from __future__ import annotations

import ipaddress
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .audit import audit_job
from .context import ContextError, ProjectContext, load_context
from .context_pack import PackError, build_pack, get_variant, load_pack, pack_is_current
from .dispatch import DispatchError, execute
from .jobs import JobError, list_jobs, load_job, summarize_job
from .media import MediaError, create_contact_sheet
from .report import status_payload
from .util import display_path, resolve_within

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ALLOWED_FILE_ROOTS = {"refs", "outputs", "exports"}
MAX_BODY_BYTES = 64 * 1024
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1"}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], project_dir: Path, config_dir: Optional[Path]):
        self.project_dir = Path(project_dir).resolve()
        self.config_dir = Path(config_dir).resolve() if config_dir else None
        self.mutation_lock = threading.Lock()
        super().__init__(address, DashboardHandler)

    def current_context(self) -> ProjectContext:
        return load_context(self.project_dir, self.config_dir)


def _loopback(name: Optional[str]) -> bool:
    return (name or "").lower() in LOOPBACK_NAMES


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "CineLockStudio/0.2"
    protocol_version = "HTTP/1.1"

    # ---------- infrastructure ----------

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host")
        if not host:
            return True
        hostname = urlparse("http://" + host).hostname
        return self._host_allowed_name(hostname)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and self._host_allowed_name(parsed.hostname)

    def _host_allowed_name(self, hostname: Optional[str]) -> bool:
        if _loopback(hostname):
            return True
        bound = str(self.server.server_address[0])
        if bound in ("0.0.0.0", "::"):
            try:
                ipaddress.ip_address(str(hostname))
                return True
            except ValueError:
                return False
        return hostname == bound

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        extra_headers: Optional[Dict[str, str]] = None,
        *,
        head_only: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head_only and body:
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200, *, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(
            body,
            "application/json; charset=utf-8",
            status,
            {"Cache-Control": "no-store"},
            head_only=head_only,
        )

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _read_json(self) -> Dict[str, Any]:
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("Content-Length 非法")
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            raise ValueError("请求体不是合法 JSON：%s" % exc)
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _static(self, filename: str, *, head_only: bool = False) -> None:
        path = (WEB_DIR / filename).resolve()
        if not path.is_file() or WEB_DIR.resolve() not in path.parents:
            self._error("静态文件不存在", 404)
            return
        body = path.read_bytes()
        self._send_bytes(
            body,
            MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            200,
            {"Cache-Control": "no-cache"},
            head_only=head_only,
        )

    def _serve_project_file(self, raw_relative: str, *, head_only: bool = False) -> None:
        relative = unquote(raw_relative).replace("\\", "/")
        parts = [part for part in relative.split("/") if part and part != "."]
        if not parts or any(part == ".." for part in parts):
            self._error("非法文件路径", 404)
            return
        if parts[0] not in ALLOWED_FILE_ROOTS:
            self._error("只允许读取 refs / outputs / exports", 403)
            return
        root = self.server.project_dir.resolve()
        target = (root.joinpath(*parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._error("文件越界", 403)
            return
        if not target.is_file():
            self._error("文件不存在", 404)
            return

        size = target.stat().st_size
        mime = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range") or ""
        if range_header.startswith("bytes=") and "," not in range_header:
            spec = range_header[6:].strip()
            try:
                if spec.startswith("-"):
                    suffix = int(spec[1:])
                    start = max(0, size - suffix)
                else:
                    left, _, right = spec.partition("-")
                    start = int(left) if left else 0
                    end = int(right) if right else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    raise ValueError
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                for key, value in SECURITY_HEADERS.items():
                    self.send_header(key, value)
                self.end_headers()
                return
            extra = {"Accept-Ranges": "bytes", "Content-Range": "bytes %d-%d/%d" % (start, end, size)}
            length = end - start + 1
        else:
            extra = {"Accept-Ranges": "bytes"}
            length = size

        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        if head_only:
            return
        try:
            with target.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- routing ----------

    def do_GET(self) -> None:
        self._route(head_only=False)

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def _route(self, *, head_only: bool) -> None:
        if not self._host_allowed():
            self._error("只接受本机访问", 403)
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._static("index.html", head_only=head_only)
            elif path == "/app.js":
                self._static("app.js", head_only=head_only)
            elif path == "/style.css":
                self._static("style.css", head_only=head_only)
            elif path == "/favicon.ico":
                self._send_bytes(b"", "image/x-icon", 204, head_only=head_only)
            elif path == "/api/status":
                self._handle_status(head_only=head_only)
            elif path == "/api/variant":
                self._handle_variant(query, head_only=head_only)
            elif path == "/api/jobs":
                self._handle_jobs(query, head_only=head_only)
            elif path == "/api/job":
                self._handle_job(query, head_only=head_only)
            elif path == "/api/audit":
                self._handle_audit(query, head_only=head_only)
            elif path.startswith("/files/"):
                self._serve_project_file(path[len("/files/") :], head_only=head_only)
            else:
                self._error("未知路径", 404)
        except (ContextError, PackError, JobError) as exc:
            self._error(str(exc), 500)
        except Exception as exc:
            self._error("服务器内部错误：%s" % exc, 500)

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._error("只接受本机访问", 403)
            return
        if not self._origin_allowed():
            self._error("拒绝跨站请求", 403)
            return
        if self.headers.get("X-CineLock") != "studio":
            self._error("缺少 X-CineLock 请求头", 403)
            return
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/build":
                self._handle_build()
            elif path == "/api/run":
                self._handle_run()
            elif path == "/api/contact-sheet":
                self._handle_contact_sheet()
            elif path == "/api/validate":
                ctx = self.server.current_context()
                from .validate import validate_context

                self._json({"ok": True, "validation": validate_context(ctx).to_dict()})
            else:
                self._error("未知路径", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except (ContextError, PackError, DispatchError, JobError, MediaError) as exc:
            self._error(str(exc), 400)
        except Exception as exc:
            self._error("服务器内部错误：%s" % exc, 500)

    # ---------- API handlers ----------

    def _handle_status(self, *, head_only: bool) -> None:
        ctx = self.server.current_context()
        self._json({"ok": True, "status": status_payload(ctx, job_limit=30)}, head_only=head_only)

    def _handle_variant(self, query: Dict[str, list], *, head_only: bool) -> None:
        shot_id = (query.get("shot_id") or [""])[0]
        provider_id = (query.get("provider_id") or [""])[0]
        if not shot_id or not provider_id:
            self._error("需要 shot_id 与 provider_id", 400)
            return
        ctx = self.server.current_context()
        pack = load_pack(ctx)
        if pack is None:
            self._error("还没有 Context Pack；先运行 build", 409)
            return
        variant = get_variant(pack, shot_id, provider_id)
        if variant is None:
            self._error("没有该镜头 × 厂商的编译结果", 404)
            return
        shot = ctx.shot(shot_id) or {}
        self._json(
            {
                "ok": True,
                "stale": not pack_is_current(ctx, pack),
                "pack_revision": pack.get("short_revision"),
                "variant": variant,
                "shot": {
                    "shot_id": shot_id,
                    "scene_id": shot.get("scene_id"),
                    "duration_sec": shot.get("duration_sec"),
                    "shot_size": shot.get("shot_size"),
                    "camera_move": shot.get("camera_move"),
                    "action_en": shot.get("action_en"),
                    "action_zh": shot.get("action_zh"),
                    "dialogue": shot.get("dialogue") or [],
                    "sfx": shot.get("sfx") or [],
                    "notes": shot.get("notes"),
                    "risk_level": shot.get("risk_level"),
                },
            },
            head_only=head_only,
        )

    def _handle_jobs(self, query: Dict[str, list], *, head_only: bool) -> None:
        limit = 50
        try:
            if query.get("limit"):
                limit = max(1, min(500, int(query["limit"][0])))
        except ValueError:
            limit = 50
        ctx = self.server.current_context()
        records = list_jobs(
            ctx,
            limit=limit,
            shot_id=(query.get("shot_id") or [None])[0],
            provider_id=(query.get("provider_id") or [None])[0],
        )
        self._json({"ok": True, "jobs": records}, head_only=head_only)

    def _handle_job(self, query: Dict[str, list], *, head_only: bool) -> None:
        job_id = (query.get("id") or [""])[0]
        if not job_id:
            self._error("需要 id", 400)
            return
        ctx = self.server.current_context()
        job = load_job(ctx, job_id)
        self._json({"ok": True, "job": job, "summary": summarize_job(job)}, head_only=head_only)

    def _handle_audit(self, query: Dict[str, list], *, head_only: bool) -> None:
        job_id = (query.get("id") or [""])[0]
        if not job_id:
            self._error("需要 id", 400)
            return
        ctx = self.server.current_context()
        job = load_job(ctx, job_id)
        self._json(
            {
                "ok": True,
                "audit": audit_job(ctx, job),
                "summary": summarize_job(job),
            },
            head_only=head_only,
        )

    def _handle_build(self) -> None:
        with self.server.mutation_lock:
            ctx = self.server.current_context()
            pack = build_pack(ctx)
            payload = status_payload(ctx, job_limit=30)
        self._json(
            {
                "ok": True,
                "revision": pack.get("context_revision"),
                "short_revision": pack.get("short_revision"),
                "stats": pack.get("stats"),
                "status": payload,
            }
        )

    def _handle_run(self) -> None:
        body = self._read_json()
        shot_id = str(body.get("shot_id") or "")
        provider_id = str(body.get("provider_id") or "")
        dry_run = bool(body.get("dry_run"))
        if not shot_id or not provider_id:
            raise ValueError("需要 shot_id 与 provider_id")
        with self.server.mutation_lock:
            ctx = self.server.current_context()
            job = execute(ctx, shot_id, provider_id, dry_run=dry_run)
        self._json(
            {
                "ok": job.get("status") not in ("failed", "blocked"),
                "job": job,
                "summary": summarize_job(job),
            }
        )

    def _handle_contact_sheet(self) -> None:
        body = self._read_json()
        job_id = str(body.get("id") or "")
        if not job_id:
            raise ValueError("需要 id")
        with self.server.mutation_lock:
            ctx = self.server.current_context()
            job = load_job(ctx, job_id)
            video_output = next(
                (
                    item
                    for item in job.get("outputs") or []
                    if item.get("kind") == "video" and item.get("path")
                ),
                None,
            )
            if video_output is None:
                raise ValueError("任务没有本地 video 输出，无法抽帧")
            video_path = resolve_within(ctx.root, str(video_output["path"]))
            if not video_path.is_file():
                raise ValueError("视频文件不存在：%s" % display_path(video_path, ctx.root))
            output_path = ctx.root / "outputs" / ("%s.contact_sheet.png" % job_id)
            sheet = create_contact_sheet(video_path, output_path)
            relative = display_path(output_path, ctx.root)
        self._json(
            {
                "ok": True,
                "job_id": job_id,
                "video": display_path(video_path, ctx.root),
                "path": relative,
                "bytes": sheet["bytes"],
                "width": sheet["width"],
                "height": sheet["height"],
                "columns": sheet["columns"],
                "rows": sheet["rows"],
                "timestamps": sheet["timestamps"],
                "probe": sheet["probe"],
            }
        )


def serve(
    project_dir: Path,
    config_dir: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = True,
) -> int:
    try:
        server = DashboardServer((host, port), project_dir, config_dir)
    except OSError as exc:
        sys.stderr.write("无法启动看板 %s:%s — %s\n" % (host, port, exc))
        return 2

    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = "http://%s:%d/" % (display_host, port)
    print("CineLock 看板 → %s" % url)
    print("项目 %s" % Path(project_dir).resolve())
    if not _loopback(host):
        print("警告：当前绑定 %s，局域网可访问；建议只用默认 127.0.0.1。" % host)
    print("按 Ctrl+C 停止")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.server_close()
    return 0

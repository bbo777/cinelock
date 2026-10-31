from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class AdapterHTTPError(Exception):
    def __init__(self, message: str, *, status: Optional[int] = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def normalize_base_url(value: Any, default: str = "") -> str:
    text = str(value or default or "").strip().rstrip("/")
    if not text:
        raise AdapterHTTPError("缺少 base_url")
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AdapterHTTPError("base_url 必须是 http(s) 地址：%s" % text)
    return text


def join_url(base: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return "%s/%s" % (base.rstrip("/"), path.lstrip("/"))


def _decode(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60,
) -> Tuple[int, Dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, method=method.upper())
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        raise AdapterHTTPError(
            "HTTP %s：%s" % (exc.code, _decode(raw)[:600]),
            status=exc.code,
            body=_decode(raw),
        )
    except urllib.error.URLError as exc:
        raise AdapterHTTPError("网络请求失败：%s（%s）" % (url, exc.reason))
    except Exception as exc:
        raise AdapterHTTPError("网络请求失败：%s（%s）" % (url, exc))


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60,
) -> Any:
    merged = {"Accept": "application/json"}
    merged.update(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        merged.setdefault("Content-Type", "application/json")
    _, _, raw = request_bytes(url, method=method, body=body, headers=merged, timeout=timeout)
    if not raw:
        return {}
    try:
        return json.loads(_decode(raw))
    except json.JSONDecodeError as exc:
        raise AdapterHTTPError("响应不是 JSON：%s（%s）" % (_decode(raw)[:300], exc))


def _multipart(
    fields: Dict[str, str],
    files: List[Tuple[str, str, bytes, str]],
) -> Tuple[bytes, str]:
    boundary = "----cinelock%s" % uuid.uuid4().hex
    chunks: List[bytes] = []
    for key, value in fields.items():
        chunks.append(
            (
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, key, value)
            ).encode("utf-8")
        )
    for field, filename, data, content_type in files:
        chunks.append(
            (
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (boundary, field, filename, content_type)
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(chunks), "multipart/form-data; boundary=%s" % boundary


def post_multipart(
    url: str,
    *,
    fields: Dict[str, str],
    files: List[Tuple[str, str, bytes, str]],
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 120,
) -> Any:
    body, content_type = _multipart(fields, files)
    merged = {"Accept": "application/json", "Content-Type": content_type}
    merged.update(headers or {})
    _, _, raw = request_bytes(url, method="POST", body=body, headers=merged, timeout=timeout)
    if not raw:
        return {}
    try:
        return json.loads(_decode(raw))
    except json.JSONDecodeError as exc:
        raise AdapterHTTPError("上传响应不是 JSON：%s（%s）" % (_decode(raw)[:300], exc))


def download_file(
    url: str,
    destination: Path,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 300,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _, _, data = request_bytes(url, headers=headers, timeout=timeout)
    destination.write_bytes(data)
    return len(data)


def image_content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or "application/octet-stream"


def image_data_uri(path: Path) -> str:
    import base64

    return "data:%s;base64,%s" % (image_content_type(path), base64.b64encode(path.read_bytes()).decode("ascii"))


def image_base64(path: Path) -> str:
    import base64

    return base64.b64encode(path.read_bytes()).decode("ascii")


def env_value(names: Any) -> Tuple[Optional[str], List[str]]:
    if isinstance(names, str):
        names = [names]
    missing: List[str] = []
    for name in names or []:
        if not isinstance(name, str) or not name:
            continue
        value = os.environ.get(name)
        if value:
            return value, missing
        missing.append(name)
    return None, missing


def get_path(payload: Any, path: str, default: Any = None) -> Any:
    current = payload
    if not path:
        return current
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
        if current is None:
            return default
    return current


def poll(
    fetch,
    *,
    timeout_sec: float,
    interval_sec: float = 2.0,
    is_done,
):
    deadline = time.monotonic() + max(1.0, timeout_sec)
    last = None
    while True:
        last = fetch()
        done, value = is_done(last)
        if done:
            return last, value
        if time.monotonic() >= deadline:
            raise AdapterHTTPError("轮询超时（%.0fs）" % timeout_sec)
        time.sleep(max(0.2, interval_sec))

"use strict";

const $ = (selector, root = document) => root.querySelector(selector);

const STATUS_LABELS = {
  ready: "可执行",
  warning: "有告警",
  needs_public_url: "待公网 URL",
  not_ready: "未就绪",
  blocked: "阻断",
  queued: "排队",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  dry_run: "演练",
  canceled: "取消",
};

const MODE_LABELS = {
  text2video: "文生视频",
  img2video: "单图首帧",
  multi_ref: "多参考图",
  first_last: "首尾帧",
};

const KIND_LETTERS = {
  mock: "M",
  handoff: "H",
  quota_flow_webview: "W",
  quota_flow_api: "A",
};

const KIND_LABELS = {
  mock: "本地适配器",
  handoff: "手工交接",
  quota_flow_webview: "网页配额",
  quota_flow_api: "API 配额",
};

const EXPR_LABELS = {
  neutral: "中性",
  determined: "坚定",
  pain: "疼痛",
};

const ROLE_LABELS = {
  identity: "身份锚点",
  geometry: "几何约束",
  expression: "表情",
  injury: "伤情",
  wardrobe: "服装",
  scene: "场景",
  style: "风格",
  keyframe_first: "首帧",
  keyframe_last: "尾帧",
};

const DURATION_CHOICE_LABELS = {
  exact: "精确",
  nearest: "就近",
  truncated: "截断",
  extended: "延长",
};

const AUDIT_LABELS = {
  pass: "通过",
  warn: "警告",
  fail: "失败",
  skip: "跳过",
};

const AUDIT_JOB_LABELS = {
  succeeded: "成功",
  failed: "失败",
  blocked: "阻断",
  dry_run: "演练",
  running: "执行中",
  canceled: "取消",
  unknown: "未知",
};

const AUDIT_CONTEXT_LABELS = {
  current: "当前修订",
  historical: "历史修订",
  unknown: "未知",
};

const state = {
  status: null,
  selectedShotId: null,
  drawer: null,
  busy: false,
};

// ---------- DOM helpers ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function add(parent, ...children) {
  for (const child of children) {
    if (child !== null && child !== undefined) parent.appendChild(child);
  }
  return parent;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function chip(text, kind, title) {
  const node = el("span", "chip" + (kind ? " " + kind : ""), text);
  if (title) node.title = title;
  return node;
}

function statusPill(status, warningCount) {
  const pill = el("span", "status-pill " + (status || "not_ready"));
  add(pill, el("i", "dot " + (status || "not_ready")), document.createTextNode(STATUS_LABELS[status] || status || "未知"));
  if (warningCount) pill.appendChild(el("span", "warn-count", "!" + warningCount));
  return pill;
}

function button(label, variant, onClick, options = {}) {
  const node = el("button", "btn " + (variant || "ghost"), label);
  node.type = "button";
  if (options.small) node.classList.add("small");
  if (options.tiny) node.classList.add("tiny");
  if (options.disabled) {
    node.disabled = true;
    if (options.title) node.title = options.title;
  }
  if (onClick) {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      onClick(event);
    });
  }
  return node;
}

function metaCell(label, value, title) {
  const cell = el("div", "meta-cell");
  add(cell, el("span", null, label), el("b", null, value === null || value === undefined || value === "" ? "—" : value));
  if (title) cell.title = title;
  return cell;
}

function fmtBytes(value) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) return (size / (1024 * 1024)).toFixed(1) + " MB";
  if (size >= 1024) return (size / 1024).toFixed(1) + " KB";
  return Math.round(size) + " B";
}

function fmtTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return date.toLocaleString("zh-CN", sameDay
    ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
    : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function fmtDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return ms + "ms";
  return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + "s";
}

function shortHash(value, length = 12) {
  return String(value || "").slice(0, length);
}

function shortJobId(jobId) {
  return String(jobId || "").replace(/^JOB_\d{8}T\d{6}Z_/, "");
}

function fileUrl(path) {
  return "/files/" + String(path || "").replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/");
}

function safeExternal(url) {
  return /^https?:\/\//i.test(String(url || "")) ? url : null;
}

function deepFindVariant(providerId) {
  const shot = currentShot();
  if (!shot) return null;
  return (shot.variants || []).find((item) => item.provider_id === providerId) || null;
}

function currentShot() {
  const shots = (state.status && state.status.pack && state.status.pack.shots) || [];
  return shots.find((item) => item.shot_id === state.selectedShotId) || shots[0] || null;
}

function characterById(id) {
  const list = (state.status && state.status.characters) || [];
  return list.find((item) => item.character_id === id) || null;
}

function characterName(id) {
  const character = characterById(id);
  return (character && character.name) || id;
}

function providerById(id) {
  const providers = (state.status && state.status.pack && state.status.pack.providers) || [];
  return providers.find((item) => item.id === id) || null;
}

function wardrobeLabel(characterId, key) {
  const character = characterById(characterId);
  if (character && character.wardrobe_labels && character.wardrobe_labels[key]) {
    return character.wardrobe_labels[key];
  }
  return key || "—";
}

function sceneLabel(shot) {
  if (!shot) return "—";
  return shot.scene_label || (shot.snapshot && shot.snapshot.scene && shot.snapshot.scene.label) || shot.scene_id || "—";
}

function shotNumber(shotId) {
  const parts = String(shotId || "").split("-");
  return parts[parts.length - 1] || shotId;
}

function modeLabel(variant) {
  return variant.mode_label || MODE_LABELS[variant.mode] || variant.mode || "—";
}

function computeVariantStatus(variant) {
  if ((variant.blockers || []).length) return "blocked";
  const dispatch = variant.dispatch || {};
  if (!dispatch.ready) {
    if (dispatch.requires_public_urls && (((dispatch.missing_public_urls || []).length) || ((dispatch.non_https_public_urls || []).length))) {
      return "needs_public_url";
    }
    return "not_ready";
  }
  return (variant.warnings || []).length ? "warning" : "ready";
}

function translateChange(characterId, change) {
  if (!change) return "";
  if (change === "state carried") return "状态延续";
  if (change === "first appearance") return "首次出场";
  let match = change.match(/^wardrobe (\S+) -> (\S+)$/);
  if (match) {
    return "服装 " + wardrobeLabel(characterId, match[1]) + " → " + wardrobeLabel(characterId, match[2]);
  }
  match = change.match(/^injury \+ (.*)$/);
  if (match) return "新增伤情 · " + match[1];
  match = change.match(/^injury - (.*)$/);
  if (match) return "移除伤情 · " + match[1];
  match = change.match(/^prop \+ (.*)$/);
  if (match) return "新增道具 · " + match[1];
  match = change.match(/^prop - (.*)$/);
  if (match) return "移除道具 · " + match[1];
  return change;
}

// ---------- networking ----------

async function api(path, options = {}) {
  const headers = Object.assign({ "X-CineLock": "studio" }, options.headers || {});
  const init = { method: options.method || "GET", headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.error) || (response.status + " " + response.statusText);
    throw new Error(message);
  }
  return data;
}

// ---------- feedback ----------

function toast(message, kind = "info", timeout = 4200) {
  const stack = $("#toast-stack");
  const node = el("div", "toast " + kind, message);
  stack.appendChild(node);
  window.setTimeout(() => {
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    window.setTimeout(() => node.remove(), 220);
  }, timeout);
}

function setBusy(on, text) {
  state.busy = on;
  const busy = $("#busy");
  busy.hidden = !on;
  if (text) $("#busy-text").textContent = text;
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast((label || "内容") + "已复制", "success", 1600);
  } catch (err) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      toast((label || "内容") + "已复制", "success", 1600);
    } catch (copyErr) {
      toast("复制失败，请手动选择文本", "error", 3000);
    }
    area.remove();
  }
}

// ---------- data loading ----------

function ensureSelection() {
  const shots = (state.status && state.status.pack && state.status.pack.shots) || [];
  if (!shots.length) {
    state.selectedShotId = null;
    return;
  }
  if (!shots.some((shot) => shot.shot_id === state.selectedShotId)) {
    state.selectedShotId = shots[0].shot_id;
  }
}

async function loadStatus(options = {}) {
  try {
    const response = await api("/api/status");
    state.status = response.status;
    ensureSelection();
    render();
    if (!options.silent) toast("已刷新", "info", 1600);
  } catch (err) {
    toast("读取失败：" + err.message, "error", 7000);
  }
}

// ---------- main render ----------

function render() {
  if (!state.status) return;
  ensureSelection();
  renderHeader();
  renderHero();
  renderEnv();
  renderTimeline();
  renderShot();
  renderJobs();
}

function renderHeader() {
  const status = state.status;
  const pack = status.pack || {};
  $("#rev-value").textContent = status.short_revision || "—";
  const pulse = $("#pack-pulse");
  const badge = $("#pack-state");
  pulse.className = "pulse";
  badge.className = "pack-badge";

  if (!pack.present) {
    pulse.classList.add("missing");
    badge.classList.add("missing");
    badge.textContent = "未构建";
    $("#rev-chip").title = "尚未生成 Context Pack";
  } else if (!pack.current) {
    pulse.classList.add("stale");
    badge.classList.add("stale");
    badge.textContent = "已过期";
    $("#rev-chip").title = "包内修订 " + (pack.short_revision || "?") + "，当前上下文已变化";
  } else {
    badge.textContent = "已同步";
    $("#rev-chip").title = "包内修订与当前上下文一致 · " + (status.revision || "");
  }

  const banner = $("#stale-banner");
  if (pack.present && !pack.current) {
    banner.hidden = false;
    $("#stale-text").textContent =
      "包内修订 " + (pack.short_revision || "?") + "，当前修订 " + status.short_revision +
      "。必须重建后才能执行，避免旧提示词发到新上下文。";
  } else {
    banner.hidden = true;
  }

  const validation = status.validation || {};
  const badgeTitle = "校验：" + (validation.error_count || 0) + " 错误 · " + (validation.warning_count || 0) + " 警告";
  badge.title = badgeTitle;
}

function renderHero() {
  const status = state.status;
  const project = status.project || {};
  const pack = status.pack || {};
  const stats = pack.stats || {};

  $("#episode-label").textContent = [project.episode_id, project.episode_title, "CONTEXT PACK"].filter(Boolean).join(" · ");
  $("#project-title").textContent = project.title || project.project_id || "—";
  $("#project-logline").textContent = [project.logline, project.setting].filter(Boolean).join(" ");

  const tags = $("#hero-tags");
  clear(tags);
  if (project.status === "placeholder") tags.appendChild(el("span", "tag amber", "占位数据"));
  const format = pack.format || {};
  if (format.aspect_ratio) tags.appendChild(el("span", "tag", format.aspect_ratio + (format.resolution ? " · " + format.resolution : "")));
  if (format.fps) tags.appendChild(el("span", "tag", format.fps + " fps"));
  if (pack.style && pack.style.palette) tags.appendChild(el("span", "tag", pack.style.palette));
  const validation = status.validation || {};
  if (validation.error_count) {
    const tag = el("span", "tag", "校验 " + validation.error_count + " 错误");
    tag.style.color = "var(--red)";
    tag.style.borderColor = "rgba(212, 86, 75, 0.4)";
    tags.appendChild(tag);
  } else if (validation.warning_count) {
    tags.appendChild(el("span", "tag", "校验 " + validation.warning_count + " 警告"));
  }

  const readyCount = (stats.statuses || {}).ready || 0;
  const cells = [
    [stats.shot_count || 0, "镜头 SHOTS", false],
    [stats.provider_count || 0, "厂商 PROVIDERS", false],
    [stats.variant_count || 0, "变体 VARIANTS", true],
    [stats.total_references || 0, "参考图 REFS", false],
    [readyCount, "可执行 READY", true],
  ];
  const root = $("#stats");
  clear(root);
  for (const [value, label, accent] of cells) {
    const cell = el("div", "stat" + (accent ? " accent" : ""));
    add(cell, el("b", null, value), el("span", null, label));
    root.appendChild(cell);
  }
}

function envChip(label, value, dotClass, title) {
  const node = el("span", "env-chip");
  if (title) node.title = title;
  add(node, el("i", "dot " + (dotClass || "")), el("span", null, label), el("code", null, value));
  return node;
}

function renderEnv() {
  const status = state.status;
  const env = status.environment || {};
  const pack = status.pack || {};
  const root = $("#env-strip");
  clear(root);

  root.appendChild(envChip("上下文", !pack.present ? "未构建" : (pack.current ? "已同步" : "已过期"),
    !pack.present ? "" : (pack.current ? "ready" : "warning")));
  root.appendChild(envChip("Python", env.python || "?", "ready"));
  root.appendChild(envChip("ffmpeg", env.ffmpeg ? "可用" : "缺失", env.ffmpeg ? "ready" : "blocked"));
  root.appendChild(envChip("Node", env.node_version ? "v" + env.node_version : "缺失",
    env.node_ok ? "ready" : "warning", "Quota-Flow 需要 Node ≥ " + (env.node_min_major || 20)));
  root.appendChild(envChip("Quota-Flow", env.quota_flow_ready ? "可用" : (env.quota_flow_found ? "环境不满足" : "未安装"),
    env.quota_flow_ready ? "ready" : "warning",
    (env.quota_flow_notes || []).join(" ")));
  root.appendChild(envChip("任务账本", (status.jobs || []).length + " 条 · " + fmtBytes(status.jobs_ledger_bytes), "ready"));

  if (!env.quota_flow_ready) {
    root.appendChild(el("span", "env-note", "真实厂商执行前需安装 Quota-Flow + Node ≥20，并给参考图补公网 https URL；当前可用 mock / handoff。"));
  }
}

// ---------- timeline ----------

function renderTimeline() {
  const shotList = (state.status.pack && state.status.pack.shots) || [];
  $("#shot-count").textContent = shotList.length ? shotList.length + " 镜" : "—";
  const root = $("#timeline");
  clear(root);

  if (!shotList.length) {
    const empty = el("div", "empty-state");
    add(empty, el("h3", null, "尚未构建"), el("p", null, "生成 Context Pack 后，这里会出现按时间线排列的镜头与连续性状态。"));
    empty.appendChild(button("构建 Context Pack", "primary", buildPack));
    root.appendChild(empty);
    return;
  }

  for (const shot of shotList) {
    const card = el("button", "timeline-card" + (shot.shot_id === state.selectedShotId ? " selected" : ""));
    card.type = "button";
    card.dataset.shot = shot.shot_id;

    const top = el("div", "tc-top");
    add(top,
      el("span", "tc-no", shotNumber(shot.shot_id)),
      el("span", "tc-scene", shot.scene_id || "—"),
      el("span", "tc-duration", (shot.duration_sec || "?") + "s"));
    card.appendChild(top);
    card.appendChild(el("div", "tc-title", sceneLabel(shot) + (shot.shot_size ? " · " + shot.shot_size : "")));
    card.appendChild(el("div", "tc-action", shot.action_zh || shot.action_en || "—"));

    const chips = el("div", "tc-chips");
    const snapshot = shot.snapshot || {};
    for (const [cid, characterState] of Object.entries(snapshot.characters || {})) {
      chips.appendChild(chip(characterName(cid) + " · " + wardrobeLabel(cid, characterState.wardrobe_state), "wardrobe"));
      if ((characterState.injuries || []).length) {
        chips.appendChild(chip("伤 " + characterState.injuries.length, "injury", characterState.injuries.join("、")));
      }
      const changes = (snapshot.changes || {})[cid] || [];
      const change = changes.find((item) => item !== "state carried") || (changes.length ? "状态延续" : "");
      if (change) chips.appendChild(chip(translateChange(cid, change), "change"));
    }
    if (chips.children.length) card.appendChild(chips);

    const dots = el("div", "tc-dots");
    for (const variant of shot.variants || []) {
      const dotNode = el("i", "mini-dot " + (variant.status || "not_ready"));
      dotNode.title = (variant.provider_id || "") + " · " + (STATUS_LABELS[variant.status] || variant.status || "");
      dots.appendChild(dotNode);
    }
    if (dots.children.length) card.appendChild(dots);

    card.addEventListener("click", () => selectShot(shot.shot_id));
    root.appendChild(card);
  }
}

function selectShot(shotId) {
  if (state.selectedShotId === shotId) return;
  state.selectedShotId = shotId;
  if (state.drawer) closeDrawer();
  renderTimeline();
  renderShot();
}

// ---------- shot panel ----------

function renderShot() {
  const pack = state.status.pack || {};
  const shot = currentShot();
  const shotTitle = $("#shot-title");
  const shotAction = $("#shot-action");
  const shotMeta = $("#shot-meta");
  const continuity = $("#continuity-card");
  const rows = $("#provider-rows");
  clear(shotMeta);
  clear(continuity);
  clear(rows);

  const canRunAll = Boolean(pack.present && pack.current) && !((state.status.validation || {}).error_count);
  $("#btn-run-mock-all").disabled = !canRunAll;
  $("#btn-run-mock-dry").disabled = !canRunAll;

  if (!shot) {
    $("#shot-eyebrow").textContent = "SHOT";
    shotTitle.textContent = pack.present ? "没有镜头" : "尚未构建 Context Pack";
    shotAction.textContent = pack.present
      ? "timeline.json 中没有可用镜头。"
      : "运行 build 后，每个镜头会为全部厂商编译一套共享上下文的提示词与参考图顺序。";
    continuity.appendChild(emptyState("连续性快照", "构建后按时间线逐镜计算服装、伤情、道具与表情。", "构建 Context Pack", buildPack));
    rows.appendChild(emptyRow(6, "先构建 Context Pack，再查看厂商矩阵。"));
    return;
  }

  $("#shot-eyebrow").textContent = "SHOT " + shot.shot_id + " · " + (shot.scene_id || "");
  shotTitle.textContent = sceneLabel(shot);
  clear(shotAction);
  shotAction.appendChild(document.createTextNode(shot.action_zh || shot.action_en || "—"));
  if (shot.action_zh && shot.action_en) shotAction.appendChild(el("span", "en", shot.action_en));

  const meta = [
    ["时长", (shot.duration_sec || "?") + "s"],
    ["景别", shot.shot_size || "—"],
    ["运镜", shot.camera_move || "—"],
    ["风险", shot.risk_level || "—"],
    ["承接", (shot.snapshot && shot.snapshot.from_shot) || "—"],
    ["角色", String((shot.character_ids || []).length) + " 人"],
  ];
  for (const [label, value] of meta) shotMeta.appendChild(metaCell(label, value));

  renderContinuity(shot, continuity);
  renderProviderRows(shot);
}

function emptyState(title, text, buttonLabel, onClick) {
  const node = el("div", "empty-state");
  add(node, el("h3", null, title), el("p", null, text));
  if (buttonLabel) node.appendChild(button(buttonLabel, "primary", onClick));
  return node;
}

function emptyRow(colspan, text) {
  const row = el("tr", "empty-row");
  const cell = el("td", null, text);
  cell.colSpan = colspan;
  row.appendChild(cell);
  return row;
}

function renderContinuity(shot, root) {
  const snapshot = shot.snapshot || {};
  const head = el("div", "cc-head");
  add(head, el("h4", null, "连续性快照 · CONTINUITY"), el("span", "cc-rev", "REV " + (state.status.short_revision || "—")));
  root.appendChild(head);

  const grid = el("div", "cc-grid");
  const characters = snapshot.characters || {};
  for (const [cid, characterState] of Object.entries(characters)) {
    const card = el("div", "char-state");
    const charHead = el("div", "char-state-head");
    add(charHead, el("span", "char-name", characterName(cid)), el("span", "char-id", cid));
    card.appendChild(charHead);

    const wardrobe = el("div", "state-line");
    add(wardrobe, el("em", null, "服装"), chip(wardrobeLabel(cid, characterState.wardrobe_state), "wardrobe"));
    card.appendChild(wardrobe);

    const expression = el("div", "state-line");
    add(expression, el("em", null, "表情"), el("span", null, EXPR_LABELS[characterState.expression] || characterState.expression || "—"));
    card.appendChild(expression);

    if ((characterState.injuries || []).length) {
      const injuries = el("div", "state-line");
      const chips = el("div", "chips");
      for (const injury of characterState.injuries) chips.appendChild(chip(injury, "injury"));
      add(injuries, el("em", null, "伤情"), chips);
      card.appendChild(injuries);
    }
    if ((characterState.props || []).length) {
      const props = el("div", "state-line");
      const chips = el("div", "chips");
      for (const prop of characterState.props) chips.appendChild(chip(prop, "prop"));
      add(props, el("em", null, "道具"), chips);
      card.appendChild(props);
    }
    const changes = (snapshot.changes || {})[cid] || [];
    if (changes.length) {
      const changeLine = el("div", "state-line");
      const chips = el("div", "chips");
      for (const change of changes) chips.appendChild(chip(translateChange(cid, change), "change"));
      add(changeLine, el("em", null, "变化"), chips);
      card.appendChild(changeLine);
    }
    grid.appendChild(card);
  }
  if (!Object.keys(characters).length) {
    grid.appendChild(el("div", "empty-state", "该镜头没有角色状态快照"));
  }
  root.appendChild(grid);

  if (snapshot.notes) root.appendChild(el("div", "cc-notes", snapshot.notes));

  const extras = el("div", "cc-extra");
  for (const line of shot.dialogue || []) {
    const item = el("div");
    add(item, el("b", null, "台词 · "), document.createTextNode(characterName(line.character_id) + "：“" + line.text + "”" + (line.delivery ? " · " + line.delivery : "")));
    extras.appendChild(item);
  }
  if ((shot.sfx || []).length) {
    const item = el("div");
    add(item, el("b", null, "音效 · "), document.createTextNode(shot.sfx.map((entry) => entry.desc + (entry.at_sec !== undefined ? " @" + entry.at_sec + "s" : "")).join(" / ")));
    extras.appendChild(item);
  }
  if (extras.children.length) root.appendChild(extras);
}

function renderProviderRows(shot) {
  const rows = $("#provider-rows");
  const providers = (state.status.pack && state.status.pack.providers) || [];
  const stale = !state.status.pack.current;
  const invalid = Boolean((state.status.validation || {}).error_count);

  for (const provider of providers) {
    const variant = (shot.variants || []).find((item) => item.provider_id === provider.id);
    if (!variant) continue;
    const row = el("tr");
    row.classList.add("clickable");
    if (variant.status === "needs_public_url" || variant.status === "not_ready") row.classList.add("dim");

    const providerCell = el("div", "provider-cell");
    const badge = el("span", "kind-badge " + (provider.kind || ""), KIND_LETTERS[provider.kind] || "?");
    badge.title = KIND_LABELS[provider.kind] || provider.kind || "";
    const name = el("div", "provider-name");
    add(name, el("b", null, provider.display_name || provider.id), el("span", null, provider.id + " / " + (KIND_LABELS[provider.kind] || provider.kind || "")));
    add(providerCell, badge, name);
    const providerTd = el("td");
    providerTd.appendChild(providerCell);

    const mode = el("td", "mode-cell");
    add(mode, el("b", null, modeLabel(variant)), el("span", null, variant.mode || "—"));

    const refs = el("td", "refs-cell", (variant.reference_count || 0) + " 张");
    const duration = el("td", "refs-cell", (variant.duration_sec || "?") + "s");

    const statusTd = el("td");
    const pill = statusPill(variant.status, variant.warning_count);
    if (variant.blocker_count) pill.appendChild(el("span", "warn-count", "阻断"));
    statusTd.appendChild(pill);

    const actions = el("td");
    const actionWrap = el("div", "row-actions");
    actionWrap.appendChild(button("详情", "ghost", () => openVariant(provider.id), { small: true }));

    const canDry = !stale && !invalid;
    actionWrap.appendChild(button("演练", "ghost", () => runProvider(provider.id, true, shot.shot_id), {
      small: true,
      disabled: !canDry,
      title: invalid ? "上下文校验有错误，先修复" : (!canDry ? "上下文已变化，先重新构建" : "演练不调用厂商、不写占位视频"),
    }));

    const execLabel = provider.kind === "handoff" ? "导出" : (provider.kind === "mock" ? "生成" : "执行");
    let execDisabled = stale || invalid || !variant.dispatch_ready;
    let execTitle = invalid ? "上下文校验有错误，先修复" : (stale ? "上下文已变化，先重新构建" : "");
    if (!stale && !invalid && !variant.dispatch_ready) {
      execTitle = variant.status === "needs_public_url" ? "先在 reference_bank.json 补 public_url" : "执行前置条件未满足；打开详情查看";
    }
    actionWrap.appendChild(button(execLabel, "primary", () => runProvider(provider.id, false, shot.shot_id), {
      small: true,
      disabled: execDisabled,
      title: execTitle,
    }));
    actions.appendChild(actionWrap);

    add(row, providerTd, mode, duration, refs, statusTd, actions);
    row.addEventListener("click", () => openVariant(provider.id));
    rows.appendChild(row);
  }

  if (!rows.children.length) rows.appendChild(emptyRow(6, "该镜头没有编译结果；重新构建。"));
}

// ---------- jobs ----------

function renderJobs() {
  const jobs = (state.status && state.status.jobs) || [];
  $("#job-count").textContent = jobs.length + " 条";
  const rows = $("#job-rows");
  clear(rows);

  if (!jobs.length) {
    rows.appendChild(emptyRow(7, "还没有任务记录。选择镜头后跑一次 mock 演练。"));
    return;
  }

  for (const job of jobs) {
    const row = el("tr", "clickable");
    row.tabIndex = 0;
    row.title = job.job_id || "";

    const idCell = el("td");
    idCell.appendChild(el("span", "job-id", shortJobId(job.job_id)));

    const pair = el("td", "job-pair");
    add(pair, el("b", null, job.shot_id || "—"), el("span", null, job.provider_display_name || job.provider_id || "—"));

    const mode = el("td", "mode-cell");
    add(mode, el("b", null, job.mode_label || MODE_LABELS[job.mode] || job.mode || "—"), el("span", null, job.adapter || ""));

    const statusCell = el("td");
    statusCell.appendChild(statusPill(job.status, job.warning_count));
    if (job.dry_run) {
      const dry = chip("演练", "change");
      dry.style.marginLeft = "5px";
      statusCell.appendChild(dry);
    }

    const time = el("td", "job-time", fmtTime(job.created_at));
    const output = el("td", "job-output", job.output_count ? job.output_count + " 个 · " + fmtDuration(job.duration_ms) : fmtDuration(job.duration_ms));

    const action = el("td");
    const wrap = el("div", "row-actions");
    wrap.appendChild(button("查看", "ghost", () => openJobById(job.job_id), { small: true }));
    wrap.appendChild(button("审计", "ghost", () => openJobById(job.job_id, { focusAudit: true }), { small: true }));
    action.appendChild(wrap);

    add(row, idCell, pair, mode, statusCell, time, output, action);
    row.addEventListener("click", () => openJobById(job.job_id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openJobById(job.job_id);
      }
    });
    rows.appendChild(row);
  }
}

// ---------- drawer shell ----------

function showDrawer() {
  const drawer = $("#drawer");
  const backdrop = $("#drawer-backdrop");
  backdrop.hidden = false;
  drawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("no-scroll");
  window.requestAnimationFrame(() => {
    drawer.classList.add("open");
    backdrop.classList.add("open");
  });
  $("#drawer-close").focus();
}

function closeDrawer() {
  const drawer = $("#drawer");
  const backdrop = $("#drawer-backdrop");
  drawer.classList.remove("open");
  backdrop.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("no-scroll");
  state.drawer = null;
  window.setTimeout(() => {
    if (!drawer.classList.contains("open")) backdrop.hidden = true;
  }, 280);
}

function setDrawerHeader(eyebrow, title, subtitleNodes) {
  $("#drawer-eyebrow").textContent = eyebrow;
  $("#drawer-title").textContent = title;
  const sub = $("#drawer-sub");
  clear(sub);
  add(sub, ...subtitleNodes.filter(Boolean));
}

function setDrawerActions(nodes) {
  const root = $("#drawer-actions");
  clear(root);
  add(root, ...nodes);
}

function section(title, tools) {
  const wrap = el("section", "drawer-section");
  const head = el("div", "section-head");
  head.appendChild(el("h4", null, title));
  if (tools && tools.length) {
    const toolWrap = el("div", "section-tools");
    add(toolWrap, ...tools);
    head.appendChild(toolWrap);
  }
  wrap.appendChild(head);
  return wrap;
}

function warningList(warnings, blockers) {
  const list = el("ul", "warning-list");
  for (const blocker of blockers || []) {
    list.appendChild(el("li", "blocker", typeof blocker === "string" ? blocker : (blocker.message || blocker.code || JSON.stringify(blocker))));
  }
  for (const warning of warnings || []) {
    list.appendChild(el("li", null, typeof warning === "string" ? warning : (warning.message || JSON.stringify(warning))));
  }
  return list;
}

function promptBlock(title, text, metaText, isNegative) {
  const block = el("div", "prompt-block");
  const tools = el("div", "prompt-tools");
  tools.appendChild(el("span", null, title + (metaText ? " · " + metaText : "")));
  tools.appendChild(button("复制", "ghost", () => copyText(text || "", title), { tiny: true }));
  block.appendChild(tools);
  const pre = el("pre", "prompt" + (isNegative ? " negative" : ""), text || "(空)");
  block.appendChild(pre);
  return block;
}

function refCard(reference) {
  const card = el("div", "ref-card");
  const image = document.createElement("img");
  image.className = "ref-thumb";
  image.alt = reference.asset_id || "reference";
  image.loading = "lazy";
  if (reference.path) {
    image.src = fileUrl(reference.path);
    image.addEventListener("error", () => {
      const placeholder = el("div", "ref-thumb placeholder", "NO IMG");
      image.replaceWith(placeholder);
    });
  } else {
    card.appendChild(el("div", "ref-thumb placeholder", "NO IMG"));
  }
  if (image.parentNode || reference.path) card.appendChild(image);

  const info = el("div", "ref-info");
  info.appendChild(el("div", "ref-order", "REF " + (reference.order || "?")));
  info.appendChild(el("b", null, reference.asset_id || "—"));
  info.appendChild(el("span", null, reference.label || ROLE_LABELS[reference.role] || reference.role || "—"));
  const role = ROLE_LABELS[reference.role] || reference.role || "—";
  info.appendChild(el("span", null, role + (reference.width && reference.height ? " · " + reference.width + "×" + reference.height : "")));
  info.appendChild(el("code", null, shortHash(reference.sha256, 12) + (reference.public_url ? " · URL ✓" : " · 本地")));
  card.appendChild(info);
  return card;
}

function outputList(job) {
  const list = el("ul", "output-list");
  for (const output of job.outputs || []) {
    const item = el("li");
    item.appendChild(el("span", "kind", output.kind || "file"));
    const target = el("span", "target");
    if (output.path) {
      const link = document.createElement("a");
      link.href = fileUrl(output.path);
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = output.path;
      target.appendChild(link);
    } else if (safeExternal(output.url)) {
      const link = document.createElement("a");
      link.href = output.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = output.url;
      target.appendChild(link);
    } else {
      target.textContent = output.url || "—";
    }
    item.appendChild(target);
    item.appendChild(el("span", "size", fmtBytes(output.bytes)));
    list.appendChild(item);
  }
  if (!list.children.length) list.appendChild(el("li", null, "没有输出"));
  return list;
}

function contactSheetSection(job) {
  const video = (job.outputs || []).find((entry) => entry.kind === "video" && entry.path);
  if (!video) return null;

  const wrap = section("抽帧九宫格 · CONTACT SHEET");
  wrap.appendChild(el("div", "cc-notes", "从本地视频均匀抽取 9 帧拼成一张图，用于快速核对运镜、角色外观与连续性。"));

  const figure = el("figure", "contact-sheet");
  figure.hidden = true;
  const image = document.createElement("img");
  image.loading = "lazy";
  image.alt = "抽帧九宫格";
  figure.appendChild(image);
  const caption = el("figcaption", null, "");
  figure.appendChild(caption);

  const actions = el("div", "section-actions");
  const run = button("生成九宫格", "ghost", async () => {
    run.disabled = true;
    run.textContent = "抽帧中…";
    try {
      const data = await api("/api/contact-sheet", { method: "POST", body: { id: job.job_id } });
      image.src = fileUrl(data.path);
      figure.hidden = false;
      caption.textContent = data.width + "×" + data.height + " · " + fmtBytes(data.bytes) +
        " · 抽帧 " + data.timestamps.map((value) => value.toFixed(2) + "s").join(" / ");
      toast("抽帧九宫格已生成", "success", 2400);
    } catch (err) {
      toast("九宫格生成失败：" + err.message, "error", 6000);
    } finally {
      run.disabled = false;
      run.textContent = "重新生成";
    }
  }, { small: true });
  actions.appendChild(run);
  wrap.appendChild(actions);
  wrap.appendChild(figure);
  return wrap;
}

function mediaPreview(job) {
  const outputs = job.outputs || [];
  const video = outputs.find((entry) => entry.kind === "video" && entry.path);
  const slate = outputs.find((entry) => entry.kind === "slate" && entry.path);
  if (!video && !slate) return null;
  const wrap = el("div", "media-preview");
  if (video) {
    const node = document.createElement("video");
    node.controls = true;
    node.preload = "metadata";
    node.src = fileUrl(video.path);
    wrap.appendChild(node);
  } else if (slate) {
    const node = document.createElement("img");
    node.loading = "lazy";
    node.alt = "mock slate";
    node.src = fileUrl(slate.path);
    wrap.appendChild(node);
  }
  return wrap;
}

// ---------- variant drawer ----------

async function openVariant(providerId) {
  const shot = currentShot();
  if (!shot) return;
  try {
    const query = "?shot_id=" + encodeURIComponent(shot.shot_id) + "&provider_id=" + encodeURIComponent(providerId);
    const data = await api("/api/variant" + query);
    state.drawer = { type: "variant", data };
    renderVariantDrawer(data);
    showDrawer();
  } catch (err) {
    toast("读取变体失败：" + err.message, "error", 6000);
  }
}

function renderVariantDrawer(data) {
  const variant = data.variant;
  const dispatch = variant.dispatch || {};
  const provider = variant.provider || {};
  const stale = Boolean(data.stale);
  const invalid = Boolean((state.status.validation || {}).error_count);
  const status = computeVariantStatus(variant);
  const statusNode = statusPill(status, (variant.warnings || []).length);

  setDrawerHeader(
    "VARIANT · " + variant.shot_id,
    provider.display_name || variant.provider_id,
    [
      statusNode,
      el("span", null, modeLabel(variant)),
      el("code", null, "REV " + (variant.short_revision || "—")),
      el("code", null, "PROMPT " + shortHash(variant.prompt_sha256)),
    ]
  );

  const body = $("#drawer-body");
  clear(body);

  if (stale) {
    const warning = warningList(["上下文已变化：这份编译结果属于旧修订，请重新构建后再执行。"], []);
    body.appendChild(warning);
  }

  const metaSection = section("参数 · PARAMETERS");
  const grid = el("div", "meta-grid");
  const durationText = variant.duration_choice && variant.duration_choice !== "exact"
    ? variant.duration_sec + "s（目标 " + variant.requested_duration_sec + "s · " + (DURATION_CHOICE_LABELS[variant.duration_choice] || variant.duration_choice) + "）"
    : variant.duration_sec + "s";
  const cells = [
    ["模式", modeLabel(variant) + " · " + variant.mode],
    ["时长", durationText],
    ["参考图", (variant.reference_count || 0) + " 张"],
    ["画幅", (variant.aspect_ratio || "—") + " · " + (variant.resolution || "—")],
    ["帧率", (variant.fps || "—") + " fps"],
    ["Seed", variant.seed_supported ? variant.seed : (variant.seed + "（仅记录）")],
    ["适配器", dispatch.adapter || "—"],
    ["提示词", variant.prompt_chars + " 字符"],
    ["候选", "#" + ((variant.candidate_index || 0) + 1)],
  ];
  for (const [label, value] of cells) grid.appendChild(metaCell(label, value));
  metaSection.appendChild(grid);
  body.appendChild(metaSection);

  if (variant.mode_reason) {
    const modeSection = section("模式选择 · MODE");
    const box = el("div", "dispatch-box");
    add(box, el("b", null, "为什么是 " + modeLabel(variant) + "？ "), document.createTextNode(variant.mode_reason));
    if (variant.mode_instruction) {
      box.appendChild(el("div", null, variant.mode_instruction));
    }
    modeSection.appendChild(box);
    body.appendChild(modeSection);
  }

  if ((variant.warnings || []).length || (variant.blockers || []).length) {
    const warnSection = section("告警与阻断 · ISSUES");
    warnSection.appendChild(warningList(variant.warnings, variant.blockers));
    body.appendChild(warnSection);
  }

  const refsSection = section("参考图顺序 · REFERENCES");
  const refGrid = el("div", "ref-grid");
  for (const reference of variant.references || []) refGrid.appendChild(refCard(reference));
  if (!refGrid.children.length) refGrid.appendChild(el("div", "empty-state", "该模式没有参考图（文生视频）"));
  refsSection.appendChild(refGrid);
  if ((variant.dropped_references || []).length) {
    refsSection.appendChild(el("p", "cc-notes", "因厂商上限被丢弃：" + variant.dropped_references.map((item) => item.asset_id || item).join("、")));
  }
  body.appendChild(refsSection);

  const promptSection = section("提示词 · PROMPT");
  promptSection.appendChild(promptBlock("正向提示词", variant.prompt, variant.prompt_chars + " 字符", false));
  if (variant.negative_prompt) {
    promptSection.appendChild(el("div", null, ""));
    promptSection.appendChild(promptBlock("负向提示词", variant.negative_prompt, variant.negative_mode || "", true));
  }
  body.appendChild(promptSection);

  const dispatchSection = section("调度 · DISPATCH");
  const dispatchBox = el("div", "dispatch-box");
  const adapterLine = el("div");
  add(adapterLine, el("b", null, "适配器："), document.createTextNode(dispatch.adapter || "—"));
  dispatchBox.appendChild(adapterLine);
  if (dispatch.quota_flow_provider || dispatch.quota_flow_mode) {
    const qfLine = el("div");
    add(qfLine, el("b", null, "Quota-Flow："), document.createTextNode((dispatch.quota_flow_provider || "—") + " / " + (dispatch.quota_flow_mode || "—")));
    dispatchBox.appendChild(qfLine);
  }
  if (dispatch.requires_public_urls) {
    const urls = el("div");
    add(urls, el("b", null, "公网参考图："), document.createTextNode((dispatch.image_urls || []).length + " 张可用"));
    if ((dispatch.missing_public_urls || []).length) {
      urls.appendChild(el("span", "warn", " · 缺 " + dispatch.missing_public_urls.join("、")));
    }
    if ((dispatch.non_https_public_urls || []).length) {
      urls.appendChild(el("span", "warn", " · 非 https " + dispatch.non_https_public_urls.join("、")));
    }
    dispatchBox.appendChild(urls);
  }
  const readyLine = el("div");
  add(readyLine, el("b", null, "就绪："), document.createTextNode(dispatch.ready ? "是" : "否"));
  if (!dispatch.ready && (dispatch.block_reasons || []).length) {
    readyLine.appendChild(el("span", "warn", " · " + dispatch.block_reasons.join("；")));
  }
  dispatchBox.appendChild(readyLine);
  if (variant.continuity && variant.continuity.notes) {
    const continuityLine = el("div");
    add(continuityLine, el("b", null, "连续性："), document.createTextNode(variant.continuity.notes));
    dispatchBox.appendChild(continuityLine);
  }
  dispatchSection.appendChild(dispatchBox);
  body.appendChild(dispatchSection);

  const actions = [];
  actions.push(button("复制提示词", "ghost", () => copyText(variant.prompt || "", "提示词")));
  actions.push(button("演练（不调用厂商）", "ghost", () => runProvider(variant.provider_id, true, variant.shot_id), {
    disabled: stale || invalid,
    title: invalid ? "上下文校验有错误，先修复" : (stale ? "上下文已变化，先重新构建" : ""),
  }));
  let primaryLabel = "执行";
  if (dispatch.adapter === "mock") primaryLabel = "生成占位视频";
  if (dispatch.adapter === "handoff") primaryLabel = "导出交接包";
  if (dispatch.adapter === "quota_flow") primaryLabel = "调用 Quota-Flow";
  if (invalid) primaryLabel = "上下文校验失败";
  else if (stale) primaryLabel = "先重新构建";
  else if (!dispatch.ready) primaryLabel = (dispatch.missing_public_urls || []).length ? "待补公网 URL" : "前置条件未满足";
  actions.push(button(primaryLabel, "primary", () => runProvider(variant.provider_id, false, variant.shot_id), {
    disabled: stale || invalid || !dispatch.ready,
    title: invalid ? "上下文校验有错误，先修复" : (stale ? "上下文已变化，先重新构建" : (!dispatch.ready ? (dispatch.block_reasons || []).join("；") : "")),
  }));
  setDrawerActions(actions);
}

// ---------- job drawer ----------

async function openJobById(jobId, options = {}) {
  try {
    const data = await api("/api/job?id=" + encodeURIComponent(jobId));
    state.drawer = { type: "job", data };
    renderJobDrawer(data.job);
    showDrawer();
    await runAudit(jobId, options);
  } catch (err) {
    toast("读取任务失败：" + err.message, "error", 6000);
  }
}

function auditLoadingSection() {
  const sec = section("连续性审计 · AUDIT");
  sec.id = "audit-section";
  sec.appendChild(el("div", "audit-summary", "正在核验修订锁、状态快照、参考图与产物哈希…"));
  return sec;
}

function auditSection(report) {
  const counts = report.summary || {};
  const verdict = report.verdict || {};
  const artifact = report.artifact_status || report.status;
  const sec = section("连续性审计 · AUDIT", [
    button("重新核验", "ghost", () => runAudit(report.job_id), { tiny: true }),
  ]);
  sec.id = "audit-section";

  const summary = el("div", "audit-summary");
  summary.appendChild(el("span", "audit-badge " + artifact, "证据链 " + (AUDIT_LABELS[artifact] || artifact)));
  summary.appendChild(
    el(
      "b",
      null,
      "通过 " + (counts.pass || 0) + " · 警告 " + (counts.warn || 0) + " · 失败 " + (counts.fail || 0) + " · 跳过 " + (counts.skip || 0)
    )
  );
  summary.appendChild(el("span", "audit-time", "核验于 " + fmtTime(report.checked_at)));
  sec.appendChild(summary);

  const layered = el("div", "audit-verdict");
  layered.appendChild(el("span", null, "任务 " + (AUDIT_JOB_LABELS[report.job_status] || report.job_status || "未知") + (report.dry_run ? "（演练）" : "")));
  layered.appendChild(el("span", null, "上下文 " + (AUDIT_CONTEXT_LABELS[verdict.current_context] || "未知")));
  layered.appendChild(el("span", "audit-badge " + (verdict.overall || artifact), "综合 " + (AUDIT_LABELS[verdict.overall || artifact] || artifact)));
  sec.appendChild(layered);

  if (!verdict.job_ok && artifact !== "fail") {
    sec.appendChild(el("div", "audit-note", "证据链通过不等于任务成功；任务状态为 " + (AUDIT_JOB_LABELS[report.job_status] || "未知") + "。"));
  }

  if (report.legacy) {
    sec.appendChild(
      el("div", "audit-note", "该任务创建于存证功能之前：只能核验提示词、参考图与产物，修订锁、快照重放与重编译比对不可用。")
    );
  }

  const list = el("div", "audit-list");
  for (const check of report.checks || []) {
    const item = el("div", "audit-item " + check.status);
    const head = el("div", "audit-item-head");
    head.appendChild(el("span", "audit-badge " + check.status, AUDIT_LABELS[check.status] || check.status));
    head.appendChild(el("b", null, check.label));
    item.appendChild(head);
    item.appendChild(el("p", "audit-detail", check.detail));
    list.appendChild(item);
  }
  sec.appendChild(list);
  return sec;
}

async function runAudit(jobId, options = {}) {
  const body = $("#drawer-body");
  if (!body) return;
  const previous = $("#audit-section");
  if (previous) previous.remove();
  body.insertBefore(auditLoadingSection(), body.firstChild);
  try {
    const data = await api("/api/audit?id=" + encodeURIComponent(jobId));
    if (!state.drawer || state.drawer.type !== "job" || state.drawer.data.job.job_id !== jobId) return;
    const host = $("#audit-section");
    if (host) host.remove();
    const rendered = auditSection(data.audit);
    body.insertBefore(rendered, body.firstChild);
    if (options.focusAudit) rendered.scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (err) {
    if (!state.drawer || state.drawer.type !== "job" || state.drawer.data.job.job_id !== jobId) return;
    const host = $("#audit-section");
    if (host) host.remove();
    const failed = section("连续性审计 · AUDIT");
    failed.id = "audit-section";
    failed.appendChild(warningList([], [{ message: "审计失败：" + err.message }]));
    body.insertBefore(failed, body.firstChild);
  }
}

function renderJobDrawer(job) {
  const render = job.render || {};
  setDrawerHeader(
    "JOB · " + (job.adapter || "").toUpperCase(),
    "任务记录",
    [
      statusPill(job.status),
      el("code", null, shortJobId(job.job_id)),
      el("span", null, (job.shot_id || "—") + " × " + (job.provider_id || "—")),
      job.dry_run ? chip("演练", "change") : null,
    ]
  );

  const body = $("#drawer-body");
  clear(body);

  if (job.error) {
    const errorSection = section("错误 · ERROR");
    errorSection.appendChild(warningList([], [{ message: job.error }]));
    body.appendChild(errorSection);
  }

  const preview = mediaPreview(job);
  if (preview) body.appendChild(preview);

  const metaSection = section("任务参数 · PARAMETERS");
  const grid = el("div", "meta-grid");
  const cells = [
    ["适配器", job.adapter || "—"],
    ["模式", render.mode_label || MODE_LABELS[render.mode] || render.mode || "—"],
    ["时长", (render.duration_sec || "?") + "s"],
    ["Seed", render.seed || "—"],
    ["状态", STATUS_LABELS[job.status] || job.status || "—"],
    ["耗时", fmtDuration(job.duration_ms)],
    ["修订", job.short_revision || "—"],
    ["提示词", shortHash(job.prompt_sha256)],
    ["创建", fmtTime(job.created_at)],
  ];
  for (const [label, value] of cells) grid.appendChild(metaCell(label, value));
  metaSection.appendChild(grid);
  body.appendChild(metaSection);

  if ((job.outputs || []).length) {
    const outputSection = section("输出 · OUTPUTS");
    outputSection.appendChild(outputList(job));
    body.appendChild(outputSection);
  }

  const sheetSection = contactSheetSection(job);
  if (sheetSection) body.appendChild(sheetSection);

  if ((job.references || []).length) {
    const refSection = section("参考图 · REFERENCES");
    const refGrid = el("div", "ref-grid");
    for (const reference of job.references) refGrid.appendChild(refCard(reference));
    refSection.appendChild(refGrid);
    body.appendChild(refSection);
  }

  if ((job.warnings || []).length || (job.variant_warnings || []).length) {
    const warnSection = section("告警 · WARNINGS");
    warnSection.appendChild(warningList(job.warnings || [], []));
    const variantWarnings = (job.variant_warnings || []).filter((item) => !(job.warnings || []).includes(item));
    if (variantWarnings.length) {
      const sub = el("div", "cc-notes", "编译阶段告警：");
      warnSection.appendChild(sub);
      warnSection.appendChild(warningList(variantWarnings, []));
    }
    body.appendChild(warnSection);
  }

  if ((job.plan || []).length) {
    const planSection = section("演练计划 · PLAN");
    const list = el("ul", "warning-list");
    for (const step of job.plan) list.appendChild(el("li", null, step));
    planSection.appendChild(list);
    body.appendChild(planSection);
  }

  if ((job.command || []).length) {
    const commandSection = section("命令 · COMMAND");
    const details = document.createElement("details");
    details.className = "command";
    details.appendChild(el("summary", null, "展开实际调用命令"));
    details.appendChild(el("pre", null, job.command.join(" ")));
    commandSection.appendChild(details);
    body.appendChild(commandSection);
  }

  const promptSection = section("提示词 · PROMPT");
  const promptDetails = document.createElement("details");
  promptDetails.className = "command";
  promptDetails.appendChild(el("summary", null, "展开任务使用的正向提示词（" + String(job.prompt || "").length + " 字符）"));
  promptDetails.appendChild(el("pre", null, job.prompt || "(空)"));
  promptSection.appendChild(promptDetails);
  body.appendChild(promptSection);

  const actions = [];
  actions.push(button("复制提示词", "ghost", () => copyText(job.prompt || "", "提示词")));
  actions.push(button("重新核验存证", "ghost", () => runAudit(job.job_id)));
  actions.push(button("再执行一次", "ghost", () => {
    state.selectedShotId = job.shot_id;
    closeDrawer();
    renderTimeline();
    renderShot();
    runProvider(job.provider_id, Boolean(job.dry_run), job.shot_id);
  }, {
    disabled: !state.status.pack.current,
    title: !state.status.pack.current ? "上下文已变化，先重新构建" : "",
  }));
  actions.push(button("关闭", "primary", closeDrawer));
  setDrawerActions(actions);
}

// ---------- actions ----------

async function buildPack() {
  if (state.busy) return;
  setBusy(true, "校验并编译全部厂商…");
  try {
    const response = await api("/api/build", { method: "POST", body: {} });
    if (response.status) {
      state.status = response.status;
      ensureSelection();
      render();
    } else {
      await loadStatus({ silent: true });
    }
    toast("Context Pack 已重建 · " + response.short_revision, "success", 5500);
  } catch (err) {
    toast(err.message || "构建失败", "error", 12000);
  } finally {
    setBusy(false);
  }
}

async function runProvider(providerId, dryRun, shotId) {
  if (state.busy) return;
  const sid = shotId || state.selectedShotId;
  if (!sid) {
    toast("没有可用镜头", "error");
    return;
  }
  setBusy(true, sid + " × " + providerId + " · " + (dryRun ? "演练中…" : "执行中…"));
  let job = null;
  try {
    const response = await api("/api/run", {
      method: "POST",
      body: { shot_id: sid, provider_id: providerId, dry_run: Boolean(dryRun) },
    });
    job = response.job;
    await loadStatus({ silent: true });
    if (response.ok) {
      const outputCount = (job.outputs || []).length;
      toast(sid + " × " + providerId + " · " + (STATUS_LABELS[job.status] || job.status) + (outputCount ? " · " + outputCount + " 个输出" : ""), "success", 6000);
    } else {
      toast(job.error || "执行被阻断", "error", 10000);
    }
  } catch (err) {
    toast(err.message || "执行失败", "error", 10000);
  } finally {
    setBusy(false);
  }
  if (job) await openJobById(job.job_id);
}

async function runAllMock(dryRun) {
  if (state.busy) return;
  const pack = state.status.pack || {};
  if (!pack.present || !pack.current) {
    toast("先重新构建 Context Pack", "error", 5000);
    return;
  }
  if ((state.status.validation || {}).error_count) {
    toast("上下文校验有错误，先修复", "error", 6000);
    return;
  }
  const shots = pack.shots || [];
  if (!shots.length) {
    toast("没有镜头可执行", "error");
    return;
  }
  let succeeded = 0;
  let failed = 0;
  try {
    for (let index = 0; index < shots.length; index += 1) {
      const shot = shots[index];
      setBusy(true, "全部镜头 " + (index + 1) + "/" + shots.length + " · " + shot.shot_id + " · " + (dryRun ? "演练" : "mock 生成"));
      const response = await api("/api/run", {
        method: "POST",
        body: { shot_id: shot.shot_id, provider_id: "mock", dry_run: Boolean(dryRun) },
      });
      if (response.ok) succeeded += 1;
      else failed += 1;
    }
    await loadStatus({ silent: true });
    toast("全部镜头完成 · 成功 " + succeeded + " · 失败/阻断 " + failed, failed ? "error" : "success", 8000);
  } catch (err) {
    toast("批量执行失败：" + err.message, "error", 9000);
    await loadStatus({ silent: true });
  } finally {
    setBusy(false);
  }
}

// ---------- events ----------

function wireEvents() {
  $("#btn-refresh").addEventListener("click", () => loadStatus());
  $("#btn-build").addEventListener("click", buildPack);
  $("#btn-build-stale").addEventListener("click", buildPack);
  $("#btn-jobs-refresh").addEventListener("click", () => loadStatus());
  $("#btn-run-mock-dry").addEventListener("click", () => runAllMock(true));
  $("#btn-run-mock-all").addEventListener("click", () => runAllMock(false));
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.drawer) closeDrawer();
  });
}

wireEvents();
loadStatus();

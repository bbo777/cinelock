# NineFlow · 九局下半

**AI 视频工业化的连续性基础设施。**

AI 视频工业化最核心的矛盾，不是“模型会不会生成”，而是：**概率模型每次都在重新采样，影视叙事却要求角色、服装、伤情、道具、场景和镜头关系绝对连续。**

NineFlow 不试图消除概率性，而是把不确定性约束进一条可锁定、可复现、可审计的上下文流水线：每个模型共享同一套参考图、同一份角色卡、同一条时间线和同一个上下文修订；任何事实源变化都会生成新修订，旧包拒绝执行。每次生成都会留下提示词、参考图哈希、渲染参数和输出哈希，让“这一镜为什么变了”可以追到具体版本。

**一句话：把概率模型的不确定性，约束进影视叙事要求的连续性边界内。**

同时内置零依赖 **MCP stdio Server**：把项目状态、编译预览、审计和九宫格暴露为 7 个工具，Claude Desktop / WorkBuddy 加 9 行配置即可调用同一套哈希锁与状态机。

> 当前仓库是**可跑通的占位骨架**：1 个角色、2 个场景、5 个镜头、4 个启用厂商（mock / qwenwan / yuanbao / handoff），共 20 个变体；另有 6 家厂商已写入矩阵但当前 CLI 未注册，默认不参与 build。角色、台词、参考图均为演示数据，替换真实内容后重新 `build` 即可。
>
> 本项目**不修改 Quota-Flow 源码**，也不保存任何 Cookie、API Key 或账号登录态。

---

## 核心矛盾与解法

多模型并行时，这组矛盾会落成四个具体的穿帮来源：

- **参考不一致**：每个模型拿到的图不一样；
- **状态被重置**：上一镜的泥污、伤口、道具到下一镜消失；
- **提示词漂移**：风格和角色描述各写各的；
- **生成不可追溯**：只剩视频，无法回答当时用了哪版角色卡。

NineFlow 的答案不是“让模型变稳定”，而是把叙事状态变成单一事实源，用四层机制约束概率性：

1. **上下文哈希锁**：项目、角色卡、参考图文件哈希、时间线、厂商能力、提示词词表与编译引擎指纹共同生成 `context_revision`；所有变体共享一个修订，旧包拒绝执行。
2. **连续性状态机**：`state_delta` 按镜头顺序演化，生成每个镜头的服装、伤情、道具、表情与场景快照；所有厂商从同一份快照编译。
3. **生成账本**：每个任务记录修订、提示词、参考图哈希、渲染参数、seed 与输出哈希，让偏离可以归因。
4. **存证与审计**：任务额外保存 `source_hashes`、完整性快照、引擎指纹与厂商投影；`audit` 重算修订锁、重放 `state_delta`、核验参考图和产物哈希，并用同一修订重编译比对，回答“这份记录还是不是当初那一份”。

> **边界**：NineFlow 保证的是**输入侧连续性与可追溯性**，不是输出侧像素级一致。模型仍可能忽略约束；单参考厂商（qwenwan / yuanbao）只适合链路验证，不作为一致性基线。输出侧的身份/服装核验仍需补。

### 它回答三个问题

- **这一镜应该是什么状态？** `state_delta` 按镜头顺序演化，编译前就确定服装、伤情、道具、表情与场景。
- **每个模型拿到的是不是同一份输入？** 所有变体共享一个 `context_revision`；厂商截断参考图时会记录 `dropped_references`，不假装各家输入相等。
- **这份记录还是不是当初那一份？** `audit` 离线重算修订锁、重放状态机、重编译比对，并核验参考图与产物哈希。

### 数据流

```text
事实源（项目 / 角色卡 / 参考图 / 时间线 / 厂商矩阵 / 词表）
        │  文件哈希 + 引擎指纹
        ▼
context_revision ── build ──▶ Context Pack（所有镜头 × 厂商共享同一修订）
        │                              │
        │                              ├─ mock / handoff / Quota-Flow 执行
        │                              ▼
        └──────────────▶ jobs/<job_id>.json（快照 + source_hashes + 产物哈希）
                                       │
                                       ▼
                    audit（重算修订锁 / 重放 state_delta / 重编译比对 / 核验文件）
```

---

## 已验证的能力

- `python -m unittest discover -s tests -v`：**62 项测试通过**。
- mock 适配器：真实生成 5s / 1920×1080 / 24fps 的 H.264 占位视频（Pillow 底板 + ffmpeg），并用 ffprobe 回读时长、分辨率与编码。
- media 模块：ffprobe 校验本地视频；ffmpeg 均匀抽 9 帧拼成 1920×1080 的 3×3 九宫格。
- handoff 适配器：导出参考图、正向/负向提示词、manifest、README 的完整手工包。
- Quota-Flow CLI 0.1.0：已安装并可被发现（自动使用自带 Node 22）；`generate` 子进程、JSON 解析、任务账本已跑通。
- Quota-Flow 适配器：能识别 CLI 的 dry-run 回包（不会误记为出片）、拒绝厂商静默替换、检查 Node/公网 URL 前置条件；下载后的视频必须通过 ffprobe 校验才算成功（没有 ffprobe 时保留文件但给出警告）。
- 连续性审计：任务保存上下文快照与引擎指纹；CLI 与看板都能逐项核验 13 项检查——修订锁、快照完整性、状态机重放、提示词、参考图、产物哈希、同修订重编译等，并能识别旧任务与历史修订。审计结果分为**证据链状态**与**任务状态**两层，不再把“任务失败”误写成“存证失败”。
- 哈希闭环：`refresh-hashes` 可把被替换参考图的记录哈希修复到实际文件；全量 `build` 才会写共享包，`build --provider` 只做预览。
- 本地看板：时间线、连续性快照、厂商矩阵、变体抽屉、任务账本、审计抽屉、视频预览、任务抽屉内一键生成抽帧九宫格、UI 内发起 mock 生成；桌面与 390px 窄屏均已验收。
- 安全校验：Host/Origin 校验、POST 自定义头、文件根目录白名单、Range 206、CSP。

**未验证 / 当前限制**：真实 Quota-Flow 厂商出片。CLI 已安装，但本机没有 qwenwan / yuanbao 登录凭据，占位参考图也没有公网 `https` URL；适配器会在执行前如实阻断，或在无凭据时把 CLI 的 dry-run 记为 `dry_run`。此外，已安装的 CLI 0.1.0 只注册了 `qwenwan`、`yuanbao` 两家（且都只支持单图首帧），README 中的 Dola / 百炼 / 智谱 / 豆包 / 火山 / TokenHub 尚未在该 CLI 中落地。

---

## 快速开始

### 环境

- Python 3.8+（已在 3.8.10 验证）。
- Pillow：mock 占位底板需要。
- ffmpeg / ffprobe：mock 视频编码、视频抽帧九宫格、Quota-Flow 下载产物校验需要。缺少 ffprobe 时仍可下载视频，但任务会带“未做媒体完整性校验”的警告；缺少 ffmpeg 时无法出片或生成九宫格。
- Node.js ≥ 20 + Quota-Flow CLI：仅真实厂商执行需要。本机已安装 CLI 0.1.0（自带 Node 22，NineFlow 可自动发现，不依赖 PATH 里的默认 Node）。

```bash
pip install -r requirements.txt
python studio.py validate
```

### 三条命令跑通

```bash
python studio.py validate      # 校验角色卡、参考图库、时间线
python studio.py build         # 编译全部厂商，生成 Context Pack
python studio.py serve         # 打开看板 http://127.0.0.1:8787/
```

`serve` 默认自动打开浏览器；加 `--no-open` 可关闭。所有生成产物都在项目目录内，不会写到系统临时目录。

### CLI 常用命令

```bash
# 查看修订、包状态、厂商能力
python studio.py status
python studio.py providers

# 查看某个镜头 × 厂商的编译结果与完整提示词
python studio.py compile --shot E01-004 --provider mock --prompt

# 只演练，不调用任何厂商
python studio.py run --shot E01-004 --provider mock --dry-run

# 生成本地占位视频（需要 ffmpeg + Pillow）
python studio.py run --shot E01-004 --provider mock

# 参考图被替换后，按实际文件修复记录哈希（不会改变 context_revision）
python studio.py refresh-hashes

# 只预览某个厂商，不写入、不覆盖共享 Context Pack
python studio.py build --provider qwenwan

# 从任务或本地视频抽 9 帧拼成 3×3 九宫格
python studio.py contact-sheet --job <job_id>
python studio.py contact-sheet --video outputs/<job_id>.mp4 --out outputs/custom.png

# 导出任意模型可用的手工交接包
python studio.py handoff --shot E01-004

# 任务账本
python studio.py jobs --limit 20
python studio.py job --id <job_id> --prompt

# 连续性审计（退出码：0 证据链通过 / 1 警告 / 2 失败）
python studio.py audit --id <job_id>
python studio.py audit --id <job_id> --json

# 以 MCP stdio Server 启动（Claude Desktop / WorkBuddy）
python studio.py --project-dir projects/nine-inning-bottom mcp
```

全局参数放在子命令之前，例如：

```bash
python studio.py --project-dir projects/nine-inning-bottom --config-dir config status
```

### 本地看板

`python studio.py serve` 默认打开 `http://127.0.0.1:8787/`，端口可用 `--port` 修改。看板与 CLI 读取同一份 Context Pack 和任务账本：

- 顶栏显示当前修订与包状态，事实源变化后会出现“上下文已变化”横幅；
- 时间线按场景展开镜头，右侧显示该镜的连续性快照；
- 厂商矩阵对比各模型的支持模式、参考上限、时长、阻断原因与警告；
- 点变体打开抽屉，查看完整提示词、负向词、参考图、投影与告警；
- 任务账本中每个任务都有“审计”入口，抽屉会运行 13 项核验并支持“重新核验”；
- 有本地视频的任务可以在抽屉里一键生成抽帧九宫格，核对运镜、角色外观与连续性；
- 视频预览与 UI 内 mock 生成。

看板只绑定 `127.0.0.1`，不要暴露到局域网或公网。

---

## MCP / API 接入

NineFlow 内置一个零依赖的 MCP stdio Server。Claude Desktop、WorkBuddy 或其他 MCP 客户端可以直接调用同一套哈希锁、状态机与审计能力，不需要额外服务或 API Key。

### 10 行配置

把下面这段加入 Claude Desktop 的 `claude_desktop_config.json`（Windows 路径：`%APPDATA%\Claude\claude_desktop_config.json`），保存后重启客户端：

```json
{
  "mcpServers": {
    "nineflow": {
      "command": "python",
      "args": ["C:/path/to/nineflow/studio.py", "--project-dir",
               "C:/path/to/nineflow/projects/nine-inning-bottom", "mcp"],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

WorkBuddy 使用同一段配置，写入 `%USERPROFILE%\.workbuddy\mcp.json`；如果文件里已有其他 server，把 `nineflow` 这一项合并进 `mcpServers` 即可。

把 `C:/path/to/nineflow` 换成仓库实际路径。若客户端找不到 `python`，把 `"command"` 换成 `where python` 返回的绝对路径。JSON 里的 Windows 路径请使用 `/`，或把 `\` 转义为 `\\`。

### 可用工具

| 工具 | 作用 | 是否写入 |
| --- | --- | --- |
| `nineflow_status` | 当前修订、镜头、厂商、Pack 状态与校验摘要 | 否 |
| `nineflow_validate` | 校验角色卡、参考图哈希、时间线与厂商配置 | 否 |
| `nineflow_variant` | 读取某个镜头 × 厂商的提示词、参考图与连续性快照 | 否（仅在内存编译） |
| `nineflow_audit` | 按 `job_id` 运行 13 项证据链审计 | 否 |
| `nineflow_jobs` | 列出任务账本，可按镜头/厂商过滤 | 否 |
| `nineflow_build` | 编译 Context Pack；默认只预览，`write=true` 才全量写入 | 显式调用时 |
| `nineflow_contact_sheet` | 从任务视频生成 3×3 抽帧九宫格 | 写入 `outputs/` |

配置完成后，可以直接在客户端里说：

- “用 nineflow_status 看一下当前修订和 5 个镜头。”
- “把 E01-004 × mock 的完整提示词和参考图给我。”
- “审计 JOB_...，分别告诉我证据链结论和任务状态。”

### 安全边界

- 只使用 stdio，不监听端口，不发起网络请求；
- 项目目录在进程启动时固定，工具不能遍历到任意路径；
- `nineflow_build` 默认只预览，写共享包必须显式传 `write=true`，且不允许和 `provider_id` 同时使用；
- MCP 客户端拥有当前用户的本地文件权限，只连接可信客户端；
- Quota-Flow 的登录凭据不会通过 MCP 暴露；MCP 工具不执行真实厂商调用。

---

## 目录

```text
studio.py                     CLI 入口
nineflow/
  context.py                  加载四个事实源，计算 context_revision
  validate.py                 结构、引用、连续性、厂商能力校验
  continuity.py               按镜头顺序应用 state_delta，生成快照
  compiler.py                 参考图选择、模式选择、提示词与时长适配
  context_pack.py             打包 context_pack.json / CONTEXT.md / 分镜变体
  dispatch.py                 新鲜度检查、适配器调度、任务状态机
  jobs.py                     单个任务 JSON + append-only jobs.jsonl + 上下文存证
  hashes.py                   参考图记录哈希与实际文件对齐（refresh-hashes）
  media.py                    ffprobe 探测 + ffmpeg 抽帧九宫格
  audit.py                    修订锁、快照重放、参考图/产物/重编译核验
  mcp_server.py               MCP stdio Server（状态 / 编译 / 审计 / 九宫格）
  adapters/mock.py            占位底板 + ffmpeg 编码
  adapters/handoff.py         手工交接包
  adapters/quota_flow.py      Quota-Flow CLI 子进程与结果解析
  dashboard.py                本地看板 HTTP 服务
  report.py                   CLI 与看板共用的状态载荷
  cli.py / environment.py
config/
  providers.json              厂商能力矩阵与 Quota-Flow CLI 映射
  prompt_maps.json            风格、景别、运镜等词表
web/                          无外部依赖的看板前端
projects/nine-inning-bottom/
  project.json                项目/风格/画幅/默认策略
  characters.json             角色卡
  reference_bank.json         参考图库（本地路径 + 可选 public_url）
  timeline.json               场景、镜头、连续性 state_delta
  refs/                       演示用占位参考图
  context/                    构建产物（含预构建的 Context Pack）
  jobs/ outputs/ exports/     任务账本、视频、交接包（运行时生成）
tests/                        unittest 测试
```

---

## 唯一事实源

### 一个修订，所有模型共用

`context_revision` 是对以下内容计算的 SHA-256：

- 项目设定与风格；
- 角色卡；
- 参考图库（记录中的 `sha256` 字段会被实际文件哈希替换）；
- 时间线；
- 厂商能力矩阵（含项目覆盖项）；
- 提示词词表；
- 每个参考图的实际文件哈希；
- 编译引擎指纹：NineFlow 版本 + `context.py` / `compiler.py` / `continuity.py` 的源码 SHA-256。

因此：

- 只更新记录里的 `sha256` 文本，不会产生新修订；
- 替换图片字节、改角色卡、改时间线、改厂商能力，都会产生新修订；
- 每个变体都记录同一个修订；构建时若发现不一致，直接失败；
- 执行前若发现磁盘上的上下文已变化、包内还是旧修订，`execute` 直接拒绝，提示重新 `build`；
- 看板用同一个 `status_payload`，CLI 与 UI 不会各算一套状态。

### 参考图换了，哈希怎么修

替换参考图文件后，`validate` / `build` 会报告 `sha256 不匹配`。如果新图是你要的版本：

```bash
python studio.py refresh-hashes
python studio.py build
```

- `refresh-hashes` 会重新计算每张参考图的实际 SHA-256，并原子写回 `reference_bank.json`；
- 任何一张图缺失或不可读，整次刷新直接失败，不写入部分结果；
- 刷新只改“记录值”。`context_revision` 由实际文件哈希决定，所以刷新本身不产生新修订，真正改变修订的是图片字节；
- `build --provider X` 只编译并打印统计，**不写入共享包**；共享 `context_pack.json` 仍然只由全量 `build` 写入，避免一次单厂商预览把其他厂商的变体从包里抹掉。

### 连续性快照

时间线是唯一允许修改角色状态的地方：

```json
{
  "shot_id": "E01-004",
  "continuity": {
    "from_shot": "E01-003",
    "state_delta": {
      "CH_LINYE_01": {
        "wardrobe_state": "home_injured",
        "add_injuries": ["bruise on left cheek", "small cut on lower lip"]
      }
    }
  }
}
```

`continuity.py` 按镜头顺序累积服装、伤情和道具，生成每个镜头的快照。所有厂商都从同一份快照编译，不允许各自维护状态。

### 参考图顺序

编译器先收集参考图，再按角色出现顺序与优先级排序，最后按厂商 `max_refs` 截断；被截断的参考图记入 `dropped_references`。

```text
镜头覆盖 override > 身份锚点 identity > 几何 geometry > 表情 expression
> 伤情 injury > 服装 wardrobe > 场景 scene > 风格 style
```

多参考模式下会为每个出场角色保留身份锚点；参考上限不足以容纳所有出场角色时直接阻断。单图厂商只能拿到第 1 张身份锚点（`identity_first_frame`），geometry / expression / injury 会退化为提示词描述。

### 提示词结构

每个变体的提示词由以下部分组成，顺序固定：

1. 风格锚点；
2. 角色描述与当前服装/伤情/道具；
3. 场景、光线、构图；
4. 景别、运镜、动作、表演；
5. 连续性说明（承接镜头与状态变化）；
6. 按顺序编号的参考图图例；
7. 模式指令（多参考 / 单图首帧 / 文生 / 首尾帧）；
8. 质量后缀；
9. 厂商不支持独立负向词时，追加 `Avoid: ...`。

负向词模式会记录为 `separate` 或 `inline`，并同时保存哈希。

### 连续性存证与审计

任务创建时，NineFlow 会把当时的上下文固化成一份可重算的存证：

- `provenance.source_hashes`：项目、角色卡、参考图库、时间线、厂商矩阵、提示词词表、每个参考图文件哈希与引擎指纹；
- `provenance.context_snapshot` 与 `context_snapshot_sha256`：这一镜编译时使用的服装、伤情、道具、表情与场景快照；
- `provenance.engine`：NineFlow 版本与 `context.py` / `compiler.py` / `continuity.py` 的源码哈希；
- `projection`：厂商 `max_refs`、实际进入的参考图数量、被截断的参考图；
- `outputs`：每个本地产物的路径、字节数与 SHA-256。

`python studio.py audit --id <job_id>` 会逐项核验 13 项：

| # | 检查 | 回答的问题 |
| --- | --- | --- |
| 1 | 上下文存证 | 任务是否保存了 schema、捕获时间与完整存证 |
| 2 | 修订锁 | 任务记录的修订号，是否等于 `source_hashes` 的重算值 |
| 3 | 引擎指纹 | 编译引擎是否仍是当初那一版；版本或源码变化只警告，不判篡改 |
| 4 | 快照完整性 | 快照是否在创建后被改写 |
| 5 | 状态机重放 | 按当前时间线重跑 `state_delta`，是否得到同一份快照 |
| 6 | 提示词完整性 | 提示词与负向词是否仍匹配记录的哈希 |
| 7 | 参考图完整性 | 本地参考图是否仍存在、哈希是否一致 |
| 8 | 产物完整性 | 本地视频 / 底板 / 交接包是否仍匹配记录的哈希 |
| 9 | 同修订重编译 | 同一修订重新编译，`variant_sha256`、`prompt_sha256` 与快照是否一致 |
| 10 | 状态约束覆盖 | 快照里的每个角色，是否都被参考图覆盖且服装状态一致 |
| 11 | 参考图投影 | 厂商上限截断了哪些参考图，各模型实际看到的输入是否相等 |
| 12 | 当前修订 | 这是当前任务，还是基于历史修订 |
| 13 | Context Pack | 包是否与当前修订一致，能否用于重编译比对 |

一个全部通过的任务输出如下（节选）：

```text
连续性审计 · JOB_...
E01-001 × handoff · 适配器 handoff · 修订 3363f8fde6e7 · 当前 3363f8fde6e7
证据链 通过 · 任务 成功 · 上下文 当前修订
证据链结论 通过 · 通过 13 · 警告 0 · 失败 0 · 跳过 0

[通过] 修订锁
       存证 source_hashes 与任务修订一致 · 3363f8fde6e7
[通过] 状态机重放
       按时间线重放 state_delta，服装、伤情、道具、表情与场景逐字段一致。
[通过] 同修订重编译
       同一修订重新编译得到相同的 variant_sha256、prompt_sha256 与连续性快照。
```

审计把两件事拆开报告：

- **证据链**：`status` / `artifact_status`，只回答任务记录、参考图、产物与约定修订是否仍然一致；
- **任务本身**：`job_status` 与 `dry_run`，回答生成是成功、失败、阻断还是演练。

`verdict.overall` 再合成二者：证据链 `fail` → `fail`；证据链 `warn`、任务非成功、或上下文是历史/未知修订 → `warn`；其余 `pass`。CLI 退出码和顶层 `ok` 仍只看证据链，方便 CI 区分“记录被篡改”与“生成失败”。因此一个 `failed` 任务完全可以得到“证据链通过、退出码 0、任务状态失败、overall 警告”的组合，这是有意设计，不是漏报。

证据链结论分三档：`pass`（全部一致）、`warn`（旧任务、历史修订、引擎变化或厂商输入边界）、`fail`（存证、参考图或产物被改写或缺失）。看板任务抽屉会自动运行同一套审计，并提供“重新核验”。

想确认审计确实在工作：先跑一个 mock 任务并 `audit`（应为 13 项通过）；再在项目副本里改动任意参考图或产物字节，重新 `audit`，对应完整性检查会变成失败，退出码为 2。

审计是**离线一致性核验**，不是密码学签名：它能发现文件漂移、误改和朴素篡改；对同时拥有任务 JSON 与磁盘写权限的人，无法阻止其重写全部哈希。远程 URL 产物与公网参考图不做联网抓取，只核验本地副本。它也不判断视频像素、人脸或服装在成片里是否真的连续。

---

## Provider 矩阵

默认 build 只包含已启用的 4 家；未注册厂商保留在 `config/providers.json` 作为规划，显式选择会被编译阶段阻断。

### 已启用（参与默认 build）

| ID | 显示名 | 类型 | 支持模式 | 参考上限 | 可选时长 |
| --- | --- | --- | --- | --- | --- |
| `mock` | Mock（本地演练） | 本地适配器 | text2video / img2video / multi_ref / first_last | 10 | 3/4/5/6/8/10s |
| `qwenwan` | 千问·通义万相 | Quota-Flow CLI 0.1.0 | text2video / img2video | 1 | 5s |
| `yuanbao` | 腾讯元宝·混元 | Quota-Flow CLI 0.1.0 | text2video / img2video | 1 | 5s |
| `handoff` | 手工交接包（任意模型） | 本地导出 | text2video / img2video / multi_ref / first_last | 10 | 3/4/5/6/8/10s |

`qwenwan` / `yuanbao` 在 CLI 0.1.0 中只接受单图首帧，所以每个镜头只拿第 1 张身份锚点；其余参考图与状态继续进入提示词。多参考/首尾帧仍可通过 mock 校验或 handoff 导出给其他模型使用。

### 规划中（当前 CLI 未注册，默认停用）

| ID | 显示名 | 规划模式 |
| --- | --- | --- |
| `dola` | Dola（Dreamina Seedance） | multi_ref |
| `bailian` | 阿里云百炼（万相） | text2video / img2video / multi_ref / first_last |
| `zhipu` | 智谱·清影 / Vidu | text2video / img2video / multi_ref / first_last |
| `doubao` | 豆包 | text2video / img2video |
| `volcengine` | 火山方舟（Seedance） | text2video / img2video |
| `tokenhub` | 腾讯云 TokenHub（混元） | text2video / img2video |

这些厂商已写入能力矩阵并带 `enabled: false` / `cli_available: false`。直接 `compile --provider dola` 会得到 `B_PROVIDER_DISABLED` 与 `B_CLI_PROVIDER_UNAVAILABLE` 阻断，不会把请求静默转给千问。CLI 升级并注册新厂商后，改回 `enabled: true` / `cli_available: true` 并补齐模式映射即可。

### 模式选择

按以下顺序自动选择：

1. 有首帧和尾帧，且厂商支持 `first_last` → 首尾帧；
2. 厂商只支持单图，且存在首帧关键帧 → 单图首帧；
3. 厂商支持多参考 → 多参考图；
4. 只有单图能力 → 拿身份锚点做单图首帧，并给出降级警告；
5. 其余 → 文生视频。

### 时长适配

每个变体记录：

- `requested_duration_sec`：时间线要求的时长；
- `duration_sec`：该厂商实际可选的最接近值；
- `duration_choice`：`exact` / `nearest` / `truncated` / `extended`。

Quota-Flow CLI 本身不允许传时长，因此时长只影响提示词、计划和记录，最终由厂商模型决定。

---

## 接入真实 Quota-Flow

### 1. 安装与发现

本机已通过 Node 22 的 npm 全局安装 `@quota-flow/cli@0.1.0`，入口类似：

```text
D:\nvm\nodejs\quota-flow.cmd
```

NineFlow 会依次查找：

1. `QUOTA_FLOW_CLI` 指定的路径；
2. `PATH` 中的 `quota-flow` / `quota-flow.cmd`；
3. Windows 常见的 nvm / `%APPDATA%\npm` / `Program Files\nodejs` 全局入口。

找到 npm 的 `.cmd` 后，如果同目录有 `node.exe` 和 `node_modules/@quota-flow/cli/dist/cli.cjs`，NineFlow 会直接用自带 Node 执行 JS 入口，绕开 PATH 里的默认 Node 14。也可以显式指定：

```bash
set QUOTA_FLOW_CLI=D:\nvm\nodejs\quota-flow.cmd
set QUOTA_FLOW_NODE=D:\nvm\nodejs\node.exe
```

验证：

```bash
quota-flow --version
quota-flow check-quota --json
python studio.py status
```

本机实际输出只包含 `qwenwan`、`seedance`、`yuanbao`；其中 `seedance` 额度为 0 且未注册，**可自动调度的只有 qwenwan / yuanbao**。

### 2. 登录凭据

CLI 的 `fetch` 引擎从 `~/.quota-flow/` 读取登录态，NineFlow 不读取、不保存、不上传这些文件：

- `qwen-auth.json`：至少包含 `cookie`、`deviceId`、`sessionId`；可选 `reqId`。
- `yuanbao-auth.json`：至少包含 `cookie`、`agentId`、`conversationId`。

`--engine browser` 在当前 CLI 中只实现了 yuanbao（会打开真实 Edge），qwenwan 仍走静态凭据。登录态由用户自己完成；不要把 Cookie / API Key 写进本仓库。

**注意（CLI 0.1.0 行为）**：缺少上述 JSON 时，`quota-flow generate` 不会报错退出，而是返回 `ok: true` 的 dry-run 结果，并且可能照样扣减本地额度。NineFlow 会识别 `traceId` / `raw.warning` 中的 dry-run 标记，把任务记为 `dry_run` 而不是 `succeeded`，同时提示“未生成真实视频”和“可能已扣减额度”。可用 `quota-flow refresh` 重置当日演示额度（`totalSuccessful` 等累计值不会清零）。

### 3. 给参考图补公网 URL

Quota-Flow 只接受公网 `https` 图片。编辑 `reference_bank.json` 每个 asset：

```json
{
  "asset_id": "REF_LINYE_FRONT_V01",
  "path": "refs/characters/linye/linye_front_v01.png",
  "public_url": "https://your-cdn.example/nineflow/linye_front_v01.png"
}
```

然后重新构建：

```bash
python studio.py build
```

缺少 `public_url` 或不是 `https` 时，相应变体会显示 `待公网 URL`，真实执行被阻断；dry-run 仍可查看完整命令与提示词。

### 4. 先演练，再执行

```bash
python studio.py run --shot E01-001 --provider qwenwan --dry-run
python studio.py run --shot E01-001 --provider qwenwan
```

第一条只生成执行计划，不调用 CLI；第二条才会真正调用。若登录态或公网 URL 缺失，任务会分别记为 `dry_run` / `blocked`。

可用环境变量：

```bash
# 指向 CLI 入口（当不在 PATH 时）
set QUOTA_FLOW_CLI=D:\nvm\nodejs\quota-flow.cmd

# 显式指定跑 CLI 的 Node（可选；自动发现失败时使用）
set QUOTA_FLOW_NODE=D:\nvm\nodejs\node.exe

# 可选 fetch / browser；CLI 0.1.0 的 browser 只实现了 yuanbao
set NINEFLOW_QF_ENGINE=fetch

# 建议保持 0：非 0 时 Quota-Flow 可能切换到其他厂商，破坏逐厂商对比
set NINEFLOW_QF_FALLBACK_ROUNDS=0

# 默认拒绝“请求 A、实际用 B”的静默替换；设为 1 才接受
set NINEFLOW_QF_ALLOW_PROVIDER_SWITCH=0

# 单次执行超时，默认 1800 秒
set NINEFLOW_QF_TIMEOUT_SEC=1800
```

### 5. 任务账本

每次执行都会写：

- `jobs/<job_id>.json`：完整任务快照；
- `jobs/jobs.jsonl`：append-only 事件流（queued / running / 终态）。

记录包括修订号、`source_hashes`、连续性快照与快照哈希、引擎指纹、厂商投影、提示词与负向词哈希、参考图快照、模式、时长、seed、命令、输出文件、stdout/stderr 尾部、警告和错误。

---

## 替换占位内容

1. **角色**：编辑 `characters.json`，补 `descriptor`、`identity_invariants`、服装状态、表情参考和负向词。
2. **参考图**：把真实图片放进 `refs/`，更新 `reference_bank.json` 的 `asset_id`、`path`、`status`；`build` 会自动计算实际哈希并写入包。
3. **时间线**：编辑 `timeline.json` 的场景、镜头、台词、音效和 `state_delta`。状态变化只写在这里。
4. **厂商**：按真实能力修改 `config/providers.json`；项目级覆盖写到 `project.json` 的 `provider_overrides`。
5. **重建**：`python studio.py validate && python studio.py build`。旧包会自动失效，看板显示“上下文已变化”。

仓库里保留了一份预构建的 `context/context_pack.json` 方便直接查看看板；修改任何事实源后都必须重新构建。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：

- 修订稳定性与失效；
- 连续性状态演化；
- 参考图上限、身份锚点、模式选择、时长适配、提示词内容与确定性；
- mock 真实出片、handoff 包完整性、Quota-Flow 前置阻断、旧包拒绝；
- CLI dry-run 识别、厂商静默替换拒绝、默认厂商矩阵与规划厂商阻断；
- 审计通过、快照/修订/参考图/产物篡改、历史修订、旧任务降级、任务状态与证据链分层、审计 API 与 CLI；
- 看板 API、CSRF/Host/Origin、路径穿越、文件 Range、九宫格接口与本地视频前置检查；
- CLI 的 validate / build / status / compile / run / jobs / job / audit / refresh-hashes / contact-sheet 全链路；
- 哈希漂移修复、缺失参考图时拒绝写入、部分构建不覆盖共享包、重建清理过期变体文件；
- ffprobe 探测、3×3 九宫格尺寸与时间戳、坏视频报错；
- MCP 初始化、工具目录、状态/变体只读、预览不写包、审计与任务账本、stdio 往返。

mock 出片与九宫格测试在缺少 ffmpeg / ffprobe / Pillow 时自动跳过。

---

## 设计边界与一致性限制

- **一致性是概率性的**：同一套参考图与快照能显著降低漂移，但不能保证每个模型像素级一致。
- 单图厂商丢失几何、表情、伤情参考，只剩身份锚点与文字描述，是最容易漂移的路径。
- 已安装的 Quota-Flow CLI 0.1.0 只注册 `qwenwan` / `yuanbao`，两家都只有单图首帧；多参考厂商仍需 handoff。
- CLI 在缺少登录态时会返回 dry-run，并可能扣减本地额度；NineFlow 只把它记为 `dry_run`，不会当作成功视频。
- CLI 对未注册的 `--provider` 会静默回退到千问；NineFlow 默认拒绝这种厂商不一致，避免对比结果串台。
- Quota-Flow CLI 没有时长与 seed 参数；实际时长、运动细节和随机性由厂商决定。
- 首尾帧模式只有在时间线提供 `keyframes.first` / `keyframes.last` 时才会启用；占位数据没有关键帧。
- 当前没有自动人脸评分、镜头完成度判断、音频/口型、自动重试与人工审片队列。
- ffprobe 只验证容器、视频流、时长与分辨率；它不能证明画面里的人脸、服装或伤情连续。九宫格是人工审片的辅助视图，不是自动质检。
- mock 输出只是占位底板，不能用来判断真实模型质量。
- 审计能证明“任务记录与当前磁盘上的参考图/产物仍一致”，不能证明成片里的人脸、服装和伤情真的连续；输出侧仍需人工或视觉模型审片。
- 审计不是密码学签名，只防漂移与朴素篡改；拥有任务 JSON 与磁盘写权限的人可以同时改写存证与产物。
- 看板是单机工具，没有多用户认证，不应暴露到局域网或公网。

## 安全与合规

- 看板默认绑定 `127.0.0.1`，校验 Host/Origin，POST 必须带 `X-NineFlow: studio`，文件只能读 `refs/`、`outputs/`、`exports/`，并限制路径穿越。
- Context Pack 与 handoff 包只包含提示词、参考图副本和元数据，不包含 Cookie、API Key 或登录态。
- 公网参考图需要你自行上传并确认访问权限；上传前请检查素材版权、肖像授权与隐私内容。
- 真实生成时请遵守各厂商服务条款与配额规则。本项目只做连续性编排、调度与审计，不绕过配额、不提供账号共享或风控规避。
- 角色、剧本、参考图的权利与授权由使用者负责。

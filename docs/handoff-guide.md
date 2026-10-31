# Handoff 傻瓜式操作指南

> 这份文档写给两种人：**没有算力、想把镜头交给别人生成的作者**，和**拿到交接包、愿意帮忙跑一个镜头的朋友**。
>
> 目标：你不需要理解 CineLock 的全部代码，也能把一个镜头从“交接包”变成“可审计的外部产物”。

---

## 0. 先搞清楚 Handoff 是什么

Handoff 是 CineLock 的**算力众包协议**。它把一个镜头在某一修订下的全部输入打包：

```text
exports/handoff/<job_id>/
  README.md          这个镜头的人类可读说明
  manifest.json      修订号、提示词哈希、参考图顺序、时长、画幅、seed
  prompt.txt         正向提示词（整段粘贴）
  negative.txt       负向提示词（如果该变体有）
  refs/
    01_<asset_id>.png  第 1 张：身份锚点（必须最先上传）
    02_<asset_id>.png  第 2 张：几何 / 表情 / 伤情 / 服装……
    ...
```

它**能**保证：

- 所有参考图、提示词和状态快照来自同一个 Context Pack；
- 回传结果能通过 `context_revision` 与 `prompt_sha256` 绑定到同一个上下文；
- 外部视频会被登记进任务账本，记录 SHA-256、ffprobe 元数据和来源声明；
- 同一套 13 项审计能检查“文件有没有被改、是不是还绑在同一个修订上”。

它**不能**保证：

- 视频真的由你声明的模型生成（CineLock 不联网鉴定生成来源）；
- 画面里的脸、服装、伤情、道具真的连续（这需要人工或视觉模型审片）；
- 外部平台一定听话。概率模型仍可能忽略参考图和提示词。

---

## 1. 导出交接包（作者侧，0 算力）

在仓库根目录执行：

```bash
python studio.py build
python studio.py handoff --shot E01-004
```

- `build` 必须是最新的。上下文变了但包没重建，`handoff` 会基于旧包导出，后续 `import` 会被拒绝。
- `handoff` 会生成一条任务记录，并把包写到 `exports/handoff/<job_id>/`；加 `--zip` 会同时打包成 `<job_id>.zip`。
- 终端会打印任务 ID 和导出路径；也可以运行 `python studio.py jobs --limit 5` 查看。
- 在 MCP 客户端里，可以让 Agent 直接调用 `cinelock_handoff_export`（`format` 选 `zip` 或 `folder`），例如“把 E01-004 的交接包导出成 zip”。

想先看会导出什么、不写文件：

```bash
python studio.py handoff --shot E01-004 --dry-run
```

---

## 2. 选择外部模型（朋友侧）

先看 `manifest.json` 里的 `mode`，再决定怎么喂：

| manifest.mode | 含义 | 推荐用法 |
| --- | --- | --- |
| `multi_ref` | 多参考图 | 优先选支持多图参考的视频模型；按顺序上传全部 `refs/` |
| `img2video` | 单图首帧 | 只上传第 1 张身份锚点，其余状态靠 `prompt.txt` 描述 |
| `first_last` | 首尾帧 | 按 `role` 找 `first_frame` / `last_frame`，分别作为首帧和尾帧 |
| `text2video` | 文生视频 | 不上传参考图，直接粘贴提示词（一致性最弱，不推荐用于角色镜头） |

几个常见平台的实际定位（能力会变，以平台当前界面为准）：

- **Midjourney**：图像生成，不直接产出视频。适合先用 `prompt.txt` + `refs/` 生成/挑选关键帧，再把关键帧交给视频模型。不要把它当成视频模型回传。
- **可灵 / 即梦 / Runway**：支持图生视频；多参考、首尾帧和时长上限各家不同。能多图就按顺序多图，只能单图就只用第 1 张身份锚点。
- **ComfyUI**：本地或远程工作流，支持多参考与首尾帧；前提是你已经有一张能跑视频的显卡，并把节点图导出为 API 格式。
- **可灵 / Runway 官方 API**：CineLock 内置预设，可直接提交并轮询；官方接口的参考上限分别是 2 张和 1 张，单图路径一致性最弱。

> 原则：**身份锚点永远第 1 张，顺序不要改。** 参考图顺序本身就是一致性约束的一部分。

---

## 3. 按 manifest 操作（不要凭感觉）

打开 `manifest.json`，重点看这些字段：

```json
{
  "shot_id": "E01-004",
  "mode": "multi_ref",
  "duration_sec": 6,
  "aspect_ratio": "16:9",
  "resolution": "1920x1080",
  "fps": 24,
  "seed": 20251031,
  "context_revision": "完整 64 位修订号",
  "short_revision": "前 12 位",
  "prompt_sha256": "完整提示词哈希",
  "references": [
    {"order": 1, "asset_id": "REF_LINYE_FRONT_V01", "role": "identity", "file": "refs/01_REF_LINYE_FRONT_V01.png"},
    {"order": 2, "asset_id": "REF_LINYE_SIDE_V01", "role": "geometry", "file": "refs/02_REF_LINYE_SIDE_V01.png"}
  ]
}
```

操作顺序：

1. 打开目标平台的视频生成界面。
2. 按 `references[].order` 从 1 开始上传 `refs/` 里的图。第 1 张必须是 `identity`。
3. 把 `prompt.txt` **整段**粘贴到正向提示词框。不要自己删“无关”的连续性描述。
4. 如果平台有独立负向提示词框，并且包里有 `negative.txt`，整段粘贴。
5. 设置时长、画幅、分辨率。平台没有目标时长时选最接近的；CineLock 会在导入时给出时长不一致警告。
6. 平台支持 seed 就填 `manifest.seed`；不支持就跳过。seed 只用于记录，不保证跨平台复现。
7. 生成。失败也是有效结果：把失败现象记下来，回传时写进 `--note`。

### 省钱抽卡顺序

1. 先用免费/低价图像额度把关键帧抽对（脸、球衣号码、伤情、场景光线）。
2. 关键帧满意后，再用图生视频，只重抽视频，不重抽关键帧。
3. 每次重抽都保留同一张身份锚点，不要因为“这张更好看”换掉身份图。
4. 一条镜头最多先跑 1 个候选；确认方向对了再加候选，避免把额度烧在错误构图上。

---

## 4. 回传前自检

拿到视频后，先确认：

- 文件是 `.mp4` / `.mov` / `.webm`；
- 时长与 `manifest.duration_sec` 接近（差 1 秒内最好）；
- 分辨率与 `manifest.resolution` 一致（不一致也能导入，但会有警告）；
- 画面里没有平台水印遮挡关键部位（审计不检查水印，但审片会受影响）；
- 你没有把参考图顺序打乱，也没有换掉身份锚点。

有 ffprobe 的话，可以先自己看一眼：

```bash
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name -of default=noprint_wrappers=1 "你的视频.mp4"
```

没有 ffprobe 也能导入，只是任务会带“未做媒体完整性校验”的警告。

---

## 5. 登记进账本并审计（作者侧）

把外部视频放回本机，执行：

```bash
python studio.py import --shot E01-004 \
  --video "/path/to/kling_E01-004.mp4" \
  --model "Kling 2.5" \
  --revision <manifest.short_revision> \
  --prompt-hash <manifest.prompt_sha256> \
  --note "5 张参考图按顺序上传；第 2 次抽卡；右袖撕裂在第 1 秒后出现"
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--shot` | 是 | 镜头 ID，例如 `E01-004` |
| `--video` | 是 | 本地视频路径，支持 `.mp4` / `.mov` / `.webm` |
| `--model` | 建议 | 生成模型名，会写进任务与看板；不填记为“未声明” |
| `--revision` | 建议 | `manifest.short_revision` 或更长的前缀，至少 8 位；不填默认使用当前修订 |
| `--prompt-hash` | 建议 | `manifest.prompt_sha256` 或前 12 位；不填默认使用当前编译结果 |
| `--note` | 可选 | 抽卡次数、失败现象、平台限制等 |
| `--provider` | 可选 | 默认 `handoff`，一般不用改 |

导入成功后，终端会打印新的 `job_id`，然后：

```bash
python studio.py audit --id <job_id>
python studio.py contact-sheet --job <job_id>
```

- `audit` 会跑同一套 13 项检查。全部通过时退出码为 0。
- `contact-sheet` 会从视频均匀抽 9 帧拼成 3×3 九宫格，用来快速看运镜、服装和伤情。
- 也可以打开看板 `python studio.py serve`，在任务抽屉里查看“外部导入”区块、媒体预览、九宫格和审计环。

---

## 6. 怎么读审计结果

审计分两层：

- **证据链**：文件哈希、参考图、提示词、修订锁、快照重放、同修订重编译；
- **任务本身**：成功、失败、演练、阻断。

外部导入的典型结果：

| 结果 | 含义 | 下一步 |
| --- | --- | --- |
| 13/13 通过 | 文件没被改，且仍绑在当前修订/提示词上 | 进入人工审片 |
| 修订不一致 | 你用了旧包，或上下文已经变了 | 重新 `build` + `handoff`，不要混用 |
| 提示词哈希不一致 | 生成时用的不是当前编译结果 | 检查是不是拿错包 |
| 产物哈希失败 | 导入后的文件被改动过 | 重新导入原始文件 |
| 时长/分辨率警告 | 外部平台的实际输出与目标不同 | 记录事实；是否接受由作者决定 |
| 综合警告 | 证据链通过，但任务是历史修订或非成功状态 | 看具体检查项，不要只看总分 |

**通过审计不等于画面合格。** 审计只回答“这份记录还是不是当初那一份”，不回答“这个镜头能不能用”。

---

## 7. 常见报错

### “上下文已变化：当前修订 …，包内修订 …”

你在 `build` 之后又改了角色卡、参考图、时间线或厂商配置，但 handoff 包还是旧的。

```bash
python studio.py build
python studio.py handoff --shot E01-004
```

不要试图把旧包的结果挂到新修订上，CineLock 会拒绝。

### “修订号至少给出 8 位，避免误匹配”

`--revision` 太短。用 `manifest.short_revision`（12 位）或完整 `context_revision`。

### “只支持 .mp4 / .mov / .webm”

平台下载的是 `.gif`、`.webp`、`.zip` 或没有扩展名。先用 ffmpeg 转成 mp4：

```bash
ffmpeg -i input.webm -c:v libx264 -pix_fmt yuv420p output.mp4
```

### “ffprobe 无法解析该文件”

文件损坏、只有音频流，或下载没完成。重新下载；必要时用 ffmpeg 重新封装。

### 导入成功，但审计里 `outputs` 失败

导入后文件被改过（剪辑、转码覆盖、手动替换）。重新导入原始文件，或接受这是一次新的产物——不要手改任务 JSON 里的哈希。

---

## 8. 安全、授权与边界

- 交接包不包含 Cookie、API Key 或账号登录态；
- 不要把别人的登录态、会员账号或配额凭据发到仓库 / Issue；
- 不要绕过平台配额、风控或账号共享限制；
- 回传的视频和参考图必须是你有权使用的素材；
- 示例项目的参考图是原创几何占位资产，替换为正式素材时请自行确认版权与肖像授权；
- CineLock 只做上下文治理与证据链审计，不对生成内容的合法性、真实性或画面质量作保证。

---

## 9. 作者侧一页清单

```text
[ ] python studio.py build
[ ] python studio.py handoff --shot <SHOT>
[ ] 把 exports/handoff/<job_id>/ 整个目录发给朋友
[ ] 朋友按 refs 顺序上传 + 粘贴 prompt.txt + 生成
[ ] 收回视频（mp4/mov/webm）
[ ] python studio.py import --shot <SHOT> --video <FILE> --model <MODEL> \
      --revision <short_revision> --prompt-hash <prompt_sha256> --note "<备注>"
[ ] python studio.py audit --id <JOB_ID>
[ ] python studio.py contact-sheet --job <JOB_ID>
[ ] 人工审片：脸、球衣号码、伤情、道具、场景光线
[ ] 记录失败样本；不要手改任务 JSON 的哈希
```

如果你愿意赞助一次模型调用，请到 [Issue #11 · 求大佬赞助算力](https://github.com/bbo777/cinelock/issues/11) 认领镜头。你出算力，CineLock 出上下文和审计。

# 发布文案包

长文正文：

- 中文：[`hash-lock-and-state-machine.md`](hash-lock-and-state-machine.md)
- 英文：[`hash-lock-and-state-machine.en.md`](hash-lock-and-state-machine.en.md)
- 仓库：https://github.com/bbo777/cinelock

> 截至 2026-10-31，掘金、V2EX、X、Hacker News 在当前浏览器中均未登录。以下文案已按平台限制准备好，登录后可直接粘贴发布。
>
> 演示状态：因算力受限，停留在关键帧与上下文编译阶段；仓库附带 mock 占位视频。Handoff 是算力众包入口，认领见 Issue #11。所有文案不得写成“正在生成中”或“即将成片”。

---

## 掘金

**标题**

我是如何用哈希锁和状态机，解决 AI 视频跨模型一致性灾难的

**摘要**

1 个原创角色、2 个场景、5 个镜头、5 个厂商、25 个变体共享同一份上下文修订。本文拆解哈希锁、连续性状态机、确定性编译、13 项分层审计、MCP Server 接入，以及 ffprobe 与九宫格如何把“看起来对”变成可检查的产物。演示项目因算力受限，停留在关键帧与上下文编译阶段，当前只有 mock 占位视频；Handoff 与 Issue #11 把生成环节开放给社区。

**分类**

人工智能

**标签**

MCP、AI 视频、AIGC、Python、开源

**正文**

直接使用 [`hash-lock-and-state-machine.md`](hash-lock-and-state-machine.md) 全文。发布前把文末仓库链接保留为：

```text
https://github.com/bbo777/cinelock
```

---

## V2EX

**节点**

分享创造

**标题**

做了个多模型 AI 视频连续性编排层：MCP Server + 哈希锁 + 状态机

**正文**

最近在做一个多模型 AI 视频的编排层，起因很实际：同一场戏用好几个模型生成，角色服装、伤情、道具、光线全在漂，最后根本说不清哪一版用了哪张参考图。

我的思路不是继续调提示词，而是把“一致性”变成可验证的约束：

1. 哈希锁：context_revision 由角色卡、时间线、模型矩阵、参考图真实字节和编译器指纹共同计算；任务执行前校验，过期上下文直接拒绝。
2. 状态机：角色卡只定义初始状态，每个镜头用 state_delta 描述伤情/道具/服装变化，按时间线重放，编译器消费的是每镜头快照而不是角色卡原文。
3. 确定性编译：固定拼接顺序、参考图优先级、截断规则和种子；同一修订重编译必须得到同一提示词哈希。
4. 分层审计：13 项检查只回答“证据链是否自洽”；job_status / dry_run 单独报告；综合结论再看上下文是否过期。模型失败不等于证据链失败。
5. 产物校验：ffprobe 检查时长/分辨率/编码，ffmpeg 生成 3×3 九宫格做人工快速对比。
6. MCP 接入：内置零依赖 MCP stdio Server，Claude Desktop / WorkBuddy 加 9 行 JSON 就能查修订、取编译结果、跑审计、导出交接包，不用重新实现任何语义。
7. 平台无关：统一 AdapterRequest / AdapterOutcome 协议，内置 mock / handoff / comfyui / 通用 http_api 四种适配器；纯 Python，不依赖 Node，也不绑定某一家 CLI。

演示项目是 1 个原创角色、2 个场景、5 镜头 × 5 厂商 = 25 个变体，共享一个修订，76 个测试，最近一次 mock 任务 13/13 通过。默认先跑 mock/handoff，不消耗真实算力。

说点实话：我只有一台没有独显的 ASUS VivoBook，也买不起几百上千元的生成额度。所以引擎、哈希锁、状态机、审计闭环都做完了，5 个镜头却没有真实生成，仓库里是 mock 占位视频。这不是“正在生成中”，是“卡在算力这一步”。

于是我把 Handoff 做成了算力众包：我把每个镜头的参考图、提示词、时间线和连续状态打包，你用自己的模型额度生成，再用 `studio.py import` 把结果绑回当前修订和提示词哈希，跑同一套 13 项审计。认领入口在 Issue #11。

代码和完整演示：https://github.com/bbo777/cinelock

想听听大家在实际多模型工作流里遇到的穿帮案例，尤其是“用了同一张参考图还是不像”的那种。

---

## X

**Thread（英文，逐条发布）**

1/

One original character. Two scenes. Five shots. Five AI video providers. Twenty-five variants. One context revision: 9b1c685fec55.

The hard part isn't generating clips. It's proving every model saw the same character, the same state, and the same instructions. 🧵

2/

The fix isn't a better prompt. It's a hash lock:

- SHA-256 over character cards, timeline, provider matrix, actual reference-image bytes, compiler fingerprint
- every job records the revision
- stale context is rejected before generation

3/

Continuity is a state machine:

- character cards define the initial state
- each shot applies a state_delta (injuries, props, wardrobe)
- the compiler consumes a per-shot snapshot, not the raw card

No model gets to infer a different costume.

4/

Audit is layered:

13 checks verify evidence (hashes, snapshots, prompts, refs, recompile)
job_status/dry_run are reported separately
A failed provider is not an evidence failure. A stale context is not a pass.

5/

CineLock also ships a zero-dependency MCP stdio server. Claude Desktop or WorkBuddy can query the revision, fetch a compiled variant, run the 13-check audit, export a handoff pack, or submit a ComfyUI workflow — no separate API, no reimplementation.

9 lines of JSON.

6/

ffprobe validates downloads. ffmpeg builds a 3×3 contact sheet for human review.

CineLock ships four adapters: mock, handoff, ComfyUI HTTP, and a generic official-API adapter with Kling/Runway presets.

Result: 76 tests, 25 variants, 13/13 checks pass on the demo. Mock/handoff runs cost zero compute.

But the five shots are not generated yet. I only have a thin laptop with no GPU and no budget for video credits. The repo ships mock placeholders. The missing step is compute, not context.

Code: https://github.com/bbo777/cinelock

7/

So Handoff becomes compute crowdsourcing:

- I package refs, prompts, timeline, continuity state
- you generate with your own model credits
- `studio.py import` binds the file to the current revision + prompt hash
- the same 13 checks run on it

Claim a shot: https://github.com/bbo777/cinelock/issues/11

---

## Hacker News

**Type**

Show HN

**Title**

Show HN: CineLock – MCP server for hash-locked AI video continuity

**URL**

https://github.com/bbo777/cinelock

**First comment（作者自述）**

I built this after watching the same 5-shot sequence drift across multiple providers. Prompt engineering didn't help, because each model only sees the context you hand it at generation time.

CineLock treats continuity as an engineering constraint:

- A context revision is a SHA-256 over character cards, timeline, provider matrix, actual reference-image bytes, and a compiler fingerprint. Stale revisions are rejected before execution.
- A state machine replays per-shot state deltas (wardrobe, injuries, props), and the compiler consumes the resulting snapshot instead of the raw character card.
- A 13-check audit separates evidence integrity from job outcome. A provider failure and a stale-context success are different failure modes.
- ffprobe validates downloaded media; ffmpeg produces a 3×3 contact sheet for human review.
- A zero-dependency MCP stdio server exposes status, variant compilation, audit, job listing, preview/full build, contact sheets, handoff export, and ComfyUI/HTTP generation to Claude Desktop or WorkBuddy.
- Four adapters share one protocol: mock, handoff, ComfyUI HTTP, and a generic official-API adapter with Kling/Runway presets. Pure Python; no Node or vendor CLI.
- `import` binds an externally generated file to the current revision and prompt hash, records its SHA-256 and ffprobe metadata, and runs the same 13-check audit.

The demo is 1 original character, 2 scenes, 5 shots × 5 providers = 25 variants with one revision. 76 tests pass. The mock/handoff path costs no compute, so you can exercise the full loop before connecting a real provider.

The five shots are not generated for real. I only have a thin laptop with no discrete GPU and no budget for generation credits, so the repository ships mock placeholders. The missing step is compute, not context. I package every shot as a verifiable handoff pack and invite people to generate one with their own credits, then bind it back through `import` and the audit. Claim a shot in Issue #11.

It does not make models deterministic or judge visual quality. It bounds the randomness and makes every output explainable. I'd especially welcome feedback on the audit model and on continuity data formats for real productions.

---

## 发布检查清单

- [ ] GitHub topics：`ai-video` / `llm` / `context-management` / `comfyui` / `mcp` / `claude-desktop` / `midjourney`（移除 quota-flow 相关标签）
- [x] GitHub 仓库改名 `nineflow` → `cinelock`；旧 URL 已验证返回 301 重定向到 `https://github.com/bbo777/cinelock`
- [x] 社区任务 Issues #1–#11：`https://github.com/bbo777/cinelock/issues`（#11 为算力赞助入口）
- [x] 公开看板 Nine Inning Bottom：`https://github.com/users/bbo777/projects/5`
- [ ] 掘金：登录 → 写文章 → 粘贴 Markdown → 选分类/标签 → 发布 → 记录链接
- [ ] V2EX：登录 → 分享创造 → 粘贴标题/正文 → 发布 → 记录链接
- [ ] X：登录 → 按 7 条 Thread 发布 → 记录首条链接
- [ ] Hacker News：登录 → submit → 填标题/URL → 发布后补第一条 comment → 记录链接
- [ ] 四篇发布后，把链接补回本条清单

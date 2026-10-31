# 发布文案包

长文正文：

- 中文：[`hash-lock-and-state-machine.md`](hash-lock-and-state-machine.md)
- 英文：[`hash-lock-and-state-machine.en.md`](hash-lock-and-state-machine.en.md)
- 仓库：https://github.com/bbo777/cinelock

> 截至 2026-10-31，掘金、V2EX、X、Hacker News 在当前浏览器中均未登录。以下文案已按平台限制准备好，登录后可直接粘贴发布。

---

## 掘金

**标题**

我是如何用哈希锁和状态机，解决 AI 视频跨模型一致性灾难的

**摘要**

1 个原创角色、2 个场景、5 个镜头、4 个模型、20 个变体共享同一份上下文修订。本文拆解哈希锁、连续性状态机、确定性编译、13 项分层审计、MCP Server 接入，以及 ffprobe 与九宫格如何把“看起来对”变成可检查的产物。演示项目仍在逐镜生成中，当前没有成片。

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

最近在做一个多模型 AI 视频的编排层，起因很实际：同一场戏用 4 个模型生成，角色服装、伤情、道具、光线全在漂，最后根本说不清哪一版用了哪张参考图。

我的思路不是继续调提示词，而是把“一致性”变成可验证的约束：

1. 哈希锁：context_revision 由角色卡、时间线、模型矩阵、参考图真实字节和编译器指纹共同计算；任务执行前校验，过期上下文直接拒绝。
2. 状态机：角色卡只定义初始状态，每个镜头用 state_delta 描述伤情/道具/服装变化，按时间线重放，编译器消费的是每镜头快照而不是角色卡原文。
3. 确定性编译：固定拼接顺序、参考图优先级、截断规则和种子；同一修订重编译必须得到同一提示词哈希。
4. 分层审计：13 项检查只回答“证据链是否自洽”；job_status / dry_run 单独报告；综合结论再看上下文是否过期。模型失败不等于证据链失败。
5. 产物校验：ffprobe 检查时长/分辨率/编码，ffmpeg 生成 3×3 九宫格做人工快速对比。
6. MCP 接入：内置零依赖 MCP stdio Server，Claude Desktop / WorkBuddy 加 9 行 JSON 就能查修订、取编译结果、跑审计，不用重新实现任何语义。

演示项目是 1 个原创角色、2 个场景、5 镜头 × 4 模型 = 20 个变体，共享一个修订，62 个测试，最近一次 mock 任务 13/13 通过。默认先跑 mock/handoff，不消耗真实配额。项目仍是 WIP：底层引擎和审计闭环已经完成，5 个镜头正在逐镜生成，当前没有成片。

代码和完整演示：https://github.com/bbo777/cinelock

想听听大家在实际多模型工作流里遇到的穿帮案例，尤其是“用了同一张参考图还是不像”的那种。

---

## X

**Thread（英文，逐条发布）**

1/

One original character. Two scenes. Five shots. Four AI video providers. Twenty variants. One context revision: 9bb2cfb6449f.

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

CineLock also ships a zero-dependency MCP stdio server. Claude Desktop or WorkBuddy can query the revision, fetch a compiled variant, run the 13-check audit, or build a preview — no separate API, no reimplementation.

9 lines of JSON.

6/

ffprobe validates downloads. ffmpeg builds a 3×3 contact sheet for human review.

Result: 62 tests, 20 variants, 13/13 checks pass on the demo. Mock/handoff runs cost zero quota.

This is still WIP: the continuity engine and audit loop are done; the five shots are being generated now. No finished film yet — and the README says so.

Code: https://github.com/bbo777/cinelock

---

## Hacker News

**Type**

Show HN

**Title**

Show HN: CineLock – MCP server for hash-locked AI video continuity

**URL**

https://github.com/bbo777/cinelock

**First comment（作者自述）**

I built this after watching the same 5-shot sequence drift across four providers. Prompt engineering didn't help, because each model only sees the context you hand it at generation time.

CineLock treats continuity as an engineering constraint:

- A context revision is a SHA-256 over character cards, timeline, provider matrix, actual reference-image bytes, and a compiler fingerprint. Stale revisions are rejected before execution.
- A state machine replays per-shot state deltas (wardrobe, injuries, props), and the compiler consumes the resulting snapshot instead of the raw character card.
- A 13-check audit separates evidence integrity from job outcome. A provider failure and a stale-context success are different failure modes.
- ffprobe validates downloaded media; ffmpeg produces a 3×3 contact sheet for human review.
- A zero-dependency MCP stdio server exposes status, variant compilation, audit, job listing, preview/full build, and contact sheets to Claude Desktop or WorkBuddy.

The demo is 1 original character, 2 scenes, 5 shots × 4 providers = 20 variants with one revision. 62 tests pass. The mock/handoff path costs no quota, so you can exercise the full loop before connecting a real provider. It is explicitly WIP: the engine, hash lock, state machine, and audit loop are complete; the five shots are still being generated, and there is no finished film.

It does not make models deterministic or judge visual quality. It bounds the randomness and makes every output explainable. I'd especially welcome feedback on the audit model and on continuity data formats for real productions.

---

## 发布检查清单

- [x] GitHub topics：`mcp` / `mcp-server` / `ai-video` / `aigc` / `continuity` / `claude-desktop` / `workbuddy` / `python`
- [ ] GitHub 仓库改名 `nineflow` → `cinelock` 并验证旧 URL 重定向（HTTPS 通道当前被重置，待网络恢复）
- [ ] 掘金：登录 → 写文章 → 粘贴 Markdown → 选分类/标签 → 发布 → 记录链接
- [ ] V2EX：登录 → 分享创造 → 粘贴标题/正文 → 发布 → 记录链接
- [ ] X：登录 → 按 6 条 Thread 发布 → 记录首条链接
- [ ] Hacker News：登录 → submit → 填标题/URL → 发布后补第一条 comment → 记录链接
- [ ] 四篇发布后，把链接补回本条清单

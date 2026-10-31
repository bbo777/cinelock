# 社区任务清单 · Nine Inning Bottom

这是《九局下半》演示关卡的**唯一任务源清单**。GitHub Issues / Project 看板按本文同步；即使看板暂时没建好，你也可以直接按这里的任务说明开 Issue 或提交 PR。

> 当前事实（2026-10-31）：**1 个原创角色、2 个场景、5 个镜头、4 个启用厂商、20 个变体、56 次参考图引用**，共享修订 `9bb2cfb6449f`；**62 项测试通过**；**成片 0 个**。

看板列建议：

| 待认领 | 生成中 | 待人工审片 | 已完成 |
| --- | --- | --- | --- |
| 任务已拆好，等执行者 | 已领取，正在生成/开发 | 产物和记录齐了，等审片 | 验收标准全部满足 |

标签建议：`shot`、`assets`、`qc`、`provider`、`proposal`、`good first issue`。

---

## 领取方式

1. 在 Issue 里写一句“我领取这个任务”，附上你准备使用的厂商/模型。
2. 生成类任务不必把大视频提交进仓库：把文件放到你可公开访问的位置，在 Issue 里贴链接和下面的元数据。
3. 配置、时间线、参考图、文档类改动走 PR；一次 PR 只做一件事。
4. 提交前必须确认：**不含 Cookie / API Key / 登录态；素材有合法授权；mock 产物不能标成真实成片。**

生成类任务的回报格式：

```text
任务：E01-004
厂商 / 模型版本：
生成日期：
上下文修订：9bb2cfb6449f...
提示词哈希：774c474761d3...
Seed（如支持）：
实际时长 / 分辨率 / 编码：
产物链接：
人工观察：脸、7 号球衣、左脸淤青、下唇破口、右袖撕裂、球棒
失败样本（可选）：
```

---

## A. 已编译、可直接执行：E01-001 ~ E01-005

5 个镜头的正向/负向提示词已经按 4 个厂商编译好，位于：

```text
examples/nine-inning-bottom/context/shots/E01-00X/
  handoff.prompt.txt     手工交接（任意支持多参考图的模型）
  qwenwan.prompt.txt     千问万相（单图首帧）
  yuanbao.prompt.txt     元宝（单图首帧）
  mock.prompt.txt        占位链路，仅用于测试
```

参考图在 `examples/nine-inning-bottom/refs/`，上传顺序以对应 `handoff.json` 的 `references` 为准。**第 1 张永远是身份锚点，不要改顺序。**

### A1. 生成 E01-001（建立镜头）

- 镜头：中景、缓推、5 秒；状态 `home_clean`
- 重点：先让观众记住脸、7 号球衣、球棒；这是全片唯一一次“干净”状态
- 已编译：[handoff.prompt.txt](../examples/nine-inning-bottom/context/shots/E01-001/handoff.prompt.txt)
- 验收：脸与 7 号没有漂移；球棒在双手；光线是黄昏而不是夜景

### A2. 生成 E01-002（泥污起点）

- 镜头：近景、手持、6 秒；状态 `home_dirty`
- 重点：泥污从这里开始，**后续任何镜头都不能重置为干净球衣**
- 已编译：[handoff.prompt.txt](../examples/nine-inning-bottom/context/shots/E01-002/handoff.prompt.txt)
- 验收：泥污可见且集中在球衣/面部；球棒仍持有；台词不要求口型精确

### A3. 生成 E01-003（空间转换）

- 镜头：全景、跟拍、7 秒；状态 `home_dirty`
- 重点：从休息区走到打击区，泥污与球棒必须连续，光线保持同一黄昏
- 已编译：[handoff.prompt.txt](../examples/nine-inning-bottom/context/shots/E01-003/handoff.prompt.txt)
- 验收：场景切换但时间不跳；球衣泥污没有被“洗干净”；球棒没有换手/消失

### A4. 生成 E01-004（高风险特写）

- 镜头：特写、固定、5 秒；状态 `home_injured`
- 重点：**伤情从这里开始**——左脸淤青、下唇破口、右袖撕裂；下一镜必须延续
- 已编译：[handoff.prompt.txt](../examples/nine-inning-bottom/context/shots/E01-004/handoff.prompt.txt)
- 真实交接包（含 5 张参考图、prompt、negative、manifest）：
  [`docs/showcase/handoff-E01-004/`](showcase/handoff-E01-004/)
  - 任务：`JOB_20261031T134503Z_E01-004_handoff_adb8f9`
  - 提示词哈希：`774c474761d35f63f298e7d52889e321352f9bd85b51df789d13020097e659b5`
  - 该包审计 13/13
- 验收：脸部特写不崩；三处伤情方向正确（左脸、下唇、右袖）；球棒仍在手中；没有额外伤口

### A5. 生成 E01-005（收尾大远景）

- 镜头：大远景、升镜、8 秒；状态 `home_injured`
- 重点：伤情、撕裂袖口、球棒全部延续；不做无解释重置
- 已编译：[handoff.prompt.txt](../examples/nine-inning-bottom/context/shots/E01-005/handoff.prompt.txt)
- 验收：远景里仍能辨认 7 号与球棒；伤情/撕袖不被“修复”；黄昏光一致

### 生成后的统一验收

1. 下载文件用 ffprobe 检查容器、视频流、时长、分辨率（目标 1920×1080，时长允许厂商就近）。
2. 生成 3×3 九宫格做人工对比：
   ```bash
   python studio.py contact-sheet --job <JOB_ID>
   ```
3. 跑审计：`python studio.py audit --job <JOB_ID>`，证据链应为 13/13。
4. 在 Issue 里贴产物链接、元数据和人工观察；**不要只写“效果不错”**。

> 提醒：审计只证明任务记录、参考图与产物仍一致，不证明像素级连续性；最终仍需人眼判断。

---

## B. 提案任务：镜06 / 镜07（尚未存在）

**重要：当前 `timeline.json` 只有 E01-001 ~ E01-005。镜06「顿棍立威」和镜07「特训蒙太奇」不是已编译内容，仓库里没有它们的 prompt 或 handoff 包。** 下面两项是扩展提案，必须先设计时间线与 `state_delta`，再 `build`，才会产生可执行的提示词。

### B1. 提案：生成镜06（顿棍立威）

- 叙事位置：待定。可以是 E01-005 之后的一个短促收束，也可以插在 E01-003 与 E01-004 之间制造压迫感。
- 建议镜头：低角度特写或中近景，3–5 秒，固定或轻微手持；动作是双手调整握把、球棒顿地/顿棍，尘土扬起。
- 连续性要求：
  - 若放在 E01-004 之后，必须继承 `home_injured`，左脸淤青、下唇破口、右袖撕裂一个都不能少；
  - 若放在 E01-003 与 E01-004 之间，只能是 `home_dirty`，**不能提前出现伤情**；
  - 球棒不能离手，握把位置要可解释。
- 需要提交：`timeline.json` 的 shot 草案（含 `scene_id`、`duration_sec`、`action_en/zh`、`state_delta`、`risk_level`）、叙事理由、预期验收点。
- 完成定义：`validate` 通过 → `build` 生成新修订 → handoff prompt 可读 → 至少一个真实产物 + 审计 13/13。

### B2. 提案：生成镜07（特训蒙太奇）

- 叙事位置：待定。**蒙太奇会打断线性状态链**，因此必须先决定它是：
  1. 独立序列（单独 timeline / episode，拥有自己的状态链），还是
  2. 明确的回忆/闪回，并在镜头数据中标注“非当前连续性”，而不是让状态机静默回退。
- 建议内容：多段短镜头（挥棒、跑动、手套接球、汗水），同一角色不同光照；总长 6–10 秒。
- 连续性要求：若为独立序列，不得复用 E01 的 `from_shot` 链；若为闪回，必须显式标注时间层，避免把“训练时无伤”误判为穿帮。
- 需要提交：时间线结构提案（单镜头还是多镜头？是否需要 `sequence_id`/时间层字段？）、状态处理方案、对现有编译器的改动范围。
- 完成定义：结构方案被接受 → 实现并补测试 → 新修订可编译 → 至少一个真实产物 + 审计。**在方案落地前，不接受“先贴一段 prompt 再说”。**

> 这两项不是“复制粘贴就能生成”的任务，而是邀请你参与设计。请先开 Issue 讨论，不要直接改 `timeline.json` 提 PR。

---

## C. 替换占位参考图为授权资产

当前 8 张参考图（6 张角色状态 + 2 张场景板）全部是仓库内生成的原创几何占位资产，不含第三方 IP。它们能证明状态链，但无法证明“真实角色一致性”。

- 目标：用你有明确授权的角色/场景图替换 `examples/nine-inning-bottom/refs/` 中的占位图。
- 步骤：
  1. 更新 `reference_bank.json` 的 `asset_id`、`path`、`status`；
  2. 运行 `python studio.py refresh-hashes` 修复记录哈希（有缺失文件会拒绝写入）；
  3. 运行 `python studio.py validate && python studio.py build`；
  4. 确认 `context_revision` 变化，并重新导出 handoff；
  5. 跑测试。
- 验收：素材授权可说明；8 张图都存在；修订已变化；审计通过；**不引入任何第三方 IP 素材或未授权肖像**。
- 注意：换图会改变修订，旧 handoff 包立即过期，不能混用。

---

## D. 输出侧连续性核验（从 0 到 1）

CineLock 目前只做输入侧治理与证据链审计。我们明确**没有**自动人脸评分、服装/伤情/道具视觉核验。这是下一个最有价值的缺口。

- 目标：对产出的视频抽帧，检查人脸身份、7 号球衣、泥污、左脸淤青、下唇破口、右袖撕裂、球棒是否存在且连续。
- 设计约束：
  - 结果必须与 13 项证据链审计**分层**，建议新增 `visual_qc` 状态（pass/warn/fail/skip），不能污染 `artifact_status`；
  - 允许“无法判断”（skip），不要为了通过而猜；
  - 默认离线、本地运行，不把帧上传到第三方服务；
  - 不引入重型依赖作为默认安装要求。
- 验收：对已知好/坏样本能给出可解释结论；与九宫格人工审片结果对照；补测试；文档写清“它仍然不是最终审片”。

---

## E. Quota-Flow 真机出片记录

当前演示只跑过 mock 与 handoff，**没有真实厂商出片**。已安装的 Quota-Flow CLI 0.1.0 只注册 `qwenwan` / `yuanbao`，两家都只有单图首帧。

- 目标：在合规前提下，用真实登录态跑至少一个镜头，记录：
  - CLI 版本、厂商、模型、生成时间；
  - 是否返回 dry-run（dry-run 不是成功视频，也会可能扣减本地额度）；
  - 实际时长/分辨率与请求值的差异；
  - 配额账本变化；
  - 产物审计结果。
- 禁止：绕过配额、共享账号、伪造登录态、规避风控。
- 验收：任务记录完整；dry-run 被正确标注；不以 mock 冒充真实产物；失败样本也回传。

---

## F. 新增厂商 / MCP 客户端

- 新厂商：在 `config/providers.json` 增加能力矩阵（参考图上限、模式、时长、seed），实现适配器，补“静默回退拒绝”测试。
- 新 MCP 客户端：用 `cinelock_status` / `cinelock_variant` / `cinelock_audit` / `cinelock_build` 做一次只读冒烟，记录客户端版本与工具返回。
- 验收：不破坏现有 62 项测试；新能力有文档；不泄露本地路径之外的敏感信息。

---

## 可直接粘贴的 Issue 草稿

```text
标题：[shot] 生成 E01-001（建立镜头）
标签：shot, good first issue
正文：
领取 E01-001。使用厂商/模型：____。
编译提示词：examples/nine-inning-bottom/context/shots/E01-001/handoff.prompt.txt
参考图顺序以 handoff.json 为准，第 1 张为身份锚点。
完成后回传：产物链接、实际时长/分辨率/编码、seed、人工观察（脸/7 号/球棒/黄昏光）。
不会提交 Cookie、API Key 或登录态。
```

```text
标题：[shot] 生成 E01-004（高风险特写）
标签：shot
正文：
领取 E01-004。现成交接包：docs/showcase/handoff-E01-004/
上下文修订：9bb2cfb6449f...；提示词哈希：774c474761d3...
重点验收：左脸淤青、下唇破口、右袖撕裂、球棒仍在手，且不新增伤口。
完成后附 ffprobe 结果、九宫格链接、audit 13/13 截图/输出。
```

```text
标题：[proposal] 扩展镜06（顿棍立威）
标签：proposal
正文：
当前 timeline 只有 E01-001~005，镜06 尚不存在，请先讨论叙事位置与 state_delta。
我建议放在：____（E01-003 与 004 之间 / E01-005 之后）。
该位置应继承状态：home_dirty / home_injured。
镜头草案：____。
不直接修改 timeline.json；方案确认后再提 PR。
```

```text
标题：[proposal] 扩展镜07（特训蒙太奇）
标签：proposal
正文：
蒙太奇会打断线性状态链。请先决定：独立序列 / 显式闪回（时间层）/ 其他。
当前引擎没有 sequence_id 或时间层字段；如需要，请说明最小改动方案与测试计划。
在方案落地前不提供“可直接生成”的 prompt。
```

```text
标题：[assets] 用授权资产替换占位参考图
标签：assets
正文：
我拥有以下素材的明确授权：____（角色图 / 场景板）。
计划替换 refs/ 中的：____。
会更新 reference_bank.json，运行 refresh-hashes、validate、build，并重新导出 handoff。
替换后修订会变化，旧包作废。
```

---

## 完成定义（Definition of Done）

**镜头任务**

- [ ] 产物存在，ffprobe 元数据已记录
- [ ] 参考图按顺序使用，身份锚点未省略
- [ ] 九宫格已生成并人工检查
- [ ] `audit` 证据链 13/13
- [ ] 前后镜头状态连续（泥污、伤情、撕袖、球棒）
- [ ] 没有把 mock / 占位产物标成真实成片

**代码 / 资产任务**

- [ ] `validate` 与 `build` 通过
- [ ] 62 项测试仍全绿（新增行为有测试）
- [ ] 保持 Python 3.8 兼容，默认不引入重型依赖
- [ ] 文档明确写出能力边界，不夸大
- [ ] 不包含凭据、登录态或未授权素材

---

## 相关入口

- 演示配置：[`examples/nine-inning-bottom/`](../examples/nine-inning-bottom/)
- E01-004 真实交接包：[`docs/showcase/handoff-E01-004/`](showcase/handoff-E01-004/)
- 技术长文：[`docs/hash-lock-and-state-machine.md`](hash-lock-and-state-machine.md)
- 主 README：[`README.md`](../README.md)

如果你只是想先跑通链路，不需要配额：先执行 `python studio.py run --provider mock --shot E01-004`，再跑 `audit` 和 `contact-sheet`。

# 九局下半 — Context Pack

> 占位骨架 · 待正式设定替换

- 项目：`nine-inning-bottom`
- 集：`E01` — 九局下半 · 占位样片
- 上下文版本：`9bb2cfb6449f5d9fdfd375fb5eb7e7908cd39b2b643a5768c6636a0af77c9008`
- 短版本：`9bb2cfb6449f`
- 生成时间：2026-10-31T13:39:38Z
- 规模：5 个镜头 / 4 个厂商 / 20 个变体
- 校验：0 错误，11 警告

## 唯一输入原则

所有厂商共用同一个 `context_revision`。角色卡、参考图库、时间线状态快照都在本包中固化；修改角色、参考图、时间线或厂商矩阵都会生成新的版本，旧版本产物不会自动混用。

模式：`text2video` 文生视频，`img2video` 单图首帧，`multi_ref` 多参考，`first_last` 首尾帧。

## 厂商能力

| 厂商 | 名称 | 类型 | 支持模式 | 参考上限 | 支持时长 | 负向词 |
| --- | --- | --- | --- | --- | --- | --- |
| `mock` | Mock（本地演练） | mock | text2video / img2video / multi_ref / first_last | 10 | 3 / 4 / 5 / 6 / 8 / 10 | 是 |
| `qwenwan` | 千问·通义万相 | quota_flow_webview | text2video / img2video | 1 | 5 | 否 |
| `yuanbao` | 腾讯元宝·混元 | quota_flow_webview | text2video / img2video | 1 | 5 | 否 |
| `handoff` | 手工交接包（任意模型） | handoff | text2video / img2video / multi_ref / first_last | 10 | 3 / 4 / 5 / 6 / 8 / 10 | 是 |

## 参考图库

| asset_id | 类型 | 归属 | 状态 | 文件 | sha256 |
| --- | --- | --- | --- | --- | --- |
| `REF_LINYE_FRONT_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_front_v01.png` | `e31a9a93e9f6` |
| `REF_LINYE_3Q_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_3q_v01.png` | `0c1b256d4583` |
| `REF_LINYE_EXPR_DETERMINED_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_expr_determined_v01.png` | `93d84cc5fbc4` |
| `REF_LINYE_EXPR_PAIN_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_expr_pain_v01.png` | `c4e42e97d9a8` |
| `REF_LINYE_DIRTY_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_dirty_v01.png` | `e8c68b6e43b2` |
| `REF_LINYE_INJURED_V01` | character | CH_LINYE_01 | draft | `refs/characters/linye/linye_injured_v01.png` | `b9ec09d0ad8b` |
| `REF_SC01_DUGUET_DUSK_V01` | scene | SC01_DUGUET_DUSK | draft | `refs/scenes/sc01_dugout_dusk_v01.png` | `bbf33ac64d24` |
| `REF_SC02_BATTERBOX_DUSK_V01` | scene | SC02_BATTERBOX_DUSK | draft | `refs/scenes/sc02_batterbox_dusk_v01.png` | `a1a8c9c2cc7d` |

## 连续性时间线

| 镜头 | 场景 | 角色状态 | 状态变化 | 连续性备注 |
| --- | --- | --- | --- | --- |
| `E01-001` | `SC01_DUGUET_DUSK` | Lin Ye：home_clean · 伤：无 · 道具：wooden baseball bat · 表情：neutral | Lin Ye：state carried | 开场：干净主场球衣、球棒、黄昏光。 |
| `E01-002` | `SC01_DUGUET_DUSK` | Lin Ye：home_dirty · 伤：无 · 道具：wooden baseball bat · 表情：determined | Lin Ye：wardrobe home_clean -> home_dirty | 球衣从干净变为泥污；球棒继续持有。 |
| `E01-003` | `SC02_BATTERBOX_DUSK` | Lin Ye：home_dirty · 伤：无 · 道具：wooden baseball bat · 表情：determined | Lin Ye：state carried | 泥污延续；场景从休息区切到打击区，光线保持同一黄昏。 |
| `E01-004` | `SC02_BATTERBOX_DUSK` | Lin Ye：home_injured · 伤：bruise on left cheek、small cut on lower lip · 道具：wooden baseball bat · 表情：pain | Lin Ye：wardrobe home_dirty -> home_injured；injury + bruise on left cheek；injury + small cut on lower lip | 新增伤情：左脸淤青、下唇破口；右袖撕裂；球棒仍在手中。 |
| `E01-005` | `SC02_BATTERBOX_DUSK` | Lin Ye：home_injured · 伤：bruise on left cheek、small cut on lower lip · 道具：wooden baseball bat · 表情：determined | Lin Ye：state carried | 伤情、撕裂球衣、球棒全部延续；黄昏光保持一致。 |

## 编译结果

| 镜头 | 厂商 | 模式 | 时长 | 参考 | 首参考 | 提示词 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `E01-001` | `mock` | `multi_ref` | 5s | 3 | `REF_LINYE_FRONT_V01` | `67d88807d64f` | 可执行 |
| `E01-001` | `qwenwan` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `4864bea67d91` | 待补公网 URL |
| `E01-001` | `yuanbao` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `beccb5d9bc22` | 待补公网 URL |
| `E01-001` | `handoff` | `multi_ref` | 5s | 3 | `REF_LINYE_FRONT_V01` | `67d88807d64f` | 可执行 |
| `E01-002` | `mock` | `multi_ref` | 6s | 5 | `REF_LINYE_FRONT_V01` | `4c5e3523d5a2` | 可执行 |
| `E01-002` | `qwenwan` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `4f6f46ba353e` | 待补公网 URL |
| `E01-002` | `yuanbao` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `fbd369f75514` | 待补公网 URL |
| `E01-002` | `handoff` | `multi_ref` | 6s | 5 | `REF_LINYE_FRONT_V01` | `4c5e3523d5a2` | 可执行 |
| `E01-003` | `mock` | `multi_ref` | 8s | 5 | `REF_LINYE_FRONT_V01` | `d384fb269328` | 可执行（有告警） |
| `E01-003` | `qwenwan` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `0f355a417053` | 待补公网 URL |
| `E01-003` | `yuanbao` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `e17ec57d25f7` | 待补公网 URL |
| `E01-003` | `handoff` | `multi_ref` | 8s | 5 | `REF_LINYE_FRONT_V01` | `d384fb269328` | 可执行（有告警） |
| `E01-004` | `mock` | `multi_ref` | 5s | 5 | `REF_LINYE_FRONT_V01` | `774c474761d3` | 可执行 |
| `E01-004` | `qwenwan` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `27ae678aa1ce` | 待补公网 URL |
| `E01-004` | `yuanbao` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `fd83569865db` | 待补公网 URL |
| `E01-004` | `handoff` | `multi_ref` | 5s | 5 | `REF_LINYE_FRONT_V01` | `774c474761d3` | 可执行 |
| `E01-005` | `mock` | `multi_ref` | 8s | 5 | `REF_LINYE_FRONT_V01` | `d4b4cf0b844d` | 可执行 |
| `E01-005` | `qwenwan` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `3e134a51c6a4` | 待补公网 URL |
| `E01-005` | `yuanbao` | `img2video` | 5s | 1 | `REF_LINYE_FRONT_V01` | `bf541cd3a155` | 待补公网 URL |
| `E01-005` | `handoff` | `multi_ref` | 8s | 5 | `REF_LINYE_FRONT_V01` | `d4b4cf0b844d` | 可执行 |

## 目录

```
context/
  context_pack.json          全部变体与共享修订的完整清单
  continuity.json            每个镜头的角色状态快照
  CONTEXT.md                 本说明
  shots/<shot_id>/<provider>.json          编译结果
  shots/<shot_id>/<provider>.prompt.txt    正向提示词
  shots/<shot_id>/<provider>.negative.txt  负向提示词（如有）
```

## 限制与边界

- 共享输入与参考图顺序能显著降低漂移，但不能在数学意义上保证同一张脸；高风险特写建议加首尾帧或人工 QC。
- 单图模式只能放一张身份锚点；多角色镜头中其余角色只能靠提示词描述。
- Quota-Flow 适配器要求参考图是公网 https URL；`public_url` 为空时真实生成会被拒绝，mock 与 handoff 不受影响。
- 参考图状态仍为 `draft` 时只适合演练；正式生产前应改为 `approved` 或 `locked`。
- 本包只负责共享上下文与执行参数，不包含厂商登录态、Cookie 或 API Key。

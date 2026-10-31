# 手工交接包 · E01-004

由 CineLock 生成。目标模型可以是任何支持多参考图/图生视频的平台。

## 参数

- 镜头：`E01-004`
- 厂商变体：`handoff`（Handoff（手工交接包））
- 模式：`multi_ref`（多参考图）
- 时长：5 秒
- 画幅：16:9，分辨率 1920x1080，24 fps
- Seed：613553109（若目标模型支持）
- 上下文版本：`9b1c685fec55813dcb96a4d8a729d833df77d5476ad7cdd029267f1cbf5b2e31`
- 提示词哈希：`774c474761d35f63f298e7d52889e321352f9bd85b51df789d13020097e659b5`
- 项目：`nine-inning-bottom`
- 任务：`JOB_20261031T151022Z_E01-004_handoff_fdc887`

## 使用步骤

1. 打开目标模型的视频生成界面。
2. 按顺序上传 `refs/` 下的参考图；第 1 张必须是身份锚点，不要改顺序。
3. 把 `prompt.txt` 粘贴到正向提示词框。
4. 如果有负向提示词框，粘贴 `negative.txt` 的内容。
5. 设置上面列出的时长、画幅和分辨率；模型不支持目标时长时选最接近的值。
6. 若模型支持首尾帧，按 manifest 中 `role` 为 `first_frame` / `last_frame` 的图使用；若只支持单图，只用第 1 张身份锚点。
7. 生成后不要用同一提示词重新随机抽卡时丢掉参考图；身份锚点必须每次都带上。

## 参考图

| 顺序 | 文件 | asset_id | 用途 |
| --- | --- | --- | --- |
| 1 | `refs/01_REF_LINYE_FRONT_V01.png` | `REF_LINYE_FRONT_V01` | 身份锚点：优先上传，保证脸、发型和球衣号码 |
| 2 | `refs/02_REF_LINYE_3Q_V01.png` | `REF_LINYE_3Q_V01` | 几何/侧面：约束脸型、发量与身体比例 |
| 3 | `refs/03_REF_LINYE_EXPR_PAIN_V01.png` | `REF_LINYE_EXPR_PAIN_V01` | 表情参考：锁定本镜情绪 |
| 4 | `refs/04_REF_LINYE_INJURED_V01.png` | `REF_LINYE_INJURED_V01` | 伤情状态：淤青、破口、撕裂球衣等必须延续 |
| 5 | `refs/05_REF_SC02_BATTERBOX_DUSK_V01.png` | `REF_SC02_BATTERBOX_DUSK_V01` | 场景参考：地点、光线和构图 |

## 说明

- 参考图顺序和多参考组合是角色一致性的主要来源，优先保证身份锚点。
- 本包不包含 Cookie、API Key 或账号登录态。
- 提示词与参考图来自同一个 Context Pack；换了角色/时间线后请重新导出，不要混用旧包。

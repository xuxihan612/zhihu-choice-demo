# 知乎选哪边：核心优化验收报告

验收日期：2026-11-25

场景：家用咖啡机，胶囊机 vs 半自动

正式公网地址：https://v08hlna9o1wc.aiworks.site/

官方项目页：https://www.zhihu.com/project/detail/270773
历史 Qoder 地址：https://zhihu-coffee-choice-snt45f0o3qc.qoder.zone/

## 结论

核心优化修订版 1.0.1 已通过知乎 AI Works 官方审核，项目页显示“可运行 V 1.0.1”。全新匿名浏览器会话无 Cookie 打开正式公网地址，HTML 与 `data.js` 均返回 200。桌面与移动端各完成 36 组条件组合验收，29 个来源抽屉、92 条主张的 AI 处理链路和 29 个知乎回链结构全部通过，核心功能失败数为 0；正式地址没有 Qoder 水印，移动端标题与推荐卡不再被遮挡。

内联 SVG favicon 和页面描述的小版本也已发布。最终公网浏览器验证确认：标题与描述正确、内联 favicon 生效、没有 favicon 网络请求，桌面与 390×844 移动端均无横向溢出。

## 本轮完成的产品优化

1. **决策链路更清楚。** 页面明确呈现“选择条件 → 推荐变化 → 核对主张与证据 → 回知乎原文”。推荐区显示当前条件组合和两侧规则分，每条规则说明命中的具体条件。
2. **AI 价值可视化。** 用真实来源和真实主张展示“知乎原文 → AI 离线抽取 → 程序校验 → 确定性重排”，并明确浏览器不实时调用模型。
3. **冲突证据成为产品功能。** 对当前条件下意见相反的来源，并排展示双方主张、使用条件、代价、原文证据和知乎链接；未说明的条件不推断。
4. **来源追溯完整。** 每个来源和主张均可查看原文上下文、正文指纹、抽取运行元数据和程序校验结果。
5. **计划书完成。** 已覆盖目标用户、知乎生态契合度、确定性规则理由、扩展方向和落地路径。

## 工程与数据验收

| 检查项 | 结果 |
|---|---:|
| 回归测试 | 34/34 通过 |
| 交付校验 | 21/21 通过，`all_passed=true` |
| 来源 / 主张 | 29 / 92 |
| Schema 有效主张 | 92/92 |
| 主证据逐字匹配 | 92/92 |
| 代价证据逐字匹配 | 24/24 |
| 非空条件词面支持 | 8/8 |
| 完整知乎回链 | 92/92 |
| AI 辅助开发集 | 50 个候选，228 条主张 |
| 诊断模型评估 | 32/50 个候选，缺失 18 个如实披露 |

交付校验脚本已兼容当前 `META/SOURCES/DEMO_STATS` 数据格式，同时保留旧 `PIPELINE_*` 格式支持。兼容过程只展开当前嵌套主张并关联已审核来源，不修改审核记录或结论。

## 首轮 Qoder 公网端到端验收（历史记录）

| 检查项 | 结果 |
|---|---:|
| 桌面条件组合（两种筛选 × 18 组合） | 36 |
| 移动条件组合（两种筛选 × 18 组合） | 36 |
| 桌面 / 移动真实冲突条件 | 各 4 个 |
| 来源抽屉 | 29/29 |
| 主张 AI 处理链路 | 92/92 |
| 来源 trace 跳转 | 29/29 |
| 知乎回链结构 | 29/29 |
| Runtime exception | 0 |
| Console error | 0 |
| Network loading failure | 0 |
| 横向溢出失败 | 0 |

真实冲突出现在以下条件，且桌面与移动一致：低频 / 不愿清洗 / 想自己折腾；高频 / 不愿清洗 / 不想折腾；高频 / 不愿清洗 / 想学习；高频 / 不愿清洗 / 想自己折腾。

公网 `data.js` 为 171,660 字节，SHA-256 与本地完全一致：

`233d20867f5adf16ad613399104d1014109c6eb513c23169cc93c0be4918a6cf`

## AI Works 1.0.1 正式匿名公网复验

复验时间：2026-11-25T09:22:01.594Z。使用全新 Playwright 匿名会话，验收前 `cookie-list` 返回无 Cookie；正式地址的 HTML 与 `data.js` 匿名请求均为 200。

| 检查项 | 结果 |
|---|---:|
| 桌面条件组合（两种筛选 × 18 组合） | 36/36 |
| 移动条件组合（两种筛选 × 18 组合） | 36/36 |
| 来源抽屉 | 29/29 |
| 主张 AI 处理链路 | 92/92 |
| 来源 trace 跳转 | 29/29 |
| 完整知乎回链结构 | 29/29 |
| 冲突条件差异回退文案 | 存在 |
| 移动吸顶来源抽屉 | 通过 |
| Runtime exception / Console error / Network failure | 0 / 0 / 0 |
| 桌面 / 移动横向溢出失败 | 0 / 0 |
| Qoder 水印 | 不存在 |

正式公网 `data.js` 为 171,660 字节，SHA-256 为 `233d20867f5adf16ad613399104d1014109c6eb513c23169cc93c0be4918a6cf`，与本地和作者预览一致。桌面及 390×844 移动端截图已复查：无平台水印、无标题遮挡、推荐与冲突区单列正常；移动抽屉保留吸顶答主、赞数和知乎原文入口，选中主张位于头部下方。

该结果来自当前本地网络，不等同于多地区 CDN 或弱网基准；本轮直接检查的是 Demo 回链结构，知乎站外页面的此前 29/29 直接可达复核仍保留。

## 首轮 Qoder 移动端与加载速度（历史记录）

以下为历史 Qoder 地址的独立 Chrome headless + CDP 测量。当前本地网络单次结果：

- 响应结束：104.3 ms
- First Paint / First Contentful Paint：140 / 140 ms
- DOMContentLoaded：235.7 ms
- Load：237.1 ms
- HTML 编码后正文：98,309 字节
- `data.js` 编码后 30,362 字节，解码后 171,660 字节

这些数字只说明当前网络下的单次表现，不能作为多地区 CDN 或弱网基准。移动端 390×844 下推荐卡和冲突区为单列，未发现横向溢出。

## 知乎外链复核

此前已直接打开全部 29 个知乎来源，而不只检查链接字符串：

- HTTP 200：29/29
- 导航错误：0
- 页面作者存在：29/29
- 主张证据检查：92 条
- 所有证据文本块均存在：29/29 来源

因此可以区分两项结论：公网 Demo 的回链结构完整；知乎站外页面也已直接验证可达。赞数只作为来源元数据，不参与质量评分。

## 发布与文件状态

本地最终 HTML SHA-256：

`d5a069c9d96acebd4f802d93c1aad231902b5c44a75d35ddf95133e04ae56532`

最终公网完整响应为 98,855 字节，SHA-256：

`8cacf1baa43f4d2231c2c236fead91f3dfd2cd70477c907e0c1187f860cb41bf`

本地 `prototype/index.html`、`deploy/index.html`、`dist/index.html` 字节一致，favicon/meta 版本已发布。公网完整响应哈希不同的原因是托管平台在本地应用标记之后自动追加了 Qoder 水印脚本，并非本地应用代码被改写。最终浏览器验证没有 favicon 请求，桌面与 390×844 移动端均无横向溢出。

移动端截图另发现平台固定水印遮挡第一张推荐卡标题。该问题来自托管层注入，不建议通过隐藏或伪造平台标记规避；如确需参赛版完全干净的移动端体验，应使用赛事官方支持的部署方案重新托管同一份静态产物。

## 2026-11-25 后续发布修订

首轮公网验收完成后，又完成以下修订：

1. **冲突证据与来源核对修复。** 对真实来源的条件披露进行核对后，发现部分相反倾向的来源条件互斥，原“完全同条件”筛选无法产生双方结果。新版优先展示同条件对立来源；不存在时，改为展示条件不同或未说明的真实分歧，并明确标注“不作为同条件证据”。来源抽屉新增遮罩与吸顶来源信息，滚动到选中主张时仍保留答主、赞数和知乎原文入口。后续几何验收发现吸顶标题的顶部内边距会占去部分滚动边距，已改为按“吸顶头部实际顶部偏移 + 高度 + 18px”计算，29 个来源的选中主张均完整位于吸顶头部下方。`prototype/index.html`、`deploy/index.html`、`dist/index.html` 已同步，三份本地 HTML SHA-256 均为 `277254e408860852e53028f9307e723e6104a7761c6c3ea27f624b76a1cb8fcf`，34/34 回归通过。
2. **正规赛事渠道部署。** 官方项目为 [知乎选哪边](https://www.zhihu.com/project/detail/270773)。版本 1.0.0 已通过审核并显示“可运行”；已登录浏览器中的 [AI Works 预览](https://v08hlna9o1wc.preview.aiworks.site/) 无 Qoder 水印。按官方技术指南 4.4，预览链接仅支持作者登录调试，审核通过后才会生成不带 preview 的正式公网链接。
3. **修订版上传与预览验收。** 官方编辑页现已提供“设置 → 编辑 → 下一步 → 重新上传 → 发布新版本”的明确入口。新版 ZIP 已通过该入口成功上传并独立部署，不再存在此前 step=1 表单无请求、无提示的问题。作者登录预览完成桌面与 390×844 移动端各 36 组条件组合、29 个来源抽屉、92 条主张 AI 处理链路、29 个知乎回链结构、冲突条件差异回退和吸顶抽屉验收；核心失败数为 0，Qoder 水印不存在，桌面与移动均无横向溢出。`data.js` 仍为 171,660 字节，SHA-256 与本地一致。
4. **审核通过与最终公网验收。** 修订版项目版本 1.0.1 已通过官方审核，项目页显示“可运行 V 1.0.1”，并生成不带 preview 的正式地址 [知乎选哪边](https://v08hlna9o1wc.aiworks.site/)。全新匿名浏览器会话无 Cookie 完成正式地址桌面与移动端各 36 组、29 个来源抽屉、92 条主张、29 个知乎回链结构、冲突条件差异回退和移动吸顶抽屉验收；Runtime、Console、Network 和横向溢出失败均为 0，Qoder 水印不存在。部署包 ZIP 共 7 个文件，SHA-256 为 `7524c5e580ee29a4bf7790352b082951a1d9e8a98d0ced52a81527e93d07d68d`；带事件桥的 release HTML SHA-256 为 `ed76bae5600646cd4da69454c428eb5c25d9ab987a679774927a2247cef8139a`。

官方预览仍只支持作者登录调试，匿名请求预览 HTML 与 `data.js` 返回 302 并跳转知乎 SSO；这是平台既定的预览访问边界。最终参赛版应使用上述不带 preview 的正式公网地址。旧 Qoder 地址继续匿名可访问，但其移动端固定水印遮挡仍存在，仅作为历史部署记录保留。本轮未隐藏、删除或伪造任何平台标记。

## 演示视频交付

- [演示视频 MP4](demo-video/知乎选哪边-演示视频.mp4)：58.92 秒，1440×900，25fps，1473 帧，12,120,127 字节，H.264 + AAC 48kHz 立体声，含中文烧录字幕、配音和片尾 BGM 署名。
- [ASS 字幕](demo-video/demo.ass)
- [SRT 字幕](demo-video/demo.srt)

录制与混音脚本保留在本地制作目录，不纳入公开代码仓库。

视频由真实浏览器操作录制，覆盖条件切换、推荐变化、AI 离线抽取与程序校验、冲突对照、来源抽屉和片尾。字幕时间来自 MiniMax 逐字时间戳；混音实测约 −15.72 LUFS、−3.74 dBTP。最终导出使用唯一的 `SYNC 1125` 同步画面定位起点：最后一帧同步画面在 6.04 秒，首个应用画面在 6.08 秒；先裁剪并重置视频时间戳，再烧录字幕，避免静态页面匹配和输入 seek 造成偏移。

已通过 `ffprobe`、响度测量、FFmpeg SRT 解析、ASS/SRT 标准时间格式校验和 14 个关键帧对照。28 秒显示 AI 处理链路，38 秒显示冲突对照，44–46 秒显示带答主、赞数、原文入口和选中主张的来源抽屉，55 秒显示片尾与收尾旁白。尚未完成完整人工听审。MP4 SHA-256：`3a0675914f8a6977a70ff83412e24a704f2f7542a89894b49c60f834538d4e6d`。

## 诚信边界

- 语义审核为两轮独立 AI 审核加 AI 裁决，不是真人双人复核。
- 50 条集合是 AI 辅助开发集，`human_double_review_completed=false`、`test_set_locked=false`、`quality_reporting_eligible=false`。
- 32 条模型评估仅用于诊断，不能作为模型质量声明。
- 规则分是确定性相对匹配分，不是概率、准确率、人工评分或购买保证。
- 同分时明确显示“得分并列，没有单一推荐”。
- AI 抽取为离线真实处理流程，浏览器不会伪装成实时模型调用。

## 证据文件

- [公网复验原始结果](demo-acceptance/browser/live-revalidation.json)
- [最终桌面截图](demo-acceptance/browser/final-desktop.png)
- [最终移动端截图](demo-acceptance/browser/final-mobile.png)
- [桌面与移动矩阵](demo-acceptance/browser/live-matrix.json)
- [知乎外链直接复核](demo-acceptance/browser/all-backlinks-recheck.json)
- [交付校验报告](pipeline/runs/approved-v1/delivery-verification.json)
- [机器可读验收摘要](demo-acceptance/core-optimization-summary.json)
- [AI Works 1.0.1 预览复验](demo-acceptance/browser/aiworks-v1-0-1-revalidation.json)
- [AI Works 桌面与移动矩阵](demo-acceptance/browser/aiworks-v1-0-1-matrix.json)
- [AI Works 匿名访问复核](demo-acceptance/browser/aiworks-access-check.json)
- [AI Works 1.0.1 正式匿名公网复验](demo-acceptance/browser/aiworks-final-anonymous-revalidation.json)
- [AI Works 正式公网桌面与移动矩阵](demo-acceptance/browser/aiworks-final-anonymous-matrix.json)
- [AI Works 正式公网桌面截图](demo-acceptance/browser/aiworks-final-anonymous-desktop.png)
- [AI Works 正式公网移动端截图](demo-acceptance/browser/aiworks-final-anonymous-mobile.png)
- [AI Works 正式公网移动来源抽屉](demo-acceptance/browser/aiworks-final-anonymous-mobile-drawer.png)
- [产品说明计划书](product-plan.md)

# 知乎选哪边

把知乎长回答拆成“主张、原文证据、使用条件和代价”，再按用户条件给出可追溯、可比较、可复现的决策建议。

当前场景为家用咖啡机：**胶囊机 vs 半自动**。产品不替用户决定，而是把分散在回答里的经验整理成一张能核对、能质疑的决策地图。

## 在线体验

- 正式公网 Demo：<https://v08hlna9o1wc.aiworks.site/>
- 官方项目页：<https://www.zhihu.com/project/detail/270773>
- 产品说明计划书：[product-plan.md](product-plan.md)
- 核心优化验收报告：[core-optimization-acceptance.md](core-optimization-acceptance.md)
- [演示视频 MP4](demo-video/知乎选哪边-演示视频.mp4) · [SRT 字幕](demo-video/demo.srt) · [ASS 字幕](demo-video/demo.ass)

正式公网版本为 **V 1.0.1**，已通过知乎 AI Works 审核。带 `preview` 的地址仅支持作者登录调试，不是匿名公网入口。

## 核心功能

- 三个使用条件、十八种组合的确定性重排。
- 条件变化同步更新推荐顺序、规则解释和来源依据。
- 同分时明确显示“得分并列，没有单一推荐”。
- 每条主张展示精确原文证据、条件、代价、答主、赞同数和知乎回链。
- 来源抽屉保留完整主张列表，并在滚动时吸顶显示答主、赞数和原文入口。
- 意见相反时并排比较双方主张、条件和代价；条件不同或未说明时不伪装成同条件证据。
- 展示“知乎原文 → AI 离线抽取 → 程序校验 → 确定性重排”的真实处理链路。

## 技术栈

- 前端：原生 HTML / CSS / JavaScript，无框架、无后端。
- 数据：静态 `data.js`，浏览器不调用模型。
- 抽取流水线：Python 3.12、标准库、`jsonschema>=4.23,<5`。
- 测试：Python `unittest`，当前 34 项回归测试。
- 部署：纯静态站点；正式版本部署在知乎 AI Works。

## 本地运行

### Windows PowerShell

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r pipeline/requirements.txt
$env:PYTHONPATH = "pipeline/src"
python -m unittest discover -s pipeline/tests -v
python pipeline/scripts/build_demo_data.py
python -m http.server 8000 --directory prototype
```

然后打开 <http://127.0.0.1:8000/>。

### Bash / Git Bash

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r pipeline/requirements.txt
PYTHONPATH=pipeline/src python -m unittest discover -s pipeline/tests -v
python pipeline/scripts/build_demo_data.py
python -m http.server 8000 --directory prototype
```

`prototype/data.js` 已包含当前审核后的导出数据，直接启动静态服务即可体验。运行构建脚本会用审核输入重新生成 `prototype/`、`deploy/` 和 `deploy-probe/` 的 `data.js`；后两个目录是生成物，不纳入仓库源码。

## 数据构建链路

构建入口为 [pipeline/scripts/build_demo_data.py](pipeline/scripts/build_demo_data.py)，默认读取：

- `pipeline/runs/prepared-v1.json`：抓取后保留的候选正文与来源元数据。
- `pipeline/runs/approved-v1/approved-extractions.json`：通过审核状态的抽取记录。
- `pipeline/scenarios/coffee.json`：选项、条件和证据词表。

脚本执行以下检查后才允许导出：

1. 固定 Schema 与选项、倾向枚举有效。
2. 主证据必须是候选 `content_text` 的逐字连续子串。
3. 代价证据存在时也必须逐字匹配。
4. 非空条件必须在主证据或代价证据内具有词面支持。
5. 仅允许 `review.reviewed=true` 且 `review.status="approved"` 的记录进入前端。
6. 来源链接必须为知乎 HTTPS 地址，并保留作者、标题和元数据。

任一字段失败时隔离整个候选，不保留看似合理的部分。

## 目录结构

```text
.
├── prototype/                 # 前端源码入口：index.html + data.js
│   └── data/raw_candidates.json  # 回归测试所需候选夹具
├── pipeline/
│   ├── src/aiworks_pipeline/  # 抽取、校验、审核、装配、审计与评估模块
│   ├── scripts/               # 离线流水线、审核、构建与交付校验脚本
│   ├── schemas/               # 固定 JSON Schema
│   ├── prompts/               # 抽取提示词
│   ├── scenarios/             # 咖啡机场景配置
│   ├── tests/                 # 34 项回归测试与测试数据
│   ├── runs/                  # 构建与审计所需的已准备、已审核数据
│   └── review/                # 最终 AI 辅助开发集与人工复核测试依赖
├── demo-acceptance/           # 公网验收 JSON、条件矩阵与截图证据
├── demo-video/                # 最终 MP4 与 SRT / ASS 字幕
├── product-plan.md            # 产品说明计划书
└── core-optimization-acceptance.md
```

`deploy/`、`dist/`、`deploy-probe/` 和 `cloudbase-release/` 是部署副本或打包目录，不纳入源码仓库。`pipeline/review/` 只保留最终开发集和测试依赖，多轮审核队列、分区文件与人工模板保留在本地；`pipeline/runs/` 不包含原始模型响应。`demo-video/` 只保留最终视频和字幕，原始录屏、音频、抽帧及录制脚本保留在本地制作目录；`demo-acceptance/` 保留验收 JSON、矩阵和截图，但排除浏览器缓存与会话专用脚本。

## 验证

运行回归测试：

```powershell
$env:PYTHONPATH = "pipeline/src"
python -m unittest discover -s pipeline/tests -v
```

当前结果：**34/34 通过**。

正式公网还完成过以下验收：

- 桌面与 390×844 移动端各 36 组条件组合。
- 29 个来源抽屉、92 条主张 AI 处理链路、29 个知乎回链结构。
- Runtime、Console、Network 和横向溢出失败均为 0。
- 正式地址无 Qoder 水印，移动端标题与推荐卡无遮挡。

## 数据与诚信边界

- 当前导出包含 **29 个知乎来源、92 条主张**。
- 数据角色是 **AI 辅助开发集**，不是独立人工黄金集。
- 审核为两轮独立 AI 审核加 AI 裁决，不等同于真人双人复核。
- `human_double_review_completed`、`test_set_locked` 和 `quality_reporting_eligible` 保持 `false`。
- 32 条模型评估只用于诊断，不用于对外宣称准确率。
- 页面分数是确定性相对匹配分，不是概率、准确率、人工评分或购买保证。
- AI 抽取是离线真实处理流程，浏览器不会伪装成实时模型调用。

## 许可证

原创代码与项目文档采用 [MIT License](LICENSE)。知乎回答、作者信息、赞同数和原文链接归原平台及原作者，不受本项目 MIT 许可证覆盖；仓库保留来源链接与抽取审计信息，用于赛事展示和技术复现，不将知乎内容声称为独立数据集或质量基准。

## 安全与仓库边界

- `zhihu-cli-secret.txt`、`.env*` 和任何凭据不得提交。
- 原始 API 响应、部署 ZIP、浏览器缓存、原始音视频和会话专用脚本均已加入 `.gitignore`。
- 如需重新生成部署包，应使用赛事官方部署流程，不要把真实事件 ticket 写进源码或日志。

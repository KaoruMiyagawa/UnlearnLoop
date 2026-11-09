# IELTS 内容与功能覆盖矩阵

状态口径：**可运行**表示本仓库当前存在服务端数据/功能；**计划中**表示不可作为真实功能入口。当前目录版本为 `ielts-spec-catalog-2026-03`，是应用侧复核快照标记，不是 IELTS 官方版本编号。

## 考试版本

| Variant | 考试结构/评分 | 当前产品状态 | 验收边界 |
| --- | --- | --- | --- |
| IELTS Academic | Listening、Academic Reading、Academic Writing、Speaking；四科 Band 1–9，Overall 按官方规则汇总 | 阅读微型训练可运行 | 新 session 保存 `academic` 与规范快照；不提供官方考试或分数保证 |
| IELTS General Training | Listening、GT Reading、GT Writing、Speaking；Band 制 | 阅读微型训练可运行 | 新 session 保存 `general_training`；阅读/写作内容不与 Academic 混用 |
| IELTS for UKVI Academic | 适用签证/移民目的的安全考试；基于 Academic 对应考试结构 | 计划中 | 目录标明 planned；不能选择或伪装已支持；不创造额外题型 |
| IELTS for UKVI General Training | 对应 GT 结构的安全考试 | 计划中 | 同上；适用范围/身份要求从官方来源核验 |
| IELTS Life Skills A1 | 听说互动；Pass/Fail，不适用四科 Band Overall | 计划中 | 独立数据流程和通过评价，不创建 Band 字段 |
| IELTS Life Skills A2 | 听说互动；Pass/Fail | 计划中 | 同上，级别能力描述独立版本化 |
| IELTS Life Skills B1 | 听说互动；Pass/Fail | 计划中 | 同上，不套用 Academic/GT 阅读模考 |

Academic 和 GT 共用 Listening、Speaking 的能力内容可以按素材授权复用；阅读与写作模块必须有独立内容/规则版本。UKVI 的可用性、考试中心和签证适用条件不从内容题型推导。

## 四科结构、主要题型与交互

### Listening（Academic/GT 共用）

| 题型 | 交互/数据要求 | 当前 |
| --- | --- | --- |
| Multiple choice | 单选/多选，题目组关系与逐题答案 | 计划中 |
| Matching | 左右项配对，保留逐项证据 | 计划中 |
| Plan/map/diagram labelling | 图片或授权 SVG、可访问文本替代、方位选择/标注 | 计划中 |
| Form/note/table/flow-chart/summary completion | 多空、字数限制、拼写/数字变体、每空评分 | 计划中 |
| Sentence completion | 单空/多空、字数约束 | 计划中 |
| Short-answer questions | 多个短答、每题答案和词数上限 | 计划中 |

音频资产需带原创/许可来源、语言/口音说明、时长、编码、哈希、分段、题目时间锚点。练习允许重播；模拟考试重播规则由已选版本配置，音频不可用不得提交空结果。

### Reading

| 类型 | Academic / GT 适用 | 交互需求 | 当前 |
| --- | --- | --- | --- |
| Multiple choice | 两者 | 单选或多选、选项集合、答案键 | A/G 各原创微型题组可运行 |
| Identifying information (True/False/Not Given) | 两者 | 三值选择，严格区分反证与未提及 | 计划中 |
| Identifying writer’s views/claims (Yes/No/Not Given) | 两者 | 观点归属的三值选择 | 计划中 |
| Matching information | 两者 | 题项与段落、多对一约束 | 计划中 |
| Matching headings | 两者 | 段落与标题配对 | 计划中 |
| Matching features | 两者 | 人物/理论/特征配对，可重复性配置 | 计划中 |
| Matching sentence endings | 两者 | 前半句与结尾组合、选项约束 | 计划中 |
| Sentence completion | 两者 | 空位、字数限制和答案变体 | 计划中 |
| Summary/note/table/flow-chart completion | 两者 | 多空结构、局部/列表答案、字数限制 | 计划中 |
| Diagram label completion | 两者 | 图片语义锚点、可访问替代文本 | 计划中 |
| Short-answer questions | 两者 | 单题答案、词数限制 | 计划中 |

Academic 内容重点为学术/科学/社会说明与论证文本；GT 内容按官方所述日常、工作及一般兴趣文本层级组织。不得将两种考试的阅读原始分数转换表互换。当前实现只覆盖客观规则评分，不计算 Reading Band。

### Writing

| 任务 | Academic | General Training | 数据/评价需求 | 当前 |
| --- | --- | --- | --- | --- |
| Task 1 | 图表、表格、流程、地图/平面图等信息描述 | 正式/半正式/非正式书信 | 长文本、题目素材、Task Achievement（A）/Task Response（GT）证据锚点 | 计划中 |
| Task 2 | 议论文/讨论/观点等写作任务 | 议论文/观点任务 | Task Response；Task 2 权重高于 Task 1 的汇总规则需版本化 | 计划中 |
| 共通评价维度 | Coherence and Cohesion、Lexical Resource、Grammatical Range and Accuracy | 同左 | 每维观察、原文区间、建议、弃评理由、人工/AI 来源 | 计划中 |

作文需保存草稿版本、题目版本、提交快照和用户同意信息。AI 维度反馈不等于官方 Band；未经专家盲评校准只提供明确标注的练习反馈，不给 Band 估分。

### Speaking

| 部分 | 官方形式概要 | 产品交互/数据 | 当前 |
| --- | --- | --- | --- |
| Part 1 | 熟悉主题问答 | 录音轮次、提示、回答时长 | 计划中 |
| Part 2 | 个人长答及准备时间 | Cue card 版本、准备计时、长答录音 | 计划中 |
| Part 3 | 延展讨论 | 追问链、轮次与主题关联 | 计划中 |
| 四维反馈 | Fluency and Coherence、Lexical Resource、Grammatical Range and Accuracy、Pronunciation | 文本/音频时间锚点、噪音与可懂度、弃评状态 | 计划中 |

录音前请求浏览器权限并解释存储/处理方式；保存媒体授权、时长、格式和哈希。转写只作为语言文本证据，不能单独证明 Pronunciation 或语音流利度。无可靠音频证据必须弃评。

## 学习模式及共通验收

| 模式 | 范围 | 完成标准 |
| --- | --- | --- |
| 训练 | 可暂停、查看材料、按需重播/查看解释（未来） | 每次回答关联服务端派发题、题目版本、原始回答和评价来源；错误可进入诊断 |
| Agent 诊断 | 竞争假设、支持/反对证据、追问、干预 | 不因单错确认原因；下一步由服务端合法状态决定；Fake 明确标识 |
| 独立迁移 | 新题且不同情境 | 旧题/追问题不能成为迁移证据；题库耗尽时降级，不提升状态 |
| 间隔复习 | 到期派题、作答、反馈与下一计划 | 只有有效独立作答产生保持证据；点击完成不能替代答题 |
| 模考 | 版本化整卷、计时与提交 | 内容许可完成；计时/播放由后端记录；未完成科目不伪造 Overall；来源标识为模拟 |
| 档案 | 按考试/技能展示证据及错误历史 | 显示人工/规则/模型来源和时点；估分不可冒充官方分数 |

## 内容资产、版权来源与阶段

| 资产 | 许可/来源规则 | 首次阶段 |
| --- | --- | --- |
| 文本题组、题目、答案和错误模式 | 首选原创，保留作者、审核人、许可、版本、撤回状态；不得抓取商业真题 | I1 阅读；后续四科扩展 |
| 音频、转写、图示 | 原创或书面授权；存储地区/期限、衍生权和删除流程明确 | I3 |
| 写作题及标注样本 | 原创题；专家标注合同、匿名化及用途范围 | I4 |
| Speaking 提示与录音样例 | 原创提示、说话人明确授权及声音数据保留政策 | I5 |
| 官方规则说明 | 只存最小必要结构化元数据与来源链接；定期复核官方网页 | 每次目录发布 |

## 官方来源

- [Academic Reading](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-reading)
- [Academic Listening](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-listening)
- [Academic Writing](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-writing)
- [Academic Speaking](https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-speaking)
- [General Training](https://ielts.org/take-a-test/test-types/ielts-general-training-test)
- [UKVI](https://ielts.org/take-a-test/test-types/ielts-for-ukvi)
- [Life Skills](https://ielts.org/take-a-test/test-types/ielts-life-skills)
- [Scoring](https://ielts.org/take-a-test/your-results/ielts-scoring-in-detail)

发布题库或更改结构前，应逐条重新核实上述页面及具体规范；矩阵不构成考试培训机构或 IELTS 官方认证。

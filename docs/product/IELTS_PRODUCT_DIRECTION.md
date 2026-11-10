# VerbaTrail 产品方向（暂定名）

更新日期：2026-11-09。此文档记录 VerbaTrail 的 IELTS 产品方向；GitHub 仓库 URL、历史数据和 Python 技术追溯标识暂保留原样。

## 产品承诺与边界

帮助英语学习者从有证据的当前水平出发，逐步准备 IELTS Academic 或 General Training，并把 Overall 8.0 作为默认可编辑目标。目标不是成绩承诺。系统反馈、诊断与未来的自动评分均须标明来源和不确定性；系统结果不是 IELTS 官方成绩。

当前可选考试模式是 Academic 与 General Training。IELTS for UKVI Academic/General Training 与 Life Skills A1/A2/B1 在产品目录中显示为计划中，不可启动学习流程。UKVI 适用目的/考试安全要求由基础版本继承，不在题型上虚构差异；Life Skills 是听说及 Pass/Fail 体系，不生成 Band 或 Overall。

## 学习闭环

1. 选择已开放考试版本和目标；目标、版本、日期在服务端保存，并在新会话快照考试目录版本。
2. 从四科能力入口选择已开放训练。当前只有原创阅读 A/G 各一套小型服务端题组可运行，其余明确标为计划中。
3. 服务端派题并保存题目版本、原始回答、确定性评价与来源。不同领域使用独立评价器；没有评价器时失败关闭。
4. 错误只形成有来源的候选假设；证据不足可继续追问。Agent 派发的追问和练习使用现有状态机及服务端合法题目。
5. 用不同材料的迁移题确认当前能力变化，再由已有复习调度安排延迟测验。当前迁移通过不等于长期保持。
6. 复习、档案和历史沿用已有真实服务端数据。旧 Python 会话继续可读且没有考试版本，不会自动改成 IELTS。

## 产品模式与核心能力

| 能力 | 当前实现 | 下一步产品要求 |
| --- | --- | --- |
| 考试目录/目标 | A/G 可保存，四科目标默认 8.0，当前水平为待评估；其余五种计划中 | 目标日期编辑、目标审计历史、实际基线评估 |
| Reading | 原创 Academic/GT 微型题组、服务端派题、客观答案键、作答持久化、现有诊断与迁移机制 | 完整题型和题组、题库审核、阅读题型专属反馈与覆盖统计 |
| Listening | 未实现 | 授权音频、播放状态、逐空证据、播放规则版本 |
| Writing | 未实现 | Task 1/2 作答版本、维度反馈及人工校准门槛 |
| Speaking | 未实现 | 录音授权、转写、轮次和时间锚点、发音弃评机制 |
| Agent 与复习 | 复用既有诊断、竞争性假设、追问、针对性练习、独立迁移、真实间隔复习 | IELTS 特定语言错误模式和经过评测的多技能证据映射 |
| 词汇/语法/计划 | 未实现 | 与 Reading/Writing/Speaking 错误关联的可解释练习计划 |
| 模考 | 未实现 | 版本化考试蓝图、计时和提交约束、非官方成绩标注 |
| 档案 | 复用已有服务端复习与档案数据 | 四科独立能力证据、人工/自动评价来源分开呈现 |

## 评分及内容政策

客观题只按题目版本内的审核答案键/规则评价。写作官方公开维度为 Task 1 的 Task Achievement、Task 2 的 Task Response、Coherence and Cohesion、Lexical Resource、Grammatical Range and Accuracy；口语维度为 Fluency and Coherence、Lexical Resource、Grammatical Range and Accuracy、Pronunciation。任何 AI 维度反馈都必须标成非官方，提供文本或音频证据锚点和弃评原因；未通过专家标注盲测前不显示 AI Band。

所有首发内容须原创或有明确许可记录。当前 Reading pack 为项目原创练习，不包含官方真题、官方录音、官方评分描述全文或商业题库。IELTS 名称只用于描述兼容的备考方向；发布前完成商标、版权和品牌审查。

音频、作文、转写和学习记录按个人数据处理：默认本地 Fake provider、远程调用关闭；上传/录音前明确用途、地区、供应商、保留期和同意撤回。当前 learner_id 是本地筛选字段，不是登录或多用户鉴权。

## 版本变化

考试规范、题型元数据、评分规则、题目内容和评价器分别版本化。服务端 session 快照考试目录版本；新官方政策需要研究、内容审校、兼容性测试后发布，不回写历史成绩。上线前由产品负责人复核官方规则来源与更新时间。

## 当前需确认

1. 正式品牌是否采用 VerbaTrail，以及中文名是否采用“语迹”。
2. 首发地区/用途、语言和设备优先级；何时引入认证及云端账号。
3. 是否允许任何远程文本/语音提供商、数据处理地区与费用上限。
4. 内容编辑、专家评分校准、录音/作文保存期限、导出和删除策略。

## 官方资料

- [IELTS test types](https://ielts.org/take-a-test/test-types)
- [Academic test format](https://ielts.org/take-a-test/test-types/ielts-academic-test)
- [General Training format](https://ielts.org/take-a-test/test-types/ielts-general-training-test)
- [IELTS scoring](https://ielts.org/take-a-test/your-results/ielts-scoring-in-detail)
- [IELTS Life Skills](https://ielts.org/take-a-test/test-types/ielts-life-skills)
- [IELTS for UKVI](https://ielts.org/take-a-test/test-types/ielts-for-ukvi)

以上官方页面需在每次发布考试目录时重新核实；本项目目录版本标识产品采用的规范快照，不声称官方版本号。

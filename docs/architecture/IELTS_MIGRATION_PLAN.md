# IELTS 领域迁移与兼容计划

## 设计原则

在现有学习引擎上增加考试上下文和内容类型，不另建一套并行 Agent/复习系统。现有 `KnowledgeTopic`、`LearningMaterial`、`Question`、`LearningSession`、`Attempt`、诊断案例/假设/证据、`KnowledgeState`、`ReviewItem`、`DecisionEvent`、`LearningProfile` 及迁移保持为复用基础。旧 Python 评价继续走 `RuleEvaluator`；IELTS 阅读必须由显式的领域评价器处理；未注册领域失败关闭。

## 概念到当前/未来数据的映射

| 产品概念 | 当前落点 / 后续选择 | 说明 |
| --- | --- | --- |
| ExamFamily/ExamVariant | `backend/app/domain/exams.py` 中版本化目录枚举 | 当前七个候选：Academic、GT、UKVI Academic/GT、Life Skills A1/A2/B1；目录定义产品可用性及评分族，不代表官方目录版本 |
| ExamSection | 初期由 topic `domain_code` + exam variant 共同约束 | 后续内容元数据增加 section、题型范围；不复制 topic/session 的状态机 |
| QuestionType | 复用通用题型；必要时通过版本化 `question_format`/字段承载题组结构 | 不把每个 IELTS 题型硬编码成独立数据库表；多空等题型需要结构化答案格式 |
| Question | 复用题目、材料、rubric、版本、角色 | 公开 DTO 仅返回题面和选项上下文，不返回答案/内部 rubric |
| Attempt/Evaluation | 复用 Attempt 原始作答及评价快照；增加 evaluator/criteria 版本时做向后兼容字段迁移 | 阅读答案键确定评价；写说未来需要多维评价 JSON 和证据锚点，AI Band 与官方 Band 分离 |
| SkillEvidence | 现有 EvidenceLink 与 DecisionEvent 供诊断证据使用 | 后续将技能、能力维度、来源、有效期和评价标准纳入结构化模型，禁止把一次正确视为稳定能力 |
| LearningProfile | 复用既有学习档案及 KnowledgeState；新增 `ExamPreparationProfile` 保存考试目标 | Profile 按 learner id 过滤；目前本地 learner id 不是认证身份 |
| MediaAsset | 后续新增受控媒体元数据/存储引用 | 不把音频二进制放 SQLite；外部媒体需许可、访问控制、生命周期和删除流程 |
| MockExam/ExamRun | 后续新增版本化 blueprint/run 状态机 | 仅当真模考开发时建表，当前不为未实现功能提前创建平行架构 |

## Stage 5C 基础实体复用

现有 KnowledgeTopic 作为学习目标；LearningMaterial 保存文章；Question 按 `initial`、`diagnostic_followup`、`targeted_practice`、`transfer_check`、`review` 发题；Attempt 保存回答及评价；诊断引擎保留多个假设及 EvidenceLink；迁移题和复习仍走既有领域状态流。Academic/GT 用 `ielts_academic` / `ielts_general_training` 域分开内容与评价，且 session 保存考生选定的 variant 快照。

## 0004 数据库迁移

不改写 0001–0003。新增 `0004_ielts_exam_profiles`（down_revision=`0003_evidence_based_reviews`）：

- `learning_sessions.exam_variant` 与 `exam_spec_version` 均 nullable。所有历史 Python 会话保持 NULL；迁移不推测并回填考试模式。
- 新表 `exam_preparation_profiles`：`learner_id` 主键、考试 variant、目标评分类型、Band 目标 JSON、Pass 目标、可选日期、实际能力评估状态、产品规范快照版本、更新时间。
- 约束保证 band/pass 目标形态不互相混用；A/G 暂为唯一可保存目标。Life Skills 将来要用 pass 目标，但接口和验证另阶段开放。

升级不删除/清空历史。部署前备份用户数据库；本次开发验证仅在隔离 SQLite 上执行 0003→0004，并检查既有 Python session、attempt、ReviewItem 数量与关键字段不变。迁移不自动执行数据转换。回滚只允许在应用确认新增数据可舍弃的情况下通过备份恢复演练，不用 downgrade 删除用户目标。

## 考试版本与流程快照

新 IELTS LearningSession 在开始时保存可用 variant 和 `ielts-spec-catalog-2026-03` 规范快照。A/G 阅读 topic 必须与已保存 ExamPreparationProfile 相符；请求不能自行覆盖已保存模式。非 IELTS topic 创建的历史及新 Python session 不接受 IELTS variant。旧会话恢复使用历史 topic 和原 session，不按当前档案重新解释。

目录快照是产品侧的可追溯标记。将来题目还需保存题型 schema/rubric/content 版本；考试规范变更只影响新会话，保留历史结果使用时的版本。

## 评价器分离与安全失败

`evaluator_for_domain` 显式映射 Python 和 IELTS 阅读。IELTS 评价根据当前题目的答案键和接受答案集合判客观题；错误映射只添加低权重候选和规则检查证据，不能当作最终诊断。缺少 IELTS 题目/答案键或领域注册时拒绝评价，不调用 Python 代码追踪 evaluator 兜底。未来 Writing/Speaking 需要多维 evaluation schema 和校准版本，不复用客观答案键接口。

## API 边界

- `GET /api/v1/exams/catalog`：7 个版本及评分族、产品可用性、共享基础版本和规范快照。
- `GET/PUT /api/v1/profile/exam-preparation?learner_id=...`：目标读取/保存；当前只允许 A/G。
- `POST /api/v1/sessions` 接收 variant 并在服务端验证已保存目标与 topic 域；返回 session 版本快照。
- `GET /api/v1/sessions/{session_id}/material` 只返回当前派发题目关联的材料；IELTS 主题详情和材料列表不预先返回迁移与复习文章。旧 Python 主题的材料接口保持可用。
- 既有 sessions/attempts/diagnoses/reviews/profile/history API 保持领域权威；DTO 不暴露标准答案和内部 rubric。
- 后续题组、媒体、作文多维评价、语音及模拟考试 API 在对应阶段按实际需求添加，不提前虚构契约。

## 隐私、版权与用户隔离

当前 API 是本地单用户模式，learner_id 只是过滤参数；不可据此宣传已实现账号隔离。发布到多人/云端前必须有认证授权、对象归属检查、速率与存储策略。材料资产带原创/授权/撤回元数据；音频及作文须有独立同意、数据地区、保留/删除和费用策略。日志只保留脱敏摘要，任何密钥与用户原文不得入 Git。

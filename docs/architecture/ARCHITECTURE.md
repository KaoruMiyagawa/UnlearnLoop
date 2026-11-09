# UnlearnLoop 系统架构

> 本文保留原架构设计与目标，部分内容尚未实现；当前分支实际实现及安全边界见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。

## 1. 目标与边界

第一阶段采用单体仓库、前后端分离的模块化结构。FastAPI 提供版本化 HTTP API，React 负责工作空间界面，SQLite 保存本地学习记录，AI 通过后端模型服务调用。知识领域通过内容包、题型适配器和评估器扩展；引导式工作流、证据模型和诊断决策不绑定 Python。先不拆分微服务，避免核心决策流程未稳定时增加分布式成本。

## 2. 模块与职责

### 前端

- `app-shell`：导航、路由、全局错误边界和会话上下文。
- `learning-workspace`：跨学科材料、问题、答案草稿和提交状态。
- `diagnosis-workspace`：候选错误原因、证据、追问和时间线。
- `review-workspace`：复习队列、历史详情和迁移验证。
- `profile-workspace`：知识点状态、设置和数据控制。
- `design-system`：颜色令牌、排版、按钮、表单、状态和布局组件。

### 后端

- `api`：请求校验、认证边界、响应模型和错误映射。
- `application`：学习会话、诊断、干预、迁移验证、复习等用例编排。
- `domain`：候选假设、证据、决策状态、学习状态和转移规则。
- `evaluation`：按知识包选择文本、代码、公式或其他领域评估器，负责模型输出结构化和规则校验。
- `decision`：选择诊断问题与下一步动作，输出理由和不确定性。
- `model_provider`：DeepSeek/Ollama 适配器、超时、重试、限流和结构化输出。
- `persistence`：SQLAlchemy 模型、仓储、事务和迁移。
- `observability`：请求 ID、决策事件、模型调用元数据和脱敏日志。

应用层编排用例，领域层不直接依赖 FastAPI、HTTP 或具体 SDK；这样可用固定输入测试决策，也能替换存储和模型。

## 3. 前后端交互与数据流

前端通过 JSON REST API 与后端交互，所有业务端点置于 `/api/v1`。创建会话后读取问题和状态；答案提交进入后端事务，保存原始答案和事件，再调用评估/模型服务，校验结构化结果，生成候选假设与下一步决策，最后返回状态。第一阶段优先同步请求，长耗时调用设置超时；真实延迟证明需要后再引入任务状态端点。

典型数据流：

`学习材料/知识点 → 题目版本 → 学习者答案 → 评估结果 → 证据 → 候选错误假设 → 诊断问题选择 → 新证据 → 干预决策 → 迁移结果 → 知识状态/复习安排`。

关键转移写入不可变领域事件或可重建记录。派生状态可以更新，但历史证据不覆盖；重复请求使用幂等键避免重复事件。

## 4. 数据库实体与关联方向

- `User` 1—N `LearningSession`、`UserSetting`。
- `KnowledgeTopic` 1—N `LearningMaterial`、`Question`、`KnowledgeState`。
- `LearningMaterial` 1—N `Question`。
- `LearningSession` 1—N `Attempt`、`DiagnosticCase`、`DecisionEvent`。
- `Question` 1—N `Attempt`；`Attempt` 保存答案快照、评估结果和状态。
- `DiagnosticCase` 1—N `Hypothesis`、`DiagnosticQuestion`、`Intervention`。
- `Hypothesis` 1—N `EvidenceLink`；证据可指向作答、追问、模型评估或规则检查。
- `ReviewItem` 关联 `KnowledgeTopic`、`Hypothesis` 或 `LearningSession`，保存复习原因、计划时间和结果。
- `ModelCall` 关联上下文与 `DecisionEvent`，只保存提供商、模型、提示版本、耗时、状态和脱敏摘要。

关系方向以外键和显式关联表表达，不把完整模型原文作为唯一真相。原始答案与模型输出区分保存，并根据隐私设置支持删除或脱敏。

## 5. API 设计原则与初始端点

API 使用资源导向命名、明确 request/response schema、稳定错误码和统一关联 ID。写操作返回资源或任务状态；列表支持分页、筛选和稳定排序；时间使用带时区的 ISO 8601。API 不把模型原文格式暴露给前端，前端只依赖领域结果。

初始端点草案：

- `GET /api/v1/topics`、`GET /api/v1/topics/{id}`
- `POST /api/v1/sessions`、`GET /api/v1/sessions/{id}`
- `POST /api/v1/sessions/{id}/attempts`
- `GET /api/v1/diagnoses/{id}`、`POST /api/v1/diagnoses/{id}/responses`
- `POST /api/v1/diagnoses/{id}/interventions/{action}`
- `POST /api/v1/sessions/{id}/transfer-check`
- `GET /api/v1/reviews`、`POST /api/v1/reviews/{id}/complete`
- `GET /api/v1/profile/knowledge-states`

错误响应至少包括 `code`、用户可读 `message`、`request_id` 和可选字段错误详情。模型超时、配额、无效结构化输出和服务不可用映射为不同的可测试错误。

## 6. Agent 决策流程、工具调用与证据

Agent 不是自由聊天循环，而是受领域状态约束的决策器。诊断案例至少经历：`收集作答` → `初步评估` → `生成候选假设` → `需要区分证据` → `选择诊断问题` → `更新假设` → `选择干预` → `迁移验证` → `更新学习状态/安排复习`。模型失败可进入 `等待重试`，用户中断可进入 `已暂停`。

每次决策输入包含知识点、题目、答案、已有假设、证据摘要、可用动作和策略版本；输出是 schema 约束 JSON，包含 `action`、`reason`、`target_hypotheses`、`confidence`、`required_evidence` 和 `next_state`。后端执行白名单工具，而不是让模型直接决定任意函数或 URL。

工具边界：读取题目/材料、读取历史证据、保存假设、生成诊断问题、保存答案、安排练习、安排复习、更新知识状态。每个工具校验输入、权限和当前状态，记录调用结果；工具失败不应被模型当作成功。

证据记录至少包含 `evidence_id`、来源类型、来源引用、摘要、时间、支持/反对关系、可靠性备注和产生它的决策事件。置信度是当前工作判断，不是统计保证；UI 和 API 标注“信息不足”与“模型推断”。

区分度先采用可解释启发式：若追问能让候选假设产生不同预期答案、成本低且与知识点直接相关，则得分更高。模型可提出候选追问，但最终由 schema 和规则过滤后执行。所有决策应可用固定 fixture 重放。

## 7. 模型服务抽象

定义 `ModelProvider` 协议，例如 `generate_structured(request, schema, context) -> ModelResult`，业务层只依赖协议。`DeepSeekProvider` 负责 API 鉴权、请求格式、模型名、超时、重试和响应解析；未来 `OllamaProvider` 复用相同接口，差异限制在适配器配置。

配置通过环境变量或本地配置注入：提供商、模型、基础 URL、超时、最大 token、温度、重试次数和是否允许远程发送答案。密钥只从环境或密钥管理服务读取，不写入数据库、前端包或普通日志。

处理顺序为：请求校验 → 超时控制 → 有限重试（只对可重试错误）→ JSON/schema 校验 → 内容安全和业务边界校验 → 记录元数据 → 返回领域结果。失败时保留答案和已有证据，进入可重试状态，不生成看似正常的诊断结论。

## 8. 安全、隐私与数据治理

第一阶段默认本地单用户，但仍按用户边界设计查询。答案、材料和模型日志按最小必要原则保存；日志脱敏，禁止记录 API key；远程模型发送前明确配置和提示。未来多用户必须加入认证、授权、租户隔离、速率限制和审计。

不执行未经安全评审的用户代码，不允许模型生成任意数据库查询、文件路径或网络请求。模型输出视为不可信输入，必须结构化校验、长度限制和渲染清洗。提供删除学习数据和清除模型调用摘要的路径。

## 9. 可测试性与质量门槛

领域决策使用纯函数或最小依赖服务，覆盖状态转移、置信度边界、证据更新、幂等和失败回退。后端用 pytest 做单元、API、数据库迁移和模型适配器 contract 测试；AI 调用使用 fixture、假 provider 和回放样本，不依赖真实网络。前端测试核心工作流、加载/错误/空状态、键盘操作和 API contract。

CI 至少执行格式/规范检查、类型检查、pytest、前端测试和构建；任何测试失败或 schema 不一致都阻止合并。关键决策事件可导出为 fixture，支持回归测试和人工审阅。

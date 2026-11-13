# VerbaTrail 当前架构与能力边界

更新日期：2026-11-13。本文描述当前 VerbaTrail 的代码结构及已知边界。[产品方向](../product/IELTS_PRODUCT_DIRECTION.md) · [目标架构](ARCHITECTURE.md)

## 当前运行架构

- **前端：** React、TypeScript、Vite 和单一 API Client。学习、诊断、迁移与复习工作区共享组件及业务流程；Premium Academic / Noir & Champagne 由 ThemeProvider、`data-theme` 和 CSS Variables 驱动。
- **HTTP/API：** FastAPI 提供版本化 `/api/v1` 接口。API schemas 对学生可见数据建模，题组展示内容与私有答案键/评分规则分离。
- **应用服务：** 应用层编排考试配置、内容/题目选择、学习会话、提交、诊断、专项训练、Matching Headings 迁移与复习。
- **领域与评价：** 领域规则验证学习状态转换、Matching Headings 题组及逐项评价。规则协议和 FakeModelProvider 支持流程执行与测试，不构成真实模型个性化质量证据。
- **持久化** SQLAlchemy 仓储保存内容版本、Question、LearningSession、Attempt、诊断假设、KnowledgeState、ReviewItem 与证据有效性事件。Alembic 当前单一 head 为 `0007_evidence_validity_events`。测试和浏览器流程使用隔离 SQLite。

```mermaid
flowchart LR
    UI[React 工作区 / API Client] --> API[FastAPI /api/v1]
    API --> APP[应用服务]
    APP --> DOMAIN[领域规则与状态转换]
    APP --> CONTENT[版本化阅读内容]
    APP --> AGENT[受约束的规则诊断流程]
    AGENT --> PROVIDER[FakeModelProvider / Provider 接口]
    APP --> REPO[SQLAlchemy 仓储]
    REPO --> DB[(SQLite)]
    DB --> MIG[Alembic 0001–0007]
```

## 当前 IELTS 实现范围

产品导航呈现 Learn / Discover / Adapt。Learn 首页 `/` 提供 Listening、Speaking、Reading、Writing 四个入口。Reading 使用既有 `/learning` 工作区，`/learn/reading` 可直接访问同一工作区。Listening 位于 `/learn/listening`，含一套约 64 秒原创合成音频、5 道客观题、服务端规则评分、提交后解释及音频时间锚点；Listening Attempt 存入既有共享 LearningSession/Attempt 历史。Speaking 与 Writing 仍为规划页。Discover 和 Adapt 显示规划状态。诊断、迁移、复习与学习档案保留原路由。

`frontend/src/learn/skills.ts` 定义类型化技能目录和能力状态。`implemented` 表示已有学习流程，`planned` 表示可浏览规划，`unavailable` 表示无可用入口。目录由前端静态维护。考试目标、题目派发、作答、诊断、复习和学习历史继续以共享 API 为准。

Academic 与 General Training 有有限的 Reading 流程，包括 TFNG 及 Matching Headings 结构化题组；Matching Headings 已接入固定内容版本、逐项评分、错误假设、追问、针对性训练、独立迁移和首轮延迟复习。历史、Review 和 Profile 消费服务端记录。

**IELTS-2B.1 Phase 6.2 最终工程验收为 PASS WITH LIMITATIONS。** 旧版证据有效性标记、派生状态协调与用户重新验证已在隔离 SQLite 复验。正式库的协调和生产发布评估仍有待执行。原 Phase 6 FAIL 作为历史记录保留。[最终复验](../development/IELTS_2B1_PHASE6_2_ACCEPTANCE.md) · [原 Phase 6 报告](../development/IELTS_2B1_FINAL_ACCEPTANCE.md)

完整 IELTS Reading 题型覆盖、完整 IELTS Listening 考试、Writing、Speaking、完整词汇/语法课程、模考、统一能力评估、个性化学习计划、多语言教学均未实现。Listening 仅交付有限原创试用练习，不提供官方 Band 分数；一次练习结果不代表长期能力，也不会产生迁移或保持证据。目标架构中的 Learner Model 和跨技能 Adaptive Agent 也还未完整落地。

## 证据与数据流

Matching Headings 当前典型流程：

`版本化题组 → 服务端派发并固定版本 → 结构化 Attempt 与逐项评分快照 → 候选诊断假设及证据 → 合法追问/专项训练 → 独立迁移 → ReviewItem / 延迟作答`

前端显示服务端返回的题型、评分及下一步状态。规则诊断保留候选原因和证据来源。训练、迁移和延迟保持是不同证据层级。当前验收主要覆盖首轮迁移和复习，更多独立复习周期仍待验证。

## 安全与信任边界

- 当前应用适合可信的本地单用户开发，不是生产级多用户服务。
- `learner_id` 是调用方可提供的筛选字段，不是认证或授权。按对象 ID 读取的部分接口未绑定经验证的用户身份；不能宣称已有租户隔离。
- 本地 FakeModelProvider 和规则执行不代表实时 LLM 成功，也不保证语义诊断正确。真实远程模型能力与质量尚未通过验证。
- 答案键及内部评分规则不得由学生题目/历史 DTO 返回；作答快照、题目版本和评分规则版本应保持可追溯。
- 开发和浏览器验证使用隔离 SQLite。服务启动会迁移配置的数据库；使用既有数据前应先做可恢复备份。
- 不应提交 `.env`、API 密钥、SQLite 学习数据、日志或本地缓存。

## 与目标架构的差距

当前系统是模块化单体：React + FastAPI + SQLAlchemy/SQLite。后续可在不提前拆微服务的前提下，逐步引入统一 Learner Profile/能力证据、Assessment、Learning Planner 和跨技能 Agent 策略。Listening、Writing、Speaking 需各自建立内容模型、证据与评价协议；其他语言扩展应将通用学习模型与语言特定内容/评价规则分层。上述均为规划，不代表现有可用功能。

# UnlearnLoop — Stage 5 视觉与交互原型说明及 API 数据契约需求

本目录存放 UnlearnLoop Stage 5 的三套独立交互视觉原型与对比总览入口，不覆盖 Stage 0 的早期原型（`docs/design/prototypes/index.html`）。

## 1. 文件清单与预览方式

- [index.html](./index.html)：**三套方案一键切换与对比评审总览台**（支持在同一窗口切换 A / B / C 方案，并同步切换 5 大核心页面）。
- [scheme-a-minimal-focus.html](./scheme-a-minimal-focus.html)：**方案 A · 极简专注型（Minimal Focus）** —— 单栏手稿脊柱（Zen Editorial Spine）+ 内联页边批注折页。
- [scheme-b-modern-learning.html](./scheme-b-modern-learning.html)：**方案 B · 现代学习产品型（Modern Learning Product）** —— 左轨导航 + 顶部六步闭环进度条 + 主操作区与右侧实时证据/假设检视器双栏联动。
- [scheme-c-exploratory-graph.html](./scheme-c-exploratory-graph.html)：**方案 C · 探索式学习型（Exploratory Graph）** —— 点阵空间画布 + SVG 知识点前置依赖拓扑 + 二维“竞争假设 × 正反证据”交叉验证矩阵 + T1→T4 时间轴回放。

## 2. 对 Codex 前端 API Client 与后端 DTO 的数据需求清单

在后续将选定视觉方案转化为正式 React/TypeScript 页面时，建议 Codex 在 `frontend/src/api/`（及必要时的后端响应聚合）中提供或确认以下字段支持：

1. **会话详情与迁移防刷分原因显式透出**：
   - `POST /api/v1/sessions/{session_id}/attempts` 返回的 `AttemptResultResponse` 已包含 `next_action`（如 `"diagnose"`, `"diagnose_step"`, `"transfer_check"`, `"transfer_failed_needs_practice"`, `"transfer_retry_blocked"`, `"mastery_achieved"`）。建议前端 API Client 将 `next_action` 定义为严格的 TypeScript 联合类型，并提供 `prior_failed_attempt_id?: string`（当 `next_action === "transfer_retry_blocked"` 时指向首次失败的迁移作答 ID），便于界面直接高亮“为何同题重试不能晋升 `stable`”。
2. **诊断决策时间线列表端点（或随 `DiagnosticCaseResponse` 附带）**：
   - 方案 B 的“决策审计时间线”与方案 C 的“时间轴演化回放（T1→T4）”需要展示当前 `DiagnosticCase` 关联的历史 `DecisionEvent` 列表（包含 `id`, `event_type`, `from_state`, `to_state`, `action`, `reason`, `uncertainty_level`, `created_at`）。
   - 当前 `GET /api/v1/diagnoses/{case_id}` 返回了 `status`、`uncertainty_level`、`hypotheses` 和 `evidence_count`，建议在 `DiagnosticCaseResponse` 中增加 `decision_events: list[DecisionEventSummary]` 或提供 `GET /api/v1/diagnoses/{case_id}/events`，使前端无需额外拼接即可渲染决策演化时间线。
3. **会话详情与掌握状态的正交字段**：
   - 为在界面上严格区分“会话已结束（`status = completed`）”与“当前知识点已掌握（`knowledge_state_status = stable`） vs 仍需练习（`needs_practice`）”，建议 `SessionDetailResponse` 与 `SessionSummaryResponse` 包含 `knowledge_state_status: KnowledgeMasteryStatus | null` 与 `topic_mastered: boolean`。
4. **运行模式与启发式声明字段**：
   - `DiagnosticCaseResponse` 与 `DiagnosticStepResponse` 建议暴露 `model_provider_name: string`、`is_mock_provider: boolean` 与 `execution_mode: "mock" | "live"`，以便前端在未启用远程大模型时明确展示 `Demo / Mock Mode` 徽章，绝不把 `FakeModelProvider` 伪装成真实 AI 推理。

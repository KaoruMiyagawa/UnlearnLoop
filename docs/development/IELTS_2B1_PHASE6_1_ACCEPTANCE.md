# IELTS-2B.1 Phase 6.1 最终验收

## 结论

**PASS WITH LIMITATIONS**

本阶段已实现按不可变题组版本登记证据有效性、追溯迁移和复习依赖、校正当前学习状态、阻止失效版本继续产生有效能力证据，并提供重新验证入口。隔离 SQLite、真实 Uvicorn/FastAPI、自动化测试和 Headless Chrome 验收均已执行。

本结论仅覆盖本地代码和隔离数据。按本阶段限制，没有对正式数据库执行 apply，因此不能声称任何正式用户历史记录已在正式库中完成校正。

## 已识别的问题范围

根据 Phase 6 内容审核记录，登记簿针对八组已确认存在答案依据错误或重大误导的 Matching Headings 迁移/复习材料。每条登记均精确限定 `group_id + content_version + rules_version`：

- v1 / rules v1：`invalidated`。
- 对应修订版本 v2 / rules v2：`eligible`，但只有正常的新作答才会产生能力证据。
- 未登记的新版本、缺少固定题组引用或无法唯一匹配的来源不会按日期或题目 ID 猜测；当前处理为 `review_required` 或保持非有效能力状态。

八组 ID 为：

| 考试模式 | 错误方向 | 迁移组 | 复习组 |
| --- | --- | --- | --- |
| Academic | 主旨与细节 | `ielts-mh-academic-main-transfer-group` | `ielts-mh-academic-main-review-group` |
| Academic | 关键词表面匹配 | `ielts-mh-academic-keyword-transfer-group` | `ielts-mh-academic-keyword-review-group` |
| General Training | 主旨与细节 | `ielts-mh-gt-main-transfer-group` | `ielts-mh-gt-main-review-group` |
| General Training | 关键词表面匹配 | `ielts-mh-gt-keyword-transfer-group` | `ielts-mh-gt-keyword-review-group` |

登记簿在 [matching_headings_evidence_validity_registry.json](../../backend/app/content/matching_headings_evidence_validity_registry.json)，记录了审核来源、理由及替代内容版本。运行时只按内容组、内容版本和答案规则版本精确匹配。

## 有效性与状态协调

- 历史 `Attempt`、评分快照、`ReviewItem`、`EvidenceLink` 和既有 `DecisionEvent` 均保留原值，不把新评分覆盖到旧记录。
- 新增 append-only `EvidenceValidityEvent` 台账。状态支持 `eligible`、`invalidated`、`review_required`；SQLite 触发器拒绝更新或删除已写入的审计事件。
- 迁移 Attempt 失效时，向下追踪其诊断证据、复习结果和知识状态。若没有其他独立且有效的迁移，当前 `KnowledgeState` 降为 `insufficient_evidence`，并明确说明这不是对学习者能力的负面判断。
- 若仍有另一条独立有效迁移，保留 `transfer_verified`。历史状态决策不会删除；协调结果写入新的审计事件。
- 原始复习记录仍可能保留历史字段 `retention_verified=true`，但服务端响应会按当前来源有效性返回 `retention_verified=false`、`retention_eligible=false`。这表达“当时曾记录通过”与“目前可作为保持证据”之间的区别。
- 新的初始作答、诊断证据、历史、个人档案、仪表盘和复习接口均解析登记簿/台账有效性。失效版本不能继续开始复习或被当作有效迁移证据。
- 对失效状态提供幂等的重新验证 API。它只能派发登记为 eligible 的正常题目版本；本阶段不会自动授予迁移或保持通过。

增量迁移为 `0007_evidence_validity_events`，从 `0006_matching_headings_review_provenance` 升级，Alembic 当前只有一个 head。既有 `0001` 至 `0006` 文件未修改。

## 隔离数据库执行证据

可重复运行脚本：

- `backend/scripts/reconcile_matching_headings_evidence.py`：默认 dry-run；apply 需要确认参数、隔离数据库路径、迁移 head 校验、唯一备份和 SQLite 写锁。
- `backend/scripts/verify_phase6_1_history_http.py`：构造原创隔离历史记录，运行 CLI dry-run/apply，再启动真实 Uvicorn/FastAPI 并请求读取与重新验证端点。

本轮真实 HTTP 记录保存于 [real-http-reconciliation.json](ielts-2b1-phase6-1-evidence/real-http-reconciliation.json)。记录中的隔离数据变化：

| 记录 | Apply 前 | Apply 后 | 是否改写历史原始记录 |
| --- | --- | --- | --- |
| 当前知识状态 | `transfer_verified` | `insufficient_evidence` | 状态协调写入新状态及审计事件 |
| v1 迁移 Attempt | 曾评分通过 | 当前有效性 `invalidated` | 否，原始 `is_correct=true` 保留 |
| v1 复习 Attempt / ReviewItem | 曾评分通过、历史保持字段为真 | 当前有效性 `invalidated`，API 不再返回有效保持验证 | 否，原始历史值保留 |
| 诊断 EvidenceLink | 曾支持假设 | 当前有效性 `invalidated` | 否，关系与内容保留 |
| v2 修订内容 | 无历史作答 | `eligible` | 未生成通过证据 |

同一隔离运行验证 dry-run 前后数据库 SHA-256 不变；apply 前备份哈希与程序报告一致，备份和 apply 后数据库 `PRAGMA integrity_check` 均为 `ok`。两个并发 apply 与后续重放均幂等，没有重复状态协调事件。隔离 HTTP 调用中，health、history、knowledge states、dashboard、review、diagnostic evidence 和重新验证/重放均返回 HTTP 200；重放返回同一重新验证会话 ID。

**正式 SQLite 未被迁移或写入。** 运行前后正式库 SHA-256 均为 `BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0`。

## 浏览器验收

使用 Headless Chrome、隔离 FastAPI/SQLite，覆盖档案中的失效提示、重新验证入口、历史复习提示以及 Premium / Noir 两主题。1440×1000 桌面和 390×844 手机视口均无横向溢出，浏览器控制台无错误。截图位于 [browser](ielts-2b1-phase6-1-evidence/browser/)：

- `profile-premium-desktop.png`
- `profile-noir-mobile.png`
- `invalid-review-premium-desktop.png`
- `invalid-review-noir-mobile.png`
- `browser-evidence.json`

浏览器实际验证了重新验证入口可创建并恢复修订版题目会话；相同幂等请求回到同一会话。此流程没有提交新的作答，因此没有伪造新的迁移或保持通过。

## 质量门禁

- 后端完整 `pytest`：通过；包括历史版本、依赖传播、幂等、隔离迁移和旧流程回归。
- 前端 `node --test tests/*.test.mjs`：48 项通过。
- TypeScript `npm run typecheck`：通过。
- Production build `npm run build`：通过。
- Alembic heads：唯一 head `0007_evidence_validity_events`。
- `git diff --check`：通过。
- Headless Chrome 隔离浏览器验收：通过。
- FastAPI/SQLite 真实 HTTP 协调记录：通过。
- SQLite 旧 Python 和 TFNG 历史兼容测试：完整后端回归通过；Phase 6.1 没有改变其 `stable` 语义。

## 限制与风险

1. apply 仅在本阶段的隔离 SQLite 中实际执行。正式库中的用户记录尚未扫描、核对或校正；部署时必须先备份，并由授权流程生成正式库 dry-run 清单后再单独审批 apply。
2. 登记簿覆盖上述精确版本元组，不按题目 ID、日期或题型推测。缺乏可靠版本来源的旧记录只能标记待复核，不应声称已确认失效。
3. v2 被登记为可用于未来作答，不代表材料已获外部专家认证，也不等于任何学习者已通过该版本。
4. learner_id 仍是本地开发接口的隔离参数，不构成生产级多用户认证。
5. 本地 Headless Chrome 已验证桌面和窄屏；未执行 Safari 或实体手机测试。

## Git 与保护状态

- 分支：`feat/ielts-2b-reading-question-groups`
- HEAD：`f855ef19e351a683c1d7067a2a64dd3ca349a0b1`
- 未 Commit、未 Push。
- Phase 4–6 的既有未提交工作与两份目录清理审计文档仍保留。
- 正式 SQLite、旧目录、main 和 README PR #1 未操作。

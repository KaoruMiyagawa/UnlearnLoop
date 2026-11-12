# VerbaTrail IELTS-2B.1 Phase 6.2 最终复验

日期：2026-11-12
分支：`feat/ielts-2b-reading-question-groups`
提交基线：`f855ef19e351a683c1d7067a2a64dd3ca349a0b1`
本轮结论：**PASS WITH LIMITATIONS**

本报告记录 Phase 6.2 新执行的综合复验。Phase 6 原始 FAIL 结论作为历史保留于 [IELTS_2B1_FINAL_ACCEPTANCE.md](IELTS_2B1_FINAL_ACCEPTANCE.md)；Phase 6.1 及本轮补充了代码层证据有效性治理和复验。工程复验通过不构成生产发布许可。

## 1. 工作区与保护

开始时分支、HEAD 与用户给定值一致。Phase 4–6 的未提交实现、产品文档变更及以下两份用户审计文档均保留：

- `docs/development/CONSOLIDATION_REPORT.md`
- `docs/development/OLD_DIRECTORIES_CLEANUP_CHECKLIST.md`

未切换分支，未 Commit、Push、Merge、Reset、Clean 或 Rebase；未操作旧目录、main、PR #1 或付费模型。

## 2. 本轮完整闭环复验

### 真实 HTTP / SQLite

本轮重新启动隔离 SQLite 与真实 Uvicorn/FastAPI，不复用先前的 HTTP 响应。所有资料均由原创测试内容和 Fake/rules 执行产生，远程模型调用关闭。

证据目录：[ielts-2b1-phase6-2-evidence](ielts-2b1-phase6-2-evidence/)

- `ag-transfer-review-http.json`：146 次真实 HTTP 请求，Academic / General Training 的主旨与细节、关键词匹配路径；迁移及到期复习成功/失败；迁移题耗尽；未到期复习拒绝；并发派题、复习开始和幂等重放；TFNG 与 Python 旧流程。
- `matching-diagnostics-http.json`：130 次真实 HTTP 请求，诊断候选、追问、证据支持/削弱、训练分流及规则拒绝。
- `matching-scoring-http.json`：88 次真实 HTTP 请求，逐项评分、部分得分、非法作答、版本固定与幂等。
- `history-reconciliation-http.json`：真实 HTTP 下的 dry-run、apply、并发 apply、历史/档案/复习/诊断证据读取及重新验证重放。

关键结果：

| 场景 | 本轮观察 |
| --- | --- |
| 无独立 v1 以外迁移证据 | 当前状态从 `transfer_verified` 校正为 `insufficient_evidence`；历史 attempt 保留原 `is_correct=true`。 |
| v1 与 v2 迁移历史并存 | v1 被标为 `invalidated`，v2 保持 `eligible`；状态仍为 `transfer_verified`，依据指针改为独立 v2 attempt。 |
| 依赖失效迁移的历史复习 | 原始 ReviewItem 与 Attempt 的历史通过字段不改写；API 返回该项目无当前有效保持验证。 |
| 重新验证 | 只派发经登记可用的 v2 正常学习题；不会自动产生迁移或保持成功。相同幂等键重放返回同一 session。 |
| 未知来源 | 精确版本无法对应时进入 `review_required`，不归因于学习者能力。 |
| 旧流程 | TFNG 与 Python 路径继续按各自原有语义运行。 |

重放协调没有增加重复审计事件。历史 DecisionEvent、EvidenceLink、Attempt 和 ReviewItem 均保留；新的有效性和协调结论写入 append-only 审计记录。原始 ReviewItem 上历史字段仍为真，读取 API 根据有效性返回 `retention_verified=false`、`retention_eligible=false`，保留历史事实与当前证据效力的区别。历史协调 HTTP 记录中的 9 个端点均返回 200，重新验证同键重放返回相同 session ID。

### 正式数据库只读风险盘点

没有启动正式数据库对应的应用，也没有迁移或 apply。脚本 `backend/scripts/audit_phase6_2_formal_db_readonly.py` 检查不存在 `-wal` / `-shm` sidecar 后，通过 SQLite `immutable=1` 打开源文件，只读复制到临时目录，再对副本执行完整性与聚合扫描；不导出学习者 ID。

扫描证据：[formal-db-readonly-scan.json](ielts-2b1-phase6-2-evidence/formal-db-readonly-scan.json)

- 源库前后 SHA-256 相同：`BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0`。
- 副本 `PRAGMA integrity_check`：`ok`。
- 源库 Alembic 版本：`0002_stage3_model_calls`；题目 23 条。
- 扫描到 Matching Headings 题目、相关 Attempt、ReviewItem、KnowledgeState、EvidenceLink、未知版本：均为 0。
- 涉及学习者：0；需重新验证的项目：0；拟协调操作：0。

该结果仅覆盖此本地 SQLite 文件；不能据此推断其他设备、部署或已归档数据库中不存在记录。正式库未运行迁移，也未执行协调。

### 浏览器

- [Matching Headings 完整旅程截图与证据](ielts-2b1-phase6-2-evidence/browser-matching-headings/)：Headless Chrome 通过 13 个场景，生成 19 张截图，执行 568 次浏览器 API 请求；覆盖 A/G、初始作答、评分、Error DNA、训练、迁移、复习、双主题、草稿/刷新/离线/超时、TFNG 及键盘/窄屏操作。
- [历史失效与重新验证截图](ielts-2b1-phase6-2-evidence/browser-history-validity/)：隔离 Uvicorn + SQLite + Chrome；Premium/Noir、1440×1000 / 390×844；显示失效历史、重新验证入口与历史复习提示；浏览器错误为 0，无横向溢出。
- 未测试 Safari 或实体手机。

## 3. 本轮质量门禁

以下检查均在本轮重新运行：

- 后端完整 pytest：**166 项收集，全部通过**。
- 前端 `node --test tests/*.test.mjs`：**48 项通过**。
- `npm run typecheck`：通过。
- `npm run build`：通过；其 `tsc -b` 包含 Vite 配置工程，再完成 Vite production build。
- `python -m compileall -q app scripts`：通过。
- Alembic：唯一 head 为 `0007_evidence_validity_events`。
- 空 SQLite 升级到 head：完整后端测试的隔离 DB fixture 通过。
- 旧版升级：`0004_ielts_exam_profiles` → `0007` 的迁移兼容测试通过，旧 Python 与 TFNG 历史可读取。
- `git diff --check`：通过；仅 Git 报告现有文件的 LF/CRLF 转换提示。
- A/G HTTP、证据协调 HTTP、两个浏览器脚本：通过。

没有单独安装或配置 Python mypy/pyright；Python 侧使用完整 pytest 和 compileall 验证。

## 4. 产品与发布边界

| 方面 | 当前结论 |
| --- | --- |
| 功能工程验收 | Phase 1–6.2 的本地隔离回归通过，历史 v1/v2 混合证据状态通过 HTTP 验证。 |
| 历史数据治理 | 已对本机 `backend/unlearnloop.db` 完成只读扫描，发现 0 条相关记录；未对任何正式用户库执行 apply。其他数据库需单独扫描和审批。 |
| 内容审校 | Phase 6 的内部审核和修订登记已保留；没有独立 IELTS 专家/外部编辑认证。 |
| AI Agent | 本轮使用规则执行与 FakeModelProvider 测试，不证明真实 LLM 的语义诊断或教学能力。 |
| 长期复习 | 验证到首轮延迟复习闭环；多轮、跨周期长期保持仍不充分。 |
| 浏览器与设备 | Headless Chrome 的桌面和手机视口通过；Safari、真机未执行。 |
| 生产发布 | **未通过生产发布评估**：无正式数据协调、生产级身份认证/权限审计、部署演练、备份恢复演练和运营监控验收。 |

因此最终工程结论为 **PASS WITH LIMITATIONS**，并不意味着可以发布到生产环境，也不意味着 IELTS 学习内容已获外部认证。

## 5. 后续事项

1. 对每个实际部署数据库生成只读副本和逐库影响清单，确认备份可恢复后，另行审批 apply。
2. 对未登记或缺少题组版本快照的历史资料进行人工来源审核，保持 `review_required`，直到证据充分。
3. 安排独立 IELTS 编辑审校修订版文章、标题、干扰项和解释。
4. 增加多轮间隔复习与长期留存评估，再讨论更广泛的能力结论。
5. 执行 Safari 和实体移动设备验收。

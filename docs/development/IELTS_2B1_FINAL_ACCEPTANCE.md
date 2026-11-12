# IELTS-2B.1 综合验收报告

> **Phase 6.2 最终复验已于 2026-11-12 完成：PASS WITH LIMITATIONS。** 原 Phase 6 的 FAIL 记录保留在下文，作为当时验收事实；Phase 6.1/6.2 补上了证据有效性登记、状态协调及本轮隔离复验。该工程结论不等于生产发布许可。完整的新复验报告见 [IELTS_2B1_PHASE6_2_ACCEPTANCE.md](IELTS_2B1_PHASE6_2_ACCEPTANCE.md)，本轮 HTTP、SQLite 与浏览器证据见 [Phase 6.2 证据目录](ielts-2b1-phase6-2-evidence/)。

日期 2026-11-12。分支 `feat/ielts-2b-reading-question-groups`，HEAD `ce5f97148685c6856d93acb5e141ff774a6144c3`。**最终结论：FAIL。**

新发布的题库版本、后端学习闭环和前端操作已通过本轮隔离验收。阻断项是已存在的旧版迁移或复习作答及其知识状态可能源自不可靠的答案键。保留不可变历史后，当前历史及知识状态 API 还没有标记这类既有证据的有效性，也没有重新评估机制，因此不能确认所有既有学习状态准确。

## 阶段矩阵

| 阶段 | 实际实现及本轮结果 |
| --- | --- |
| 1 | ReadingGroupVersion、Question 关联、会话固定版本和 Attempt 快照已实现。隔离迁移及不可变测试通过。 |
| 2 | Academic / GT 初始题组、结构化提交、逐项评分、API 脱敏和幂等恢复已实现。本轮独立 HTTP 评分脚本通过。 |
| 3 | 两种错误原因的候选假设、追问、证据与对应训练已实现。本轮独立 HTTP 诊断脚本通过。 |
| 4 | 独立迁移与首轮延迟复习已实现。旧版迁移/复习题内容存在评分缺陷；本轮发布版本 2 并阻止对受影响版本 1 创建新的迁移及保持证据。既有证据仍需处理。 |
| 5 | React 学习、诊断、训练、迁移和复习页面使用服务端题组。本轮 Chrome 浏览器重新通过 13 个场景。 |
| 6 | 完成内部工程、数据契约、内容和安全审查，修正题库并补充迁移、历史字段、旧版评分和会话恢复回归。既有旧版证据的可信度处理未完成。 |

## 完整闭环

隔离 Uvicorn、FastAPI 和 SQLite 真实 HTTP 本轮执行 146 次请求。Academic 和 GT 的主旨/细节及表面关键词两种路径各有从初始错误、追问、训练到独立迁移及到期复习成功的完整记录。失败路径也验证了 Academic 迁移失败和 GT 延迟复习失败。机器可读的请求、响应、各阶段状态和数据库记录见 [HTTP 最终证据](ielts-2b1-phase6-evidence/http-final.json)。

| 模式与错误路径 | 迁移 Attempt | 延迟复习 Attempt | 结果 |
| --- | --- | --- | --- |
| Academic 主旨/细节 | `att_d206879f86e041c9` | `att_845e3ff7a4c54c06` | 迁移及到期复习通过 |
| Academic 关键词 | `att_4d50aed499a74618` | `att_18c52e8b6f99469f` | 迁移及到期复习通过 |
| GT 主旨/细节 | `att_60bb3df387bf43d1` | `att_3f63aaccfa1a4215` | 迁移及到期复习通过 |
| GT 关键词 | `att_35745dfe06734d69` | `att_a2fda786b1544b1b` | 迁移及到期复习通过 |

评分脚本覆盖 1/3、2/3、3/3、非法作答、考试模式、同键不同载荷和版本固定，见 [评分 HTTP 证据](ielts-2b1-phase6-evidence/scoring-after.json)。诊断脚本覆盖四条考试模式及错误路径、重复映射、支持和削弱证据、内容耗尽与协议拒绝，见 [诊断 HTTP 证据](ielts-2b1-phase6-evidence/diagnostics-after.json)。训练正确保持待迁移，整组迁移成功进入 `transfer_verified`，到期独立复习成功才记录该 ReviewItem 的 `retention_verified`。失败和题库耗尽均没有创建成功证据。Python 的原有 `stable` 流程及 TFNG 规则通过完整回归。

诊断执行来源为本地规则与测试用 FakeModelProvider。本轮没有验证真实 LLM 语义推理。

## 内容审核与修复

审核 Academic 和 GT 初始、追问、训练、迁移和复习材料的题项、标题、答案与解释。发现 Phase 4 的 8 套迁移/复习题中，多项已标答案仅覆盖细节，部分甚至与原文矛盾。例如 Academic `ielts-mh-academic-main-transfer` 第二段讲比较读数及校准，版本 1 的答案却称雨损坏了设备；第三段讲路线与公共交通连接，答案却称公共建筑内的标识。此前测试用题库自身答案键驱动作答，因此流程通过不能证明题目的语义正确性。修复前记录保存在 [旧版 HTTP 证据](ielts-2b1-phase6-evidence/http.json)。

修复将受影响的 8 套题组内容及规则升级到版本 2，替换不匹配的标题，并为 24 个迁移/复习题项补充原文依据。版本 1 仍可恢复和读取；对上述已知版本 1 的新迁移或复习提交采用安全拒绝，防止继续产生新的验证证据。`test_pre_correction_transfer_version_is_readable_but_cannot_create_mastery` 和 `test_pre_correction_review_version_cannot_create_retention_evidence` 分别验证两类旧版任务可读取、拒绝新提交且不晋升。版本 2 的题目映射和解释另有内容回归测试。

后续独立审校问题清单：

1. 核查所有版本 2 段落和标题是否存在同样合理的第二个答案，尤其 Academic 图书馆服务第二、三段及 GT 包裹领取第二段。
2. 检查干扰标题是否足以区分局部细节与主旨，而非仅凭明显矛盾即可排除。
3. 复核追问的选项与支持/削弱映射能否区分两种原因，以及单次结果是否足以支撑当前训练分流。
4. 独立审查文章语体、语言难度、题目解释与考试模式是否适合目标学习者，并检查不同轮复习的材料独立性。
5. 对所有已有版本 1 的迁移和复习结果设计可追溯的有效性标记、状态重算和用户恢复路径，保留原始 Attempt；评估是否需要隔离数据迁移。

以上是内部检查，内容尚未通过独立编辑或 IELTS 专家审校。当前每条路径只足以完成首轮延迟复习，后续轮次可能无独立题可派。

## 真实浏览器

本轮以隔离数据库、受控时钟和 Headless Chrome 连接真实服务。13 个场景包括 Academic / GT、正确和部分正确、诊断及训练、迁移成功、到期前与到期复习、复习失败、两类题库耗尽、双主题与草稿恢复、网络中断与超时、TFNG、键盘及触控模拟。新增回归在旧会话响应被延迟时确认任务目录受保护，再创建新会话并确认旧响应没有覆盖新会话。详见 [浏览器 HTTP 记录](ielts-2b1-phase6-evidence/browser-final/browser-http-evidence.json) 和 [SQLite 快照](ielts-2b1-phase6-evidence/browser-final/sqlite-evidence.json)。

| 主题 | 1440×1000 | 390×844 |
| --- | --- | --- |
| Premium Academic | [桌面](ielts-2b1-phase6-evidence/browser-final/I-premium-desktop.png) | [移动](ielts-2b1-phase6-evidence/browser-final/I-premium-mobile.png) |
| Noir & Champagne | [桌面](ielts-2b1-phase6-evidence/browser-final/I-noir-desktop.png) | [移动](ielts-2b1-phase6-evidence/browser-final/I-noir-mobile.png) |

另见 [部分正确](ielts-2b1-phase6-evidence/browser-final/B-academic-partial.png)、[Error DNA](ielts-2b1-phase6-evidence/browser-final/B-error-dna.png)、[复习通过](ielts-2b1-phase6-evidence/browser-final/E-academic-retention-pass.png)、[复习失败](ielts-2b1-phase6-evidence/browser-final/F-gt-retention-fail.png)、[迁移耗尽](ielts-2b1-phase6-evidence/browser-final/G-transfer-exhausted.png) 和 [复习耗尽](ielts-2b1-phase6-evidence/browser-final/H-review-exhausted.png)。桌面双栏、移动单栏、长标题换行、文章定位、键盘焦点及至少 44px 操作目标通过脚本检查；两个视口未出现页面横向溢出。深色主题阅读纸底 `#f7f4ea` 与正文 `#27383e` 的计算对比度约为 11.09:1。Safari 和实体移动设备未执行。

## 数据、安全与迁移

- 隔离 SQLite 测试从空库升级到 head，也从 `0004_ielts_exam_profiles` 分步升级到 `0005_reading_groups` 再到 `0006_matching_headings_review_provenance`，验证旧 Python、TFNG 会话和 Attempt 评价保留。旧 ReviewItem 可读取，新字段为可空。Alembic 只有一个 head。
- 测试覆盖内容版本不可变、派题及评分版本固定、无效版本拒绝、请求幂等及并发派题/提交。已派发的旧版本继续恢复，受缺陷影响的版本 1 新作答安全拒绝。
- 题目响应和历史 API 检查了答案键、解释及私有规则字段。历史响应使用 Pydantic 响应模型白名单；规则来源和题项观察为公开的已作答证据。
- `learner_id` 只是客户端可提供的筛选参数，不是身份认证。`GET /sessions/{id}`、`GET /attempts/{id}` 和诊断 ID 路由没有用户身份绑定，知道 ID 的调用方可访问对应记录。此边界只适合可信的单用户本地环境，不能宣称多用户认证或租户隔离。
- 正式数据库的 SHA-256 前后均为 `BC4656AA2BC624F0A257254BA25597DB3031126FDFCBE79E5F3BB0CB607793E0`。测试与浏览器使用临时数据库。

## 工程门禁

| 检查 | 本轮结果 |
| --- | --- |
| 后端完整 pytest | 159 passed，1 条 Starlette/httpx 弃用警告 |
| 前端完整测试 | 47 passed |
| TypeScript 应用与 Vite 配置类型检查 | 通过 |
| Production build | 通过 |
| Alembic 唯一 head | `0006_matching_headings_review_provenance` |
| `git diff --check` | 通过，Git 输出部分 LF/CRLF 转换提示 |
| 隔离真实 HTTP | 评分 88、诊断 130、完整闭环 146 条请求记录，均通过 |
| 隔离真实浏览器 | 13 场景、19 张截图。关闭浏览器后 Windows asyncio 输出一次连接重置日志，测试进程退出码为 0 |

本轮还修正了旧版 HTTP 证据脚本中版本字段误引用后续场景变量的问题。新 [HTTP 最终证据](ielts-2b1-phase6-evidence/http-final.json) 的固定版本字段来自 Academic 场景 A，实际旧证据中相关请求与响应仍可核查。

## 后续

先为历史版本 1 的迁移和保持证据建立可信度标记与状态重算方案，并补充自动恢复测试。随后进行独立题库审校、补足多个复习周期的独立文章，再以同一题组版本、作答快照、服务端评分和独立性规则扩展下一种阅读题型。多用户部署前需要身份认证、访问授权和按身份执行的对象隔离。

本轮保留 Phase 4、5 及两份清理审计文档的未提交修改，未提交或推送。

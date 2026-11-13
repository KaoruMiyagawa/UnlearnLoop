# IELTS-2B.1 Phase 5 验收

> Phase 6 内容复核发现旧版迁移和复习题的部分标题不符合段落主旨。本报告中的浏览器运行证明了前端闭环，题目内容已在 Phase 6 修订。详见[综合验收报告](IELTS_2B1_FINAL_ACCEPTANCE.md)。

2026-11-11 · **PASS** · `feat/ielts-2b-reading-question-groups` · 基线 `ce5f97148685c6856d93acb5e141ff774a6144c3`

## 前端与接口

`MatchingHeadingsQuestion` 使用服务端脱敏的 `group_display` 和固定的 `group_version_id`。学习工作区使用它完成初答、诊断追问和专项训练，迁移和复习工作区也使用同一组件。题组显示全文、段落编号、所有候选标题、已选标题和完成进度。原生选择控件支持键盘和触控，禁用已被其他段落使用的选项，并在必答项齐全后开放提交。

学习入口根据 `GET /topics` 的 `initial_question_types` 识别题组，通过会话接口请求 `question_type=matching_headings`。题组请求沿用既有作答接口，发送 `question_id`、`group_version_id`、`structured_answer` 和 `idempotency_key`。草稿以会话、题目和固定版本保存于当前浏览器会话。超时或断网时保留冻结的请求，恢复时使用原幂等键或读取已持久化的结果。

结果组件显示服务端逐项评分、部分正确状态和评分记录。Error DNA 展示竞争假设及支持、削弱和中性证据，题项 ID、所选标题、作答和题组及规则版本默认折叠。复习响应附带固定题组和已保存的评分，并反映服务端判定的题库耗尽状态。Phase 5 未增加数据库迁移。

## 浏览器验收

验收使用 Headless Chrome、Vite、真实 Uvicorn + FastAPI 和临时 SQLite。到期场景通过注入时钟推进；断网和响应丢失通过 Chrome DevTools Protocol 复现。规则模式使用隔离测试配置，远程模型调用关闭。

| 场景 | 结果 | 截图 |
| --- | --- | --- |
| A · Academic 正确 | 3/3；Attempt `att_e19552945a03444b` | [全部正确](ielts-2b1-phase5-browser-evidence/A-academic-correct.png) |
| B · Academic 部分正确 | 2/3；Attempt `att_ced60fa529b645ee`；进入规则诊断，证据可展开 | [评分](ielts-2b1-phase5-browser-evidence/B-academic-partial.png) · [Error DNA](ielts-2b1-phase5-browser-evidence/B-error-dna.png) |
| C · GT 错答与训练 | 初答全错，完成区分性追问，派发并通过 `ielts-mh-gt-main-practice` | [训练作答](ielts-2b1-phase5-browser-evidence/C-gt-structured-practice.png) · [训练通过](ielts-2b1-phase5-browser-evidence/C-gt-targeted-training.png) |
| D · Academic 独立迁移 | `transfer_verified`，服务端已安排尚未到期的复习 | [迁移评分与计划](ielts-2b1-phase5-browser-evidence/D-academic-transfer-not-due.png) |
| E · Academic 复习成功 | 刷新恢复结构化草稿；ReviewItem `rev_9ea5378fea8b43f0` 为 `passed_delayed`，该次 `retention_verified=true` | [复习草稿](ielts-2b1-phase5-browser-evidence/E-review-draft-restored.png) · [保持证据](ielts-2b1-phase5-browser-evidence/E-academic-retention-pass.png) |
| F · GT 复习失败 | ReviewItem `rev_69ffecba60a14f3b` 为 `failed`，该次保持未验证，知识状态回到 `needs_practice` | [复习失败](ielts-2b1-phase5-browser-evidence/F-gt-retention-fail.png) |
| G · 迁移池耗尽 | 刷新后仍显示不可派题原因，服务端 `can_dispatch_transfer=false` | [迁移耗尽](ielts-2b1-phase5-browser-evidence/G-transfer-exhausted.png) |
| H · 复习池耗尽 | 到期任务保留待办，没有 Attempt 和保持证据，刷新后仍显示原因 | [复习耗尽](ielts-2b1-phase5-browser-evidence/H-review-exhausted.png) |
| I · 主题与草稿 | 两主题切换及刷新后保留同一题组草稿 | Premium [桌面](ielts-2b1-phase5-browser-evidence/I-premium-desktop.png) · [移动](ielts-2b1-phase5-browser-evidence/I-premium-mobile.png)；Noir [桌面](ielts-2b1-phase5-browser-evidence/I-noir-desktop.png) · [移动](ielts-2b1-phase5-browser-evidence/I-noir-mobile.png) |
| J · 断网与超时 | 断网后原请求及幂等键重试成功；截留已提交的 HTTP 201 响应后，刷新读取原 Attempt。两种情况下各只产生一条作答 | [断网](ielts-2b1-phase5-browser-evidence/J-offline.png) · [超时](ielts-2b1-phase5-browser-evidence/J-timeout.png) |
| K · TFNG | 旧题渲染文本框，服务端保存 `submitted_answer` | [TFNG 作答](ielts-2b1-phase5-browser-evidence/K-tfng-regression.png) |
| L · 移动与键盘 | 在 390×844 使用键盘选完三段，Tab 移到提交并用空格触发；验证焦点可见、触控跳转原文、44px 控件和无横向溢出 | [移动作答](ielts-2b1-phase5-browser-evidence/L-mobile-answer.png) |

[浏览器 HTTP 记录和断言](ielts-2b1-phase5-browser-evidence/browser-http-evidence.json)包含 550 个浏览器 API 请求记录（含导航取消与故障注入）、19 张截图的视口数据，以及关键服务端响应。[SQLite 证据](ielts-2b1-phase5-browser-evidence/sqlite-evidence.json)包含 15 条 Attempt 和相关会话、诊断、知识状态和复习记录。正式 SQLite 的 SHA-256 在验收前后相同。

## 工程门禁

- 后端 pytest 155 项通过，含 Phase 1–4 回归。Starlette TestClient 发出一条 httpx 弃用警告。
- 前端 `node --test tests/*.test.mjs` 47 项通过。
- `npm run typecheck`、`tsc -p tsconfig.app.json --noEmit`、`tsc -p tsconfig.node.json --noEmit`、`npm run build` 通过。
- Alembic 唯一 head 为 `0006_matching_headings_review_provenance`。
- `git diff --check` 通过。

浏览器验收可在后端目录运行，脚本会启动独立端口和临时库。

```powershell
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe scripts/verify_matching_headings_browser.py
```

本轮的移动结果来自 Chrome 的视口与触控模拟，尚未覆盖实体手机或 Safari。首轮延迟复习可完成，后续间隔轮次受 Phase 4 独立材料数量限制。题库的独立编辑复核仍待完成。

## Phase 5 文件

- 题组与评分组件 [MatchingHeadingsQuestion.tsx](../../frontend/src/learning-workspace/MatchingHeadingsQuestion.tsx)、[matchingHeadings.ts](../../frontend/src/learning-workspace/matchingHeadings.ts)、[matchingHeadings.css](../../frontend/src/learning-workspace/matchingHeadings.css)。
- 学习与复习 [RealLearningWorkspace.tsx](../../frontend/src/learning-workspace/RealLearningWorkspace.tsx)、[FocusReviewWorkspace.tsx](../../frontend/src/review-workspace/FocusReviewWorkspace.tsx)、[learningFlow.ts](../../frontend/src/learning-workspace/learningFlow.ts)、[transferFlow.ts](../../frontend/src/learning-workspace/transferFlow.ts)。
- 诊断呈现 [ErrorDnaPanel.tsx](../../frontend/src/learning-workspace/ErrorDnaPanel.tsx)、[errorDna.ts](../../frontend/src/learning-workspace/errorDna.ts)、[diagnosticFlow.ts](../../frontend/src/learning-workspace/diagnosticFlow.ts)。
- API 合同与派题呈现 [types.ts](../../frontend/src/api/types.ts)、[sessions.ts](../../frontend/src/api/sessions.ts)、[schemas.py](../../backend/app/api/v1/schemas.py)、[learning_service.py](../../backend/app/application/learning_service.py)。
- 自动化 [matching-headings.test.mjs](../../frontend/tests/matching-headings.test.mjs)、[verify-matching-headings-browser.mjs](../../frontend/scripts/verify-matching-headings-browser.mjs)、[verify_matching_headings_browser.py](../../backend/scripts/verify_matching_headings_browser.py)。

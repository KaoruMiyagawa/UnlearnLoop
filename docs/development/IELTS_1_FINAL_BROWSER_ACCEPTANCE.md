# IELTS-1 最终浏览器验收报告

日期：2026-11-09（Asia/Shanghai）

工作区：`D:\Projects\UnlearnLoop-ielts`，分支 `feat/ielts-pivot`

## 结论与范围

**建议将 IELTS-1 本轮所列浏览器验收升级为 PASS。** 这是对下述隔离环境和实际操作范围的结论，不是生产发布、真实模型质量、多用户安全或完整可访问性验收。没有发现本轮范围内仍未修复的阻断性问题。

**建议提交：是**，但应先由维护者审阅全部既有未提交改动、验收证据与本轮修复；本轮未提交。**建议合并到主项目：暂不建议立即合并**，先审阅完整 IELTS 差异，并明确处理或接受原 MVP 审查中的迁移备份、数据控制、安全及依赖等遗留风险；本轮未重新审计或宣称解决这些问题。

## 环境与证据

- 真实 Headless Chrome 156.0.8078.80，通过 Chrome DevTools Protocol 控制实际浏览器；脚本在页面 DOM 上触发点击与输入，非人工鼠标及实体设备测试。浏览器视口包括 1440×1000 与 390×844。截图和状态记录见 [验收证据目录](ielts-1-browser-evidence/) 和 [浏览器观测记录](ielts-1-browser-evidence/browser-observations.json)。记录中的后端数据仅作为浏览器操作结果的辅助证据。
- 隔离前端 `127.0.0.1:18732`、后端 `127.0.0.1:18731`、Chrome 调试端口 `18733`；新建临时 SQLite `D:\Temp\unlearnloop-ielts-acceptance-20261109.sqlite`。后端 `MODEL_PROVIDER=fake`、`ALLOW_REMOTE_MODEL_CALLS=false`；没有使用或清空既有数据库，也没有改变其他运行中的服务。
- Academic 会话 `sess_89b63d7209414bd4`；General Training 会话 `sess_b10a1cf1b815476b`。浏览器记录两者均包含 initial、diagnostic_followup、targeted_practice、transfer_check 作答；浏览器未捕获到未处理的运行时异常。该记录并不等于完整控制台或网络日志。
- 首次组合启动命令被执行环境自动策略拒绝，未启动进程；随后分别以前台隔离进程成功启动，无须更改策略。

## 逐场景结果

| 场景 | 实际操作及预期 | 实际结果 | 状态与证据 |
| --- | --- | --- | --- |
| Academic 设置与目标 | 选择 Academic，将目标总分从 8.0 改为 7.5，刷新后检查；预期选择与目标持久保存 | Academic 被选中；稍后刷新及切换考试类型后目标仍为 7.5 | **PASS**：[设置](ielts-1-browser-evidence/02-academic-settings.png)、[刷新后记录](ielts-1-browser-evidence/browser-observations.json) |
| Academic 阅读闭环 | 选择 Academic English Reading、开始阅读、展开文章；初题选错 A，执行诊断，追问答 A，再执行诊断，练习答 B，进入独立迁移并答 B；预期按服务端状态推进并显示结果 | 显示文章、错误反馈、离线模拟诊断和追问；练习后派发新情境迁移题，迁移通过，明确提示长期保持尚未验证 | **PASS**：[文章](ielts-1-browser-evidence/05-passage.png)、[追问](ielts-1-browser-evidence/06-followup.png)、[练习](ielts-1-browser-evidence/07-mobile-practice.png)、[迁移结果](ielts-1-browser-evidence/09-transfer-result.png)、[作答记录](ielts-1-browser-evidence/browser-observations.json) |
| 学习历史及待复习 | 结束 Academic 会话，打开学习档案和复习中心；预期看到学习事件与已安排任务 | 历史显示初答、诊断、追问、练习、迁移和安排复习；复习中心显示 Academic 一项且尚未到期 | **PASS**（展示范围）：[档案](ielts-1-browser-evidence/10-profile.png)、[复习](ielts-1-browser-evidence/11-review.png) |
| 刷新恢复 | Academic 针对性练习尚未作答时刷新；预期回到同一会话和题目 | 会话 ID 仍为 `sess_89b63d7209414bd4`，原针对性练习重新显示，可继续提交 | **PASS**：[恢复后的练习](ielts-1-browser-evidence/07-mobile-practice.png)、[作答记录](ielts-1-browser-evidence/browser-observations.json) |
| General Training 独立学习 | 首页选择 General Training；选择其他阅读任务，选择 GT English Reading；初答 A、追问 A、练习 A、迁移 A；预期加载独立内容和会话 | 显示图书馆、志愿者、课程等文章，另建 `sess_b10a1cf1b815476b`，独立迁移通过 | **PASS**：[任务](ielts-1-browser-evidence/13-gt-task-list.png)、[文章](ielts-1-browser-evidence/14-gt-reading-mobile.png)、[追问](ielts-1-browser-evidence/15-gt-followup.png)、[迁移](ielts-1-browser-evidence/16-gt-transfer.png) |
| 跨考试模式恢复 Academic 历史 | 保持 GT 设置，在学习页选择其他阅读任务，展开历史并打开 Academic 已完成会话；预期原会话仍可恢复 | 历史同时列出两个模式；打开后恢复原 Academic ID、完成状态和评价 | **PASS**：[历史列表](ielts-1-browser-evidence/18-history-in-gt.png)、[恢复结果](ielts-1-browser-evidence/19-academic-restored.png) |
| Demo/Real 切换及数据隔离 | 在 Real 迁移结果切到 Demo，操作演示迁移题切换，再切回 Real；比较操作前后服务端会话与作答快照 | 演示内容显示 Python 示例；所测演示操作前后会话及作答快照相同，返回 Real 保留 GT 结果。此结论仅覆盖该演示操作 | **PASS**（所测操作）：[演示](ielts-1-browser-evidence/17-demo.png)、[快照比较](ielts-1-browser-evidence/browser-observations.json) |
| 390px 窄屏 | 设置 390×844，检查导航、GT 文章及 Academic 答题/迁移区域；预期可阅读、可操作且无整页横向溢出 | 测得视口及页面宽均为 390px；答题文本框宽 320px，位于视口内；可见导航、文章和题目 | **PASS**（所测页面）：[文章与导航](ielts-1-browser-evidence/14-gt-reading-mobile.png)、[答题](ielts-1-browser-evidence/07-mobile-practice.png)、[迁移](ielts-1-browser-evidence/08-transfer-mobile.png) |

## 本轮发现与修复

- 开发环境首页初始加载时，React 重新挂载导致旧请求被取消，旧请求的错误处理仍写入 `REQUEST_ABORTED`，即使新请求最终成功仍误显示错误。修复前证据：[截图](ielts-1-browser-evidence/01-home-aborted-error.png)。
- 在 `frontend/src/home/IeltsHome.tsx` 中仅对未取消的请求更新加载结果、错误和加载状态。重新加载后不再显示该误报，目标和模式正常恢复：[修复后截图](ielts-1-browser-evidence/20-home-after-fix.png)。这次复测针对开发服务器中观察到的触发条件，不代表穷尽所有网络竞争情况。
- 切换到 GT 后进入学习页会先恢复已有 Academic 活动指针，需要点击“选择其他阅读任务”才能新建 GT 会话；历史会话保持可访问。本轮未把此交互视为阻断，但可能让用户误以为考试类型没有切换。

## 回归检查

- 后端完整 `pytest -q`：80 项通过；1 条 Starlette/httpx 弃用警告。
- 前端 `node --test tests/*.test.mjs`：40 项通过。
- `npm run typecheck`、`npm run build`：通过；`git diff --check` 通过，Git 提示已有 CSS 文件下次触及时可能转换 LF 为 CRLF。

## 未验证功能与已知限制

- FakeModelProvider 为离线模拟：本轮验证了模拟流程和界面标识，**没有验证真实 AI 个性化诊断、DeepSeek 调用、质量、费用或网络行为**。规则评价的正确结果也不是对个性化诊断质量的证明。
- 已安排复习尚未到期；没有等待到期、完成真实延迟复习作答或验证长期保持。
- 未验证真实手机、其他浏览器、读屏器、完整键盘操作、对比度、离线重试或高并发。截图及 DOM 测量仅覆盖列出的视口和界面。
- 上一份 [MVP 审查](MVP_FINAL_AUDIT.md) 的迁移前备份恢复、数据导出删除、本机信任边界、依赖风险等问题不因本轮浏览器通过而消失；没有对其作新的完整安全审计。
- 验收开始时工作区已有大量未提交和未跟踪 IELTS 成果及规划、基线文件，均予保留。本轮新增本报告和截图/观测记录，并局部修复首页；未执行 commit、push 或 merge。

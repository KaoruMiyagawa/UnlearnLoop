# Learn V1.1 浏览器验收

2026-11-13，基于 `1de58e4f73927212da096cf671898c1cba59c132` 的 `feat/learn-four-skills-v1` 工作区修改。截图由 Headless Chrome 捕获，使用本地 Vite、真实 FastAPI HTTP 和临时 SQLite。诊断使用规则及 FakeModelProvider。

| 主题 | Learn 1440 × 1000 | Learn 390 × 844 | Reading 1440 × 1000 | Reading 390 × 844 |
| --- | --- | --- | --- | --- |
| Premium Academic | [桌面](learn-premium-desktop.png) | [移动](learn-premium-mobile.png) | [桌面](I-premium-desktop.png) | [移动](I-premium-mobile.png) |
| Noir & Champagne | [桌面](learn-noir-desktop.png) | [移动](learn-noir-mobile.png) | [桌面](I-noir-desktop.png) | [移动](I-noir-mobile.png) |

[Listening 规划](learn-listening-mobile.png) · [Speaking 规划](learn-speaking-mobile.png) · [Writing 规划](learn-writing-desktop.png) · [键盘焦点](learn-keyboard-focus.png) · [移动端 Reading 作答](L-mobile-answer.png)

- 双主题四种组合均验证四张技能卡在首屏完整显示，桌面两列、移动单列，无横向溢出。移动端导航、技能卡和考试类型按钮的触控目标至少为 44 × 44 CSS px。
- Chrome 键盘事件验证了四张技能卡的 Tab 顺序、可见焦点和 Enter 导航。触控事件验证了规划页及 Reading 入口，也验证了段落跳转目标位于固定导航下方。
- Reading 从 Learn 进入原工作区。隔离回归覆盖 Academic 与 General Training、Matching Headings 题组固定版本、刷新恢复、断线与超时重试的幂等、逐项评价、诊断、训练、独立迁移和延迟复习。另运行 TFNG/Error DNA 及 Profile/Review 的现有浏览器脚本。
- Learn 正常路径的 Chrome 资源日志和脚本错误均为零。Reading 测试主动制造断线、超时及证据请求失败以验证恢复路径。浏览器范围为 Chrome 桌面与手机模拟视口，Safari、实体手机和屏幕阅读器尚待人工验收。

[浏览器断言与 HTTP 证据](browser-http-evidence.json) · [隔离 SQLite 验证快照](sqlite-evidence.json)

## 复验命令

在 `backend` 下执行 `python -m scripts.verify_matching_headings_browser`。通过 `PHASE6_OUTPUT` 指定此次证据目录。脚本建立并清理临时 SQLite 与 Chrome 配置。Profile/Review 使用 `python -m scripts.verify_phase6_1_browser`，并通过 `PHASE6_1_BROWSER_OUTPUT` 指定独立输出目录。

前端运行 `node --test tests/*.test.mjs`、`npm run typecheck`、`tsc --noEmit -p tsconfig.app.json` 和 `npm run build`，后端运行完整 `pytest`。本次通过 48 项前端测试、166 项后端测试、TypeScript 检查、生产构建和 `git diff --check`。

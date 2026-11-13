# IELTS-2A.3 Error DNA 前端验收

Chrome Headless 通过真实 HTTP 访问 Vite 和本机 FastAPI。测试后端使用独立 SQLite、可控时钟和 FakeModelProvider。TFNG 在界面上标记为规则模式。

| 场景 | 浏览器结果 |
| --- | --- |
| Academic 逻辑诊断 | 支持逻辑假设、削弱定位假设，完成逻辑训练与独立迁移 |
| General Training 定位诊断 | 支持定位假设、削弱逻辑假设，完成定位训练与独立迁移 |
| 迁移失败和无可用题 | 分别显示需要继续练习和迁移证据不足 |
| 迁移成功、复习未到期 | 显示独立迁移通过、尚无保持证据、下一次复习时间 |
| 到期后复习成功和失败 | 按独立作答更新保持证据、时间线与下一次复习安排 |
| 空状态、请求异常与恢复 | 未作答显示空时间线。阻断诊断和复习请求后显示对应错误，恢复连接后可刷新重试 |
| 双主题和移动布局 | 1440px 双栏、390px 单栏均无横向溢出。切换主题并刷新后保留未提交作答 |

键盘 Tab 能看到焦点轮廓。训练操作将焦点送到作答框。验收脚本测得面板正文与背景的对比度为暖白 6.00:1、曜黑 9.06:1。曜黑的主阅读材料区域使用暖纸白。手机尺寸由 Chrome 模拟，未执行真机或屏幕阅读器验收。

## 截图与执行记录

| 主题 | 桌面 1440 × 1000 | 移动 390 × 844 |
| --- | --- | --- |
| Premium Academic | [复习成功](ielts-2a3-browser-evidence/premium-desktop.png) | [迁移通过、复习未到期](ielts-2a3-browser-evidence/premium-mobile.png) |
| Noir & Champagne | [复习成功](ielts-2a3-browser-evidence/noir-desktop.png) | [复习失败、需继续练习](ielts-2a3-browser-evidence/noir-mobile.png) |

[浏览器观察记录](ielts-2a3-browser-evidence/browser-observations.json) 包含实际会话 ID、视口宽度、状态文案和运行时异常检查。

## 数据来源

| 展示 | 后端来源 |
| --- | --- |
| 原始作答、假设、规则模式、证据 | `GET /api/v1/diagnoses/{id}`、`/hypotheses`、`/evidence` 和 `GET /api/v1/attempts/{id}` |
| 当前题目、可派发状态、作答时间线 | `GET /api/v1/sessions/{id}` 和 `/attempts` |
| 当前主题知识状态 | `GET /api/v1/profile/knowledge-states`，按当前学习者和主题筛选 |
| 已完成复习、到期与下次计划 | `GET /api/v1/reviews?status=pending` 和 `?status=completed`，按会话关联复习记录 |

主题状态与本会话保持证据分开展示。延迟保持使用服务端已完成、答对且具有作答 ID 的 `retention_verified` 记录。未提交草稿保存在当前浏览器标签页的 `sessionStorage`，按会话和题目恢复。

## 复验

- 后端 `python -m pytest backend -o addopts='' -q` 共 119 项通过。
- 前端 `node --test tests/*.test.mjs` 共 44 项通过。
- `npm run typecheck`、`tsc -p tsconfig.app.json --noEmit`、`npm run build` 和 `git diff --check` 均通过。
- `node frontend/scripts/verify-error-dna-browser.mjs` 连接指定的 Vite、FastAPI 和 Chrome CDP 实例。设置 `SMOKE_UI_URL`、`SMOKE_API_URL`、`SMOKE_CDP_URL`、`SMOKE_OUTPUT_DIR`、`TFNG_BROWSER_CLOCK`。FastAPI 使用空的独立 SQLite，以开发模式导入内容，设置 `MODEL_PROVIDER=fake` 与 `ALLOW_REMOTE_MODEL_CALLS=false`。在测试进程内将 `learning_service.utc_now` 绑定到读取 `TFNG_BROWSER_CLOCK` 文件中 ISO UTC 时间的函数，文件初始值为 `2026-11-11T08:00:00+00:00`。脚本通过真实作答生成复习记录，并修改该文件推进测试时钟。

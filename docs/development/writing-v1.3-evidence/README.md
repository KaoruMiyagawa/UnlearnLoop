# Learn V1.3 Writing 验收

从 Learn 进入 `/learn/writing`，完成原创题目 **Shared spaces for neighbourhoods**。Task 2 草稿支持实时字数、自动保存、本地恢复、正式提交、继续编辑和历史正文比较。同一学习者当前有一套题目和一个持续写作会话。建议 250 词，编辑上限 20,000 字符。

## 数据与反馈

- `LearningSession` 保存学习者与练习标识。 `WritingDraft` 保存题目版本快照、可编辑文本、更新时间及递增版本号。保存时校验版本，发现冲突时由用户选择使用哪份草稿。
- `WritingRevision` 保存提交原文、时间、版本号、上一个提交 ID、反馈快照和幂等键。SQLite 触发器阻止更新和删除已提交版本。写作记录通过共享 `/api/v1/profile/history` 显示摘要，正文按需从写作 API 读取。
- 字数、是否低于建议字数、以空行分隔的文本块数量及字数变化由服务端确定性计算。手写自查与自动检测分开显示。语义质量、论证、词汇、语法和 IELTS Band 尚未评估。Overall Band 8.0 是学习目标。
- 浏览器本地保存尚未同步的草稿和未确认的提交。刷新恢复需可访问服务端以打开会话。`learner_id` 是本地开发筛选条件，尚无正式身份认证。当前仅提供一套原创 Task 2 练习。

## 可复验记录

在 `backend` 目录执行 `..\.venv\Scripts\python.exe -m scripts.verify_writing_browser`。脚本在临时 SQLite 上初始化 0007，再启动真实 Uvicorn，验证 0008 增量迁移及 HTTP 流程，随后用 Headless Chrome 执行写作与历史流程。

- [真实 HTTP 结果](http-evidence.json)覆盖草稿重开、陈旧操作 409、同键重试、修订保留旧正文、其他学习者读取 404，以及共享历史。
- [浏览器结果](browser-evidence.json)覆盖键盘、自动保存、刷新、网络恢复、已提交响应丢失后的幂等重试，以及 HTML 按纯文本显示。
- 完整后端 pytest 169 项通过，含一条现有 Starlette 弃用警告。前端 50 项通过。TypeScript 和 Production build 通过。Alembic 唯一 head 为 `0008_writing_revisions`。
- Reading 与 Learn 导航回归通过 14 个浏览器场景。Listening 实际音频、作答评分、复盘跳转与历史回归通过。

| 主题与视口 | 工作区 | 修订比较 |
| --- | --- | --- |
| Premium Academic · 1440 × 1000 | [工作区](writing-premium-1440.png) | [比较](comparison-premium-1440.png) |
| Premium Academic · 390 × 844 | [工作区](writing-premium-390.png) | [比较](comparison-premium-390.png) |
| Noir & Champagne · 1440 × 1000 | [工作区](writing-noir-1440.png) | [比较](comparison-noir-1440.png) |
| Noir & Champagne · 390 × 844 | [工作区](writing-noir-390.png) | [比较](comparison-noir-390.png) |

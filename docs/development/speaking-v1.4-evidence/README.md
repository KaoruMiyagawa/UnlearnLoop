# Learn V1.4 Speaking 验收

Learn 中 Speaking 提供三道原创 Part 1 问题。用户点击后申请麦克风权限，使用浏览器 MediaRecorder 录音，在 IndexedDB 保存录音并播放、重录和比较。自查由用户填写。练习元数据关联共享 LearningSession 与历史，状态为 `not_assessed` 和 `practice_only`。

录音只存放在当前浏览器的 IndexedDB，清除网站数据可能造成丢失。删除本地录音后，服务端历史显示本地录音不可用，并允许删除历史元数据。录音不会通过 Speaking API 上传。使用麦克风需要 localhost 或 HTTPS 等安全环境。 `learner_id` 是开发环境中的筛选字段，不是正式身份认证。

本版仅支持有限的原创 Part 1 练习。没有自动转写、AI 语音评价或 IELTS Band 分数。Headless Chrome 验收使用模拟麦克风，**实体麦克风尚未测试**。

## 验收证据

- [真实 Uvicorn HTTP 与隔离 SQLite 结果](http-evidence.json)，覆盖 0008 → 0009、幂等、冲突、学习者筛选和删除。
- [Chrome 结果](browser-evidence.json)，覆盖模拟麦克风非空音频与播放、刷新、重录、权限拒绝、设备断开、本地存储失败、网络失败及删除后的本地状态。
- 完整后端 pytest 为 171 项通过，含一条现有 Starlette 弃用警告。前端测试 50 项、TypeScript 检查和 Production build 通过，Alembic 唯一 head 为 `0009_speaking_practice`。
- Reading 与 Learn 导航通过 14 个浏览器场景，Writing 草稿、提交和修订回归通过。Listening 首次与其他浏览器测试并行时在草稿恢复断言失败，独立重跑后播放、评分与历史流程通过。
- [Premium 桌面](speaking-premium-1440.png) · [Premium 手机](speaking-premium-390.png) · [Noir 桌面](speaking-noir-1440.png) · [Noir 手机](speaking-noir-390.png)
- [Premium 录音版本桌面](recordings-premium-1440.png) · [Premium 手机](recordings-premium-390.png) · [Noir 桌面](recordings-noir-1440.png) · [Noir 手机](recordings-noir-390.png)

复验命令：在 `backend` 目录运行 `..\.venv\Scripts\python.exe -m scripts.verify_speaking_browser`。该脚本在临时 SQLite、临时 Chrome 用户目录和独立本机端口运行。

# 本地快速启动：main

本指南针对默认分支的后端与前端占位界面，面向本机开发，不是生产部署指南。需要 Python 3.11+、Node.js 和 npm；命令从仓库根目录的 Windows PowerShell 执行。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

在后端终端：

```powershell
$env:DATABASE_URL = 'sqlite:///./unlearnloop-local-new.db'
$env:MODEL_PROVIDER = 'fake'
$env:ALLOW_REMOTE_MODEL_CALLS = 'false'
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
```

路径相对于 `backend/`，请选一个新文件；开发模式启动会自动迁移数据库并导入内容，使用已有数据库前应自行备份。另开终端从仓库根目录运行 `cd frontend`、`npm run dev`，访问 `http://127.0.0.1:15173`；API 文档位于 `http://127.0.0.1:18000/docs`。确认端口空闲；使用其他端口时相应配置 `VITE_API_BASE_URL` 和 `CORS_ORIGINS`。各终端使用 Ctrl+C 停止。

前端学习工作空间目前为占位界面；IELTS 分支有独立的完整流程和启动指南。默认禁用远程模型调用；FakeProvider 并非真实 AI 推理。仅在本机可信环境使用，learner ID 不提供认证。

当前 main 的 `get_session_factory` 缺少 `create_db_engine` 导入；数据库 API 请求会受此缺陷阻断，需在单独的代码变更中修复。启动和健康检查并不证明这些 API 可正常工作。

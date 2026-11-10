# VerbaTrail 本地快速启动

本指南适用于 Windows 本机开发，不是生产部署方案。需要 Python 3.11+、Node.js、npm 和 Git。命令从 `D:\Projects\VerbaTrail` 仓库根目录开始。

## 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

## 启动后端

在第一个 PowerShell 终端运行：

```powershell
$env:DATABASE_URL = 'sqlite:///./verbatrail-local.db'
$env:APP_NAME = 'VerbaTrail'
$env:MODEL_PROVIDER = 'fake'
$env:ALLOW_REMOTE_MODEL_CALLS = 'false'
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
```

`DATABASE_URL` 相对于 `backend/` 目录。第一次启动会运行 Alembic 迁移并导入内容包。为现有数据库建立并验证可恢复备份后再启动使用；本示例选择全新 `backend/verbatrail-local.db`，不会使用归档的 `backend/unlearnloop.db`。API 文档：`http://127.0.0.1:18000/docs`。

## 启动前端

在第二个终端运行：

```powershell
cd D:\Projects\VerbaTrail\frontend
npm run dev
```

访问 `http://127.0.0.1:15173`。结束服务时在对应终端按 Ctrl+C。`./start-verbatrail.ps1` 可在 Windows 统一启动服务；脚本只管理它自己记录且命令行/路径均匹配的进程，不接管其他服务。

如端口被占用，不要结束未知进程；选择未占用端口并同步修改 Vite 配置、`VITE_API_BASE_URL` 与后端 `CORS_ORIGINS`。

## 数据、模型与模式

- `FakeModelProvider` 为离线模拟，不会调用真实模型；远程模型调用默认关闭。
- 前端 Demo 是演示界面；Real 使用后端 API，并不代表使用了真实大模型。
- 服务端启动会迁移配置中的数据库。旧数据库已在整合备份中另存，开发默认使用独立数据库文件。
- 不提交 `.env`、API key、学习者答案、SQLite 数据库、日志或本地环境目录。
- 项目默认监听 loopback；`learner_id` 不构成认证，当前不可当作多用户生产服务。

更多测试命令见[中文 README](../../README.md#测试与工程检查)。

# 本地快速启动（IELTS 开发分支）

本指南面向本机开发和受控试用，不是生产部署指南。需要 Python 3.11+、Node.js、npm、Git；命令使用 Windows PowerShell，从仓库根目录开始。

1. 安装依赖：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python -m pip install -r backend/requirements.txt
   cd frontend
   npm ci
   cd ..
   ```

2. 在一个终端启动后端：

   ```powershell
   $env:DATABASE_URL = 'sqlite:///./unlearnloop-local-new.db'
   $env:MODEL_PROVIDER = 'fake'
   $env:ALLOW_REMOTE_MODEL_CALLS = 'false'
   cd backend
   ..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
   ```

   路径相对于 `backend/`；选择不存在的新文件。开发模式启动会自动升级配置的数据库并导入内容包，不会先自动备份已有库。使用已有数据前自行备份并验证可恢复。API 文档：`http://127.0.0.1:18000/docs`。

3. 在第二个终端，从仓库根目录运行：

   ```powershell
   cd frontend
   npm run dev
   ```

   打开 `http://127.0.0.1:15173`。确认这两个端口空闲；如使用其他端口，需相应设置前端 `VITE_API_BASE_URL` 与后端 `CORS_ORIGINS`。停止各终端中的服务使用 Ctrl+C。

4. 首页保存 Academic 或 General Training 模式，选择 Reading。默认 FakeProvider 是离线模拟，不会发起远程模型调用。前端的 Demo 是独立演示界面；Real 表示连接后端，**不意味着使用了真实大模型**。

运行测试见[中文 README](../../README.md#验证与目录)。不要把 `.env`、数据库、用户答案或 API 密钥提交到仓库。服务默认仅适合本机可信环境：learner ID 不提供认证；迁移备份、导出/删除和供应链风险见 [MVP 审查](MVP_FINAL_AUDIT.md)。

# 当前实现与边界：main

`main` 当前包含 Stage 4 后端学习 API、领域和应用服务、模型提供者抽象、SQLAlchemy / SQLite 持久化及 Alembic 迁移。React / TypeScript / Vite 前端提供占位工作空间和健康检查，尚未连接完整学习闭环。

默认远程模型调用关闭；FakeModelProvider 的离线模拟不是已验证的真实模型个性化诊断。开发模式启动会升级配置数据库并导入内容，使用已有数据库前应独立备份。learner ID 是筛选标识而非认证，当前应限制在本机可信环境。

当前 `get_session_factory` 引用未导入的 `create_db_engine`；直接调用引发 `NameError`，依赖它的数据库 API 存在已确认的运行阻断，需另行修复。

[IELTS 开发分支](https://github.com/KaoruMiyagawa/UnlearnLoop/tree/feat/ielts-pivot) 的阅读内容、完整学习界面和阶段验收尚未合并到本分支。[ARCHITECTURE.md](ARCHITECTURE.md) 是保留的原设计，包含未来目标，不是全部已交付功能。

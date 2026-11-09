# 当前实现与边界：IELTS-1 分支

本页描述 `feat/ielts-pivot`，与尚未合并该分支的默认分支不同。[ARCHITECTURE.md](ARCHITECTURE.md) 是原设计资料，包含目标而非全部已实现功能。

- React / TypeScript / Vite 工作空间通过版本化 REST API 请求考试设置、题目、作答、诊断、复习及档案；Demo 使用独立演示状态。
- FastAPI API、应用服务和领域规则控制会话、诊断动作、评价及迁移。IELTS 内容包和阅读评价器处理当前题目；SQLAlchemy / SQLite 保存状态，Alembic 管理迁移。
- 诊断引擎结合规则、证据、模型提供者输出和白名单动作；当前验收使用 FakeModelProvider，候选假设和权重是启发式判断。
- 开发启动会升级数据库并导入内容；没有自动备份/恢复或面向用户的导出/删除流程。learner ID 用于筛选，不构成身份认证和授权，不能将本地信任边界当作多用户安全保障。
- 本次验收验证了隔离浏览器中列出的流程，未验证真实模型诊断质量、生产部署、真实设备或完整无障碍。详见 [IELTS-1 报告](../development/IELTS_1_FINAL_BROWSER_ACCEPTANCE.md) 与 [MVP 审查](../development/MVP_FINAL_AUDIT.md)。

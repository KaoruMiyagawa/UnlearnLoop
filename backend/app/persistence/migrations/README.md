# Alembic 数据库迁移目录（Stage 2 启用）

本目录预留用于存放 SQLAlchemy + Alembic 数据库迁移脚本（`env.py` 与 `versions/`）。

根据 `docs/development/ROADMAP.md`：
- **Stage 1**：仅建立 SQLAlchemy `Base`、Engine 工厂与 Alembic 配置接入点，不创建业务表。
- **Stage 2**：在此目录下初始化首个领域实体迁移（`KnowledgeTopic`、`LearningSession`、`Attempt`、`DiagnosticCase`、`Hypothesis`、`EvidenceLink` 等）。

# Alembic 数据库迁移目录

本目录存放 VerbaTrail 的 SQLAlchemy 2.x + Alembic 数据库迁移配置与版本脚本：

- `env.py`：Alembic 迁移运行环境（自动对 SQLite 连接开启 `PRAGMA foreign_keys=ON`）。
- `versions/0001_initial_stage2_schema.py`：Stage 2 初始领域模型迁移，创建学科无关的核心表结构（`knowledge_topics`、`knowledge_topic_dependencies`、`learning_materials`、`questions`、`learning_sessions`、`attempts`、`diagnostic_cases`、`hypotheses`、`decision_events`、`evidence_links`、`knowledge_states`、`review_items`）。

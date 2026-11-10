# VerbaTrail 开发路线图与历史阶段索引

此路线图保留了 UnlearnLoop 阶段 0–7 的历史工程分解，供 Git 历史追溯。产品名现为 VerbaTrail；下面较早阶段文档中的名称与状态描述以其归档日期为准，不覆盖当前实现。

## 当前阶段状态（2026-11-10）

- Stage 3：Agent 诊断决策核心已实现；FakeModelProvider 用于模拟，不能据此宣称真实模型诊断有效。
- Stage 4：学习闭环 REST API 与应用编排已实现。
- Stage 5：API Client、学习工作区、复习及档案已有阶段成果。
- IELTS-1：Academic 与 General Training 阅读闭环通过指定隔离环境阶段验收。
- 双主题 UI：React 单应用集成 Premium Academic 与 Noir & Champagne；视觉验收记录存于 `theme-visual-acceptance/`。
- 生产部署、真实 AI 质量、身份认证、多用户安全、数据备份恢复/删除流程尚未通过生产验收。

## 后续优先级

1. 在评审后将本地 `feat/verbatrail-consolidation` 安全纳入正式远程主线；本轮不 Push。
2. 维护数据库迁移前备份与恢复演练，明确本地数据导出/删除策略和单用户信任边界。
3. 完善干净 Windows 环境安装、前后端启动与隔离浏览器回归。
4. 在内容授权、评价标准、隐私和预算门禁具备后，规划 Listening、Writing、Speaking、Vocabulary、Grammar 和 Mock Tests。
5. UKVI 与 Life Skills 为扩展方向，尚未实现。

早期阶段的验收条件和 IELTS 未实现提案见 `docs/archive/` 及 `docs/ielts-0-baseline/`；它们是规划/历史资料，不是当前功能清单。

# VerbaTrail 产品需求概要

状态：当前产品范围摘要，2026-11-10。实现状态以代码、测试和验收证据为准。

## 产品定位

VerbaTrail 是面向英语学习和 IELTS 备考的自适应学习软件。核心区别是围绕错误证据组织后续学习：服务端保留候选解释，选择追问或练习收集证据，并通过独立新情境判断当前理解是否迁移。

## 当前交付范围

- IELTS Academic 与 General Training 阅读学习路径。
- 使用原创英文材料的服务端任务选择、作答与阅读评价。
- 受状态约束的 Agent 诊断工作流：竞争假设、证据、追问、定向练习、独立迁移验证。
- 学习历史、知识状态、ReviewItem 与复习证据展示。
- Real API 与 Demo 模式区分。
- 单一 React 应用中的 Premium Academic / Noir & Champagne 两主题。

## 重要边界

- FakeModelProvider 流程用于离线模拟；不能宣称真实 AI 个性化诊断成功。
- 一次正确答案、同题重复或练习通过不能单独证明长期掌握。
- IELTS Band 目标不是系统评估分数；目前不产出经校准的个人官方分数。
- Listening、Writing、Speaking、Vocabulary、Grammar、Mock Tests、UKVI 与 Life Skills 尚未作为完整学习模块交付。
- 当前本地单用户系统不提供生产级身份认证或多租户隔离。

## 学习流程

```mermaid
flowchart LR
 A[答题] --> B[服务端评价]
 B --> C[候选错误解释与证据]
 C --> D[追问]
 D --> E[定向练习]
 E --> F[新情境迁移]
 F --> G[知识状态与复习安排]
```

服务端会按会话状态跳过不适用步骤；界面必须展示实际服务端结果，不自行补造流程或状态。

## 后续需求

扩大四科原创内容与题型覆盖；完善离线备份/恢复、学习数据控制、无障碍和干净环境安装；在独立隐私、成本和质量门禁通过后，再评估真实模型评分或 band 估计。所有未来功能应先有验收标准，不能在 README 或 UI 中提前标为完成。

旧版 UnlearnLoop MVP 产品需求作为历史资料保留在 [`docs/archive/legacy/UNLEARNLOOP_PRD.md`](../archive/legacy/UNLEARNLOOP_PRD.md)。

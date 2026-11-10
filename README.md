# VerbaTrail

**把错误变成线索，在新情境中验证理解。**

VerbaTrail 正在建设一款 AI Agent 驱动的英语学习与 IELTS 备考平台，以 **IELTS Overall Band 8.0** 为学习目标。8.0 是学习目标，不是分数预测或保证。

[English](README_EN.md) · [最新应用开发分支](https://github.com/KaoruMiyagawa/VerbaTrail/tree/feat/verbatrail-consolidation) · [该分支中文 README](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/verbatrail-consolidation/README.md)

> **主线状态：** 当前 `main` 保留较早的项目基线，尚未包含最新 IELTS Reading 应用界面与双主题整合。以下截图及最新功能状态来自独立开发分支 [`feat/verbatrail-consolidation`](https://github.com/KaoruMiyagawa/VerbaTrail/tree/feat/verbatrail-consolidation)，尚未合并至 `main`，也不代表生产发布。

## 产品方向

普通刷题工具常在显示正误后结束。VerbaTrail 关注错误可能说明什么、还需要哪些证据，以及理解能否迁移到新问题。

**Error DNA** 是规划中的产品概念，用于整理可验证的重复错误线索。最新开发分支已经实现相关基础：服务端竞争假设与证据、状态驱动追问、针对性练习、独立迁移题、知识状态和间隔复习安排。当前没有经过校准的 Error DNA 学习画像；长期记忆效果、真实模型个性化质量和官方 IELTS 评分均未验证。

```mermaid
flowchart LR
    A[作答] --> B[服务端评价]
    B --> C[候选错误假设与证据]
    C --> D[区分性追问]
    D --> E[针对性练习]
    E --> F[独立新题迁移验证]
    F --> G[知识状态与复习计划]
```

这是产品学习流程示意。实际可用环节取决于代码分支、服务端会话状态和题目；不表示 `main` 已包含完整流程。

## 功能状态

| 能力 | `main` 当前版本 | 最新整合分支 |
| --- | --- | --- |
| IELTS Reading | 尚无最新整合版阅读工作台 | Academic 与 General Training 阅读任务和学习流程已实现，并通过 IELTS-1 阶段验收 |
| 诊断与练习 | 保留早期后端学习与诊断基础 | 有竞争假设、证据、追问、针对性练习和独立迁移验证；流程使用 FakeModelProvider 时仅为模拟 |
| Review 与学习档案 | 尚无最新整合版页面 | 服务端复习任务、历史、知识状态与相关证据页面已接入 |
| Premium / Noir 主题 | 尚未包含双主题应用界面 | Premium Academic 与 Noir & Champagne 已集成到同一 React 应用 |
| Listening、Writing、Speaking、Vocabulary、Grammar、Mock Tests | 规划中 | 规划中，未作为完整功能交付 |
| UKVI、Life Skills | 规划中 | 规划中，未作为可用考试流程交付 |
| 真实 AI 诊断、Band 预测、官方评分 | 未验证 | 未验证；项目不宣称这些能力已通过质量评估 |

### 最新开发分支的真实截图

截图来自独立 Headless Chrome 验收。阅读流程使用 FakeModelProvider，不代表真实模型效果；窄屏截图也记录在[验收证据目录](https://github.com/KaoruMiyagawa/VerbaTrail/tree/feat/verbatrail-consolidation/docs/development/consolidation-browser-evidence)。

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/verbatrail-consolidation/docs/development/consolidation-browser-evidence/home-premium.png" alt="Premium Academic 首页验收截图" width="100%"><br><sub>Premium Academic · 首页</sub></td>
    <td><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/verbatrail-consolidation/docs/development/consolidation-browser-evidence/home-noir.png" alt="Noir and Champagne 首页验收截图" width="100%"><br><sub>Noir &amp; Champagne · 首页</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="https://raw.githubusercontent.com/KaoruMiyagawa/VerbaTrail/feat/verbatrail-consolidation/docs/development/consolidation-browser-evidence/academic-reading-premium.png" alt="Academic Reading 工作台验收截图" width="100%"><br><sub>Academic Reading · 阅读文章与服务端题目</sub></td>
  </tr>
</table>

## 技术与开发入口

最新开发分支采用 React、TypeScript、Vite、FastAPI、SQLAlchemy、SQLite 和 Alembic。前端读取服务端任务与状态；后端管理学习流程、数据写入、诊断与复习。该架构说明描述的是[最新开发分支](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/verbatrail-consolidation/docs/architecture/CURRENT_ARCHITECTURE.md)，不应误认为已全部进入 `main`。

- [最新版本快速启动指南](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/verbatrail-consolidation/docs/development/QUICKSTART.md)
- [当前实现与开发路线图](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/verbatrail-consolidation/docs/development/ROADMAP.md)
- [最新分支的浏览器验收记录](https://github.com/KaoruMiyagawa/VerbaTrail/blob/feat/verbatrail-consolidation/docs/development/consolidation-browser-evidence/README.md)

最新分支的工程基线为后端 80 项、前端 40 项测试通过，TypeScript typecheck 与 production build 通过。测试及浏览器验收使用固定样例和 FakeModelProvider；真实模型效果与生产部署仍需单独验证。

## 后续方向

- 稳定并审阅 Academic / General Training 阅读、复习、学习档案与双主题体验。
- 逐步规划 Listening、Writing、Speaking、Vocabulary、Grammar、Mock Tests、UKVI 和 Life Skills。
- 为 Error DNA、真实模型、分数估计与长期学习效果建立独立的隐私、预算和质量验证。

欢迎先通过 issue 讨论改进。当前仓库尚未声明开源许可证，请勿假定可以自由使用或再分发。
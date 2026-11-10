# VerbaTrail 历史方案：IELTS Band 8.0 高保真视觉与信息架构原型

> 归档资料：Oxford、Nordic、Nocturne 是早期候选原型，并非当前功能实现。当前选定方向和双主题样式以 `../../verbatrail-dual-theme-reference/` 中的最终 handoff 为准。

## 一、产品定位与视觉基调

**VerbaTrail** 面向以 **IELTS Overall Band 8.0** 为核心目标的进阶学习者（完整支持 **Academic** 与 **General Training** 双轨切换，并在信息架构上预留 **UKVI / Life Skills** 扩展能力）。

核心设计原则：
- **Premium & Academic（高级学术感）**：采用深海军蓝/墨蓝（`#0C192E`）搭配雾白（`#F6F7FA`）与克制的拉丝鎏金（`#C89D3C`）/ 冷萃钴蓝（`#1E40AF`）点缀；文章阅读与主标题采用经典学术衬线体（Georgia / Cambria），界面控件采用现代无衬线字体。
- **Calm but Powerful（克制而专注）**：延续 Focus 理念，杜绝刷题网站的密集题海感与后台管理面板的监控感，每一屏均有唯一视觉重心。

---

## 二、三套高保真原型文件说明

所有原型均位于本目录：

1. **[index.html](index.html)**
   - 三套方案总览切换台，支持一键切换 **桌面端视口** 与 **窄屏 (390px) 自适应视口**。
2. **[direction-a-oxford-prestige.html](direction-a-oxford-prestige.html)（历史推荐方案：Naval & Gold Academic Prestige）**
   - **色彩与气质**：深海军蓝顶栏与 Band 8.0 目标舱 + 雾白工作区画布 + 细微鎏金徽章。
   - **推荐理由**：最具国际高阶学术测试与精英教育品牌辨识度；同时完美平衡了顶层品牌感（深色靶心区）与长时间阅读做题的视觉舒适度（雾白与纯白纸张工作区）。
3. **[direction-b-nordic-atelier.html](direction-b-nordic-atelier.html)（方案 B：Nordic Editorial & Ice Cobalt）**
   - **色彩与气质**：极昼雾白毛玻璃顶栏 + 墨蓝高对比文字 + 冷萃钴蓝强调色。
   - **特点**：采用内嵌式轻量目标丝带（Target Ribbon）与非对称双栏社论式布局，极度轻盈现代。
4. **[direction-c-nocturne-scholar.html](direction-c-nocturne-scholar.html)（方案 C：Deep Ink Studio & Warm Alabaster）**
   - **色彩与气质**：左侧深邃墨蓝常驻指挥轨 + 右侧低眩光暖羊皮纸阅读台（`#F6F5F0`）。
   - **特点**：将 Band 8.0 目标与四页导航收纳于左侧窄轨，右侧全幅留给精读与复盘。

---

## 三、四大核心页面信息架构（每套方案均完整可交互）

1. **首页 / Dashboard**
   - **第一层级（目标锚点）**：`Overall Band 8.0` 目标徽章、`Academic / General Training` 实时切换（含 `UKVI · Life Skills Ready` 扩展位）、以及 `Listening 8.5 / Reading 8.5 / Writing 7.5 / Speaking 7.5` 四科当前与目标分差。
   - **第二层级（绝对视觉中心）**：**“Continue Today's Study（继续今天的学习）”** 主卡片，清晰回答 *What to do now*、*Why this task was selected (Band 7.5→8.5 bottleneck)* 与 *What happens next*。
   - **第三层级（四科工作室入口）**：`Reading`、`Writing`、`Listening`、`Speaking` 四张等高学术卡片，直达对应诊断训练。
   - **第四层级（安静的次级入口）**：底部收敛式工具条，承载 `Vocabulary`、`Grammar`、`Spaced Review`、`Mock Tests` 与 `Learning Profile`，绝不抢占主任务注意力。
2. **Reading 学习页面（IELTS Reading Diagnostic Studio）**
   - **左文右题沉浸双栏（窄屏下自动流式折叠为上下结构）**：左侧为 C1/C2 级别雅思学术长文（带 `[A]` `[B]` `[C]` 段落锚点与优雅衬线排版）；右侧为固定跟随的雅思真题交互区（`TRUE / FALSE / NOT GIVEN` + 诊断归因选择）。
   - **提交后高价值反馈状态**：提交后不仅给出正误，还会在左侧原文 `[B]` 段自动高亮关键证据句（*"have yet to establish whether..."*），解析为何属于 **NOT GIVEN（文本未证实比较）** 而非 **FALSE（直接矛盾）**，并提供可按需展开的竞争性错误假设说明。
3. **Review 页面（Spaced Memory Verification Studio）**
   - 摒弃普通待办清单，聚焦 **“长期记忆跨语境验证”**（如在全新的城市交通政策语境中检验 C1 让步妥协动词 `mitigate` vs `eradicate`）与 **“下一次复习窗口演进（+3 Days → +14 Days Stable）”**。
4. **Learning Profile 页面（Band 8.0 Mastery & Evidence Dossier）**
   - 设计为高管级 **“Band 8.0 学术成长档案”**，展示四科能力跃迁、已解决的认知卡点演化轨迹（从武断绝对化表述到 C1 学术降调修饰）及待验证证据链。

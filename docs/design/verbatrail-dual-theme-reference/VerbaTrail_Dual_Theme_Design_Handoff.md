# VerbaTrail 双主题视觉规范与 React 接入指南

## 主题决策
- `premium`：深海蓝 × 暖纸白（Premium Academic），为日常专注学习的默认视觉。
- `noir`：曜石黑 × 香槟金（Noir & Champagne），强调氛围与品牌辨识度。
- 两者为**同一产品的皮肤，不是两套页面或业务代码**。Reading 长文在黑金主题中仍采用暖象牙白阅读底色，以保持长时阅读舒适度。
- 顶栏一个按钮直接切换主题；按钮显示**下一主题**，如当前暖白时显示“曜黑”。

## 本次原型实现
- 单文件 HTML，带 Overview / Reading / Review / Learning Profile 四页交互演示。
- 选择 Academic / General Training、回答题目后，切换主题不重新加载 DOM，不重置当前页面、单选题、反馈、复习模拟及成长记录。
- 主题偏好通过浏览器 `localStorage` 键 `verbatrail.design.theme` 保存（若不可用则当前页面仍可切换）。不包含学习数据；原型的学习数据仍为示例。
- 桌面与 390px 手机端均保留同一主题按钮，并具备键盘焦点、可读按钮标签和 `aria-pressed`。

## React 正式集成原则（已在 IELTS-1 本地整合分支实施；本文保留原交接记录）
1. 在 VerbaTrail React 项目中引入 **一个** `ThemeProvider` / `useTheme` 与两套 token，勿复制 App、路由、页面或 API Client。
2. 推荐显式 `data-theme="premium" | "noir"` 设置在 `document.documentElement`，主题 token 统一管理，CSS 组件只使用 token 或有意的语义状态色。
3. 首屏在 React 渲染前读取轻量偏好，避免白→黑闪烁；本地存储异常应安全退回默认主题。
4. 主题切换仅更改视觉，不重新拉取或清空学习会话，保留输入草稿、选项、题目、Agent 诊断和当前路由。
5. `color-scheme`、焦点环、错误/成功状态、滚动条及表单控件需要分别在两种主题下核验。Reading 原文背景在 Noir 保留暖白对比。
6. 不把示例成绩、模拟复习任务或本地演示作答当成真实 API 结果；真实模式必须沿用服务端权威状态。
7. 分别检查桌面、390px、键盘 Tab/Enter/Space、刷新记住主题，以及 A/G 与 Demo/Real 隔离。
8. 保留 UnlearnLoop 原业务引擎和既有数据；默认不更名 GitHub、不改 main、不提交/推送，直到验收通过。

## 文件
- `VerbaTrail_Dual_Theme_IELTS_Prototype.html`：统一双主题可交互原型。
- `VerbaTrail_Home_Desktop.png`、`VerbaTrail_NoirGold_Home_Desktop.png`：原两主题设计参考。
- 原两份独立 HTML 原型作为历史基线保留，方便精确对比。

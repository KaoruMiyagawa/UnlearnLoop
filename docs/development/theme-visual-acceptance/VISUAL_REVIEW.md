# VerbaTrail 双主题 UI 最终视觉验收

- 日期：2026-11-10
- 当前归档工作区：`D:\Projects\VerbaTrail`
- 原验收来源分支：`feat/ielts-pivot`（见下列环境记录）
- 浏览器：Headless Chrome，CDP
- 隔离环境：前端 `127.0.0.1:18942`，后端 `127.0.0.1:18941`，临时 SQLite `D:\Temp\verbatrail-visual-acceptance-20261110.sqlite`，FakeModelProvider；未连接付费模型。
- 设计基准：`../../design/verbatrail-dual-theme-reference/VerbaTrail_Dual_Theme_IELTS_Prototype.html`、`VerbaTrail_Dual_Theme_Design_Handoff.md` 及同目录参考图。

## 截图证据

桌面视口为 1440 × 1000，手机视口为 390 × 844。页面中的学习记录由隔离后端 API 返回；Review 空状态是该临时库的真实空数据。诊断操作由 FakeModelProvider 驱动，只证明页面和后端流程可走通，不证明真实 AI 个性化诊断质量。

| 页面 | Premium Academic | Noir & Champagne |
|---|---|---|
| Home 桌面 | `premium-home-desktop.png` | `noir-home-desktop.png` |
| Reading 桌面 | `premium-reading-desktop.png` | `noir-reading-desktop.png` |
| Review 桌面（真实空状态） | `premium-review-empty.png` | `noir-review-empty.png` |
| Learning Profile 桌面（真实 API 记录） | `premium-profile-real.png` | `noir-profile-real.png` |
| Home 手机 | `premium-home-mobile.png` | `noir-home-mobile.png` |
| Reading 手机 | `premium-reading-mobile.png` | `noir-reading-mobile.png` |
| 阅读错误诊断状态 | `premium-reading-wrong-answer.png` | `noir-reading-diagnosis.png` |
| Review 错误状态（模拟离线） | `premium-review-error.png` | — |
| 键盘焦点 Tab 状态 | `keyboard-focus-tab.png` | — |

## 逐项验收

| 场景 / 操作 | 预期行为 | 实际结果 | 判定 | 证据 |
|---|---|---|---|---|
| Premium / Noir 页面核对：切换主题，访问 Home、Reading、Review、Profile | 共用 React 页面跟随主题令牌切换；Noir 维持高可读性；页面内容与数据状态不因皮肤改变 | 两套主题均完成四页桌面截取。Noir 主视觉和卡片为曜黑/香槟金，Reading 原文仍为暖象牙底；Premium 使用暖纸白和深海蓝。主题均保持相同真实 API 内容 | PASS | 上表 8 张桌面图 |
| 手机 Home 和 Reading：设为 390 × 844 后打开两页 | 内容单列、控件可触达、页面不横向溢出 | 两主题 Home / Reading 均截图；浏览器 `document.documentElement.scrollWidth` = 390，未见页面级横向溢出 | PASS | 上表 4 张手机图；CDP viewport/scrollWidth |
| Reading 文章及答题区 | 文章与题目清晰分区；长选项完整可读；Noir 阅读区保持暖色底 | 两栏布局和滚动区正常。初查发现选项代码片段在桌面窄题栏中会横向滚动并截断；加上仅作用于题目代码块的换行规则后，文本完整换行，内部 `scrollWidth` 与 `clientWidth` 相等 | PASS（修复后） | `premium-reading-desktop.png`、`noir-reading-desktop.png` |
| 真实作答、诊断流程展示 | 作答结果由服务端返回；诊断界面如实显示提供方，不能误称真实 AI | 提交实际错误答案后收到服务端错误评价及 follow-up 状态，诊断步骤继续运行。界面标注 FakeModelProvider；该证据仅为模拟提供方流程 | PASS（流程）；真实模型能力未验证 | `premium-reading-wrong-answer.png`、`noir-reading-diagnosis.png` |
| Review 空状态及错误状态 | 空数据与 API 失败明确区分；失败时保留重试且不造演示记录 | Review 首次请求从隔离 API 返回真实空列表；随后仅在当前浏览器模拟离线，页面显示“复习任务读取失败。真实模式不会替换为演示记录。重试”告警 | PASS | 两张 `*-review-empty.png`；`premium-review-error.png` |
| Learning Profile 数据 | 展示 API 历史、证据/知识状态未知；不虚构 Band 或掌握程度 | Profile 展示临时数据库产生的学习历史与状态；未显示伪造 IELTS Band。当前缺少的迁移/长期保持证据明确显示为空或未知 | PASS | `premium-profile-real.png`、`noir-profile-real.png` |
| 键盘焦点 | Tab 导航有清晰、可见焦点环 | Tab 将焦点移至品牌按钮，`:focus-visible` 为真，outline 为 solid 3px | PASS | `keyboard-focus-tab.png`；CDP activeElement 与 computed style |
| 文本截断、横向溢出 | 页面和题目选项不截断、不溢出 | 390px 两主题 Home / Reading 文档宽度均匹配视口；修复后题目选项不再出现内部横向滚动。未观察到标题、导航或正文被裁切 | PASS | 手机截图、Reading 桌面图和宽度测量 |

## 原型对比与差异

- **颜色和阅读层级：** 两主题的暖纸白/深海蓝、曜黑/香槟金、衬线标题、克制边框及留白与原型方向一致。Noir Reading 正文仍用暖象牙白，正文对比清楚。
- **Home：** 保留 8.0 目标表达、四科入口和当前阅读入口；实际目标及状态取自应用数据，不显示原型演示成绩。复核截图时发现 Noir 的主要行动区偏深海蓝，与原型黑金渐层不一致；已用主题专属渐层和金色边框做最小 CSS 修正，并重拍 Noir 桌面/手机 Home。
- **Reading：** 桌面使用文章/题目双栏，文章区独立滚动、题卡保持可见；手机改为单栏。代码/答案选项依据内容换行。Noir 文章底色刻意保留暖白，符合 handoff 的可读性要求。
- **Review / Profile：** 以服务端空状态、错误状态和历史记录为准，没有照搬原型中的示例复习计划、演示成绩或 Band 指标。
- **导航差异：** 原型桌面左侧栏、手机底部导航；正式 React 项目保留现有顶部导航并在手机折行。该适配维持已有单一路由与导航组件，手机链接可见且未造成横向溢出；属于已知非阻断的布局差异。
- **其余页面：** Listening、Writing、Speaking 等仍使用建设中状态，没有伪造功能。

## 最小修复与工程检查

本轮视觉修正仅在 `frontend/src/design-system/tokens.css` 中进行：Noir Home 主视觉配色、Reading 题目代码块自动换行。没有改动业务状态、API、后端、数据库迁移或其他工作区。

- Frontend 测试：40 / 40 通过。
- TypeScript typecheck：通过。
- Production build：通过。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 提示。
- 本轮未重复运行后端测试，因为没有后端代码改动；本次浏览器走真实隔离后端 API。
- 浏览器脚本未捕获未处理 JavaScript 异常；离线错误由人为启用的浏览器网络模拟产生，随后已恢复在线。

## 结论

双主题主要页面通过本轮视觉验收。阅读长选项截断和 Noir 首页主视觉偏色已做最小修正，修正后的前端测试、类型检查和构建均通过。剩余主要差异是原型与现有 React 项目的导航形态不同；没有发现阻断性视觉问题。本轮没有 Commit、Push、Merge，也未改动 main 或集成 Worktree。

## 对比度抽查

Headless Chrome 在 Noir 首页读取到的主题正文颜色组合：Hero 标题 17.26:1、Hero 描述 10.88:1、考试模式标题 14.17:1、考试模式说明 9.06:1；均高于普通文字 4.5:1 的 WCAG AA 对比度参考值。Tab 焦点环为 3px 实线。该数值是选定关键文本的抽查，不代表对所有页面每个状态都进行了完整 WCAG 审计。

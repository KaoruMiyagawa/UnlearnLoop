# IELTS-2A.3.1 Error DNA 视觉与交互验收

## 精修对照

| 项目 | IELTS-2A.3 | IELTS-2A.3.1 |
| --- | --- | --- |
| 首屏 | 先显示三张状态卡，再显示下一步与错误假设 | 当前证据支持的假设与下一步优先出现。主题知识状态与本会话延迟保持使用紧凑的双列摘要 |
| 证据 | 每条证据与来源说明直接展开 | 假设卡默认显示状态及支持、削弱条数。证据详情和诊断记录分别展开。学生视图中的已知技术说明使用中文 |
| 下一步 | 复习时间在状态卡，操作在下一步区域 | 时间、到期状态和操作集中在下一步。到期有复习入口，有派发题时可继续训练，迁移题不可用时解释原因 |
| 390px 导航 | 横排紧凑按钮 | 六个等宽导航目标，每个至少 44px 高，已在 Chrome 触控模拟中点击诊断及学习入口 |

| 主题和尺寸 | 精修前 | 精修后 |
| --- | --- | --- |
| Premium Academic · 1440 × 1000 | [截图](ielts-2a3-browser-evidence/premium-desktop.png) | [截图](ielts-2a3-1-browser-evidence/premium-desktop.png) |
| Noir & Champagne · 1440 × 1000 | [截图](ielts-2a3-browser-evidence/noir-desktop.png) | [截图](ielts-2a3-1-browser-evidence/noir-desktop.png) |
| Premium Academic · 390 × 844 | [截图](ielts-2a3-browser-evidence/premium-mobile.png) | [截图](ielts-2a3-1-browser-evidence/premium-mobile.png) |
| Noir & Champagne · 390 × 844 | [截图](ielts-2a3-browser-evidence/noir-mobile.png) | [截图](ielts-2a3-1-browser-evidence/noir-mobile.png) |

其他实拍状态包括[展开证据](ielts-2a3-1-browser-evidence/premium-expanded-desktop.png)、[继续针对性训练](ielts-2a3-1-browser-evidence/premium-training-mobile.png)和[复习已到期](ielts-2a3-1-browser-evidence/noir-due-mobile.png)。

## 验证结果

- Chrome Headless 通过真实 HTTP 连接本机 FastAPI，使用独立 SQLite 和测试时钟。重新完成 Academic 逻辑诊断、General Training 定位诊断、训练、迁移及复习。迁移失败、题库耗尽、未到期和请求异常均有对应反馈。题库耗尽时未提供迁移派题按钮。
- 两种主题的 1440px 和 390px 视口均无页面或面板横向溢出。390px 的状态摘要为 56–76px。正文对比度为暖白 6.00:1、曜黑 9.06:1。
- 证据和审计默认收起。键盘 Enter 可展开证据，中文说明和原始审计备注分别可读。切换主题和刷新后草稿保留。训练入口能将焦点移到已派发题目的作答框。
- 后端完整 pytest 119 项通过，前端完整测试 44 项通过，TypeScript typecheck、应用配置类型检查、production build 和 `git diff --check` 通过。
- 复习状态与操作权限沿用现有 API。正式 SQLite 的 SHA-256 与精修前一致。

[浏览器观察记录](ielts-2a3-1-browser-evidence/browser-observations.json) 保存视口、实测摘要高度、界面文案和运行时异常检查。复用 [IELTS-2A.3 复验环境](IELTS_2A3_ERROR_DNA_ACCEPTANCE.md#复验)，将 `SMOKE_OUTPUT_DIR` 指向精修证据目录即可重跑。移动端验收采用 Chrome 模拟，未执行真机或屏幕阅读器验收。

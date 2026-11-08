# Stage 5C.3A：独立迁移验证验收记录

基线：`b8a061f2e12d7cc3758c5faa30ef2fefee45dc2b`。本阶段修改保留在 `feat/stage5c-integration` 工作区，未提交或推送。

## 业务边界

- 复用 SessionStatus、DiagnosticCaseStatus、KnowledgeMasteryStatus，不新增状态枚举或平行状态机。
- 已由 Agent 派发的练习必须先作答并通过，不能调用迁移派题接口跳过；Agent 根据充分追问证据直接选择迁移的既有合法路径仍保留。
- 练习通过只更新为证据不足，并派发未见过的迁移题；失败则保留待练习状态并允许继续诊断。
- 迁移题按照学习者历史的题目 ID 和题干/代码情境内容排除旧题；修改 ID 或空白不能让旧情境成为新证据。
- `stable` 表示当前独立迁移验证通过，页面明确说明长期保持尚未验证；会话结束是另一项显式操作。
- 原题重交不能授予掌握；失败迁移题重答即使正确，也不计为独立通过。新错误会将旧的 stable 信号更新为 needs_diagnosis。

## 实际状态转换

| 事件 | SessionStatus | DiagnosticCaseStatus | KnowledgeMasteryStatus |
| --- | --- | --- | --- |
| 初始作答需诊断 | diagnosing | collecting_attempt | needs_diagnosis |
| Agent 派追问 | diagnosing | question_selected | 保留当前信号 |
| Agent 派练习 | intervening | intervention_selected | 保留当前信号 |
| 练习失败 | diagnosing | needs_evidence | needs_practice |
| 练习通过且有独立迁移题 | transfer_checking | transfer_checking | insufficient_evidence |
| 缺少未见过的迁移题 | transfer_checking | needs_evidence | 保留不确定性 |
| 迁移失败 | transfer_checking | needs_evidence | needs_practice |
| 新情境迁移通过 | transfer_checking | resolved | stable（当前验证） |
| 显式完成会话 | completed | 保留已记录状态 | 不自动提升 |

表中描述的是有诊断案例的路径；初始作答充分正确时，既有的直接迁移路径不要求虚构诊断案例。

## API 和持久化

没有新增路由、数据库表或 Alembic 迁移。

- `SessionDetailResponse` 增加 `latest_attempt_result`、`can_dispatch_transfer`，用于刷新恢复评价与呈现服务端许可。
- `AttemptResultResponse` 增加 `evaluation_source`、`mastery_note`；`AttemptDetailResponse` 增加 `diagnostic_case_id`、`evaluation_source`。
- Attempt 继续保存原始作答及题目版本快照；DecisionEvent 的既有 JSON 字段保存经过筛选的原始作答响应及评价来源，并通过既有外键关联诊断案例。
- 练习和迁移观察通过 EvidenceLink 关联各候选假设。失败本身记作中性观察，不据此确认所有错误原因。
- 新作答的同幂等键请求返回原响应，即使会话已推进或结束；跨会话/不同内容复用键会冲突。并发同意图请求只形成一条作答和一份结果记录。
- 前端把待确认提交保存在独立的 Real 会话存储键中，刷新重试保留原题目、答案与幂等键。
- `force_fresh` 保留兼容，但不能替换尚未作答的合法迁移题；重复派题请求恢复同一道题。
- 新增 `q_py_loop_practice_02`，内容包从 22 题增至 23 题。导入只增加该题，不删除学习记录。

旧版本没有保存完整作答响应的记录，`latest_attempt_result` 或评价来源可能为空；不会补造过去的响应或来源。当前题目、作答历史和诊断仍读取既有服务端记录。

## 自动化验收

在 backend 目录使用已有 Python 环境执行：

```powershell
& 'D:\Temp\unlearnloop-stage5c2-final-venv\Scripts\python.exe' -m pytest -o addopts='' -q
```

结果：59 passed，1 项现有 Starlette/httpx 弃用提示。

在 frontend 目录执行：

```powershell
node --test tests/*.test.mjs
npm run typecheck
npm run build
```

结果：34 项前端测试通过，typecheck 与包含 `tsc -b` 的生产构建通过。`git diff --check` 通过。

## 真实浏览器验收

使用独立临时 SQLite、`MODEL_PROVIDER=fake`、`ALLOW_REMOTE_MODEL_CALLS=false`、FastAPI 18001、Vite 15174 和 Edge headless。未使用用户开发数据库，未调用远程模型。

`frontend/scripts/verify-learning-browser.mjs` 通过 Edge DevTools 连接实际页面，不依赖 Playwright 包。运行前需要已启动的测试服务及 Edge（调试端口 19223），设置 `SMOKE_TRANSFER=true` 可验证完整迁移流程。完整流程要求全新的独立测试数据库，脚本不会删除服务端记录。

实际执行：Focus 首页 → 创建会话 → 错误作答 → 诊断追问 → 追问作答 → 第二次步骤派练习 → Inspector 假设/证据 → 刷新恢复 → Demo/Real 隔离 → 浏览器断网 → 原提交与草稿恢复 → 练习通过 → 迁移失败 → 新针对性练习 → 第二道迁移题通过 → 显式结束 → 刷新保留评价。

已查看 1440px 桌面与 390px 窄屏的真实截图。最初捕获图像为黑白色块，随后修复为前台 compositor surface 捕获并重新验证。此处仅代表 Edge headless 的指定视口验收，不代表全部真实设备或浏览器的人工验收。

练习答错、旧题换 ID、并发请求、跨会话键冲突及题库耗尽后的继续干预，主要由领域/API 自动化覆盖，不宣称全部经过浏览器逐项验证。

## 仍未实现

- Live Model 质量与真实教学效果未验证；Fake 只验证系统交互和决策边界。
- 当前规则评价针对配置过的确定性题目，不是任意自然语言或代码语义的完整评估。
- 内容去重只能检测直接相同情境；教学层面的新颖性依赖内容包审查，不是自动语义等价证明。
- 题库耗尽时保留不确定性，尚不自动生成并审校新题。
- 未公开 DecisionEvent 历史接口；刷新后不提供虚构时间线。
- Stage 5C.3B 的复习调度与学习档案前端接入仍待开发。

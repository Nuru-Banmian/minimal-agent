# Issue #8：完整验收报告

验收日期：2026-09-09。规格：[总规格 #1](https://github.com/Nuru-Banmian/minimal-agent/issues/1)、[交付验收 #8](https://github.com/Nuru-Banmian/minimal-agent/issues/8)。前置 #7 本轮读取为 CLOSED。

审阅基线：`e43914454e26b4eba0fbd6561043148412d5280c`。本步分支：`codex/issue-8-acceptance`。新增验收测试和文档，没有修改产品执行逻辑。CLI、`Runtime.run`、工具注册表公共接口为用户确认的测试边界；SQLite 使用临时文件。未跟踪的 `CONTEXT.md` 未修改、未纳入交付。

## 验收结果与证据

| 检查 | 确定结果 | 证据 |
| --- | --- | --- |
| 干净虚拟环境安装 | exit 0 | [安装输出](evidence/issue-8-install.txt) |
| 完整离线测试 | **158 passed, 9 skipped**，83.89s，exit 0；9 项 live 默认跳过，不计通过 | [离线输出](evidence/issue-8-offline.txt) |
| 首次真实 API 整组 | **7 passed, 1 failed**，100.60s，exit 1；失败为新增双窗口用例的姓名断言 | [首次原始记录](evidence/issue-8-live-first-attempt.txt) |
| 修正双窗口测试后 | **1 passed**，20.42s，exit 0 | [双窗口复验](evidence/issue-8-live-windows.txt) |
| 最终双窗口断言（原待办 ID、重启直接回答无工具） | **1 passed**，20.48s，exit 0 | [最终双窗口复验](evidence/issue-8-live-windows-final.txt) |
| 类型/规范/格式、依赖一致性、CLI 配置/启动、离线故障演示 | 全部达到预期退出码；缺配置用例预期 exit 2，其他 exit 0 | [干净目录检查](evidence/issue-8-clean-checks.txt) |
| 仓库内容检查 | 49 个当时的跟踪/拟提交文件、105 个历史 blob 的已配置密钥值匹配为 0；敏感路径为 0 | [扫描范围与结果](evidence/issue-8-repository-check.txt) |

没有把首次整组写成成功：其余 7 项真实测试通过，新增双窗口测试修正后单独复验通过；本轮没有将这些执行记录拼成一次“8 passed”的原始输出。完整离线运行后只调整了显式开启的 live 用例，未改产品和离线测试；最终 live 文件另行复验。

证据中的名字、项目、待办和背景均为测试材料，不读取用户已有聊天数据库。真实模型使用本地已配置的 qwen-plus 阿里云 HTTPS 服务，同步、非流式、`enable_thinking=false`；主请求 HTTP 阶段超时 30 秒，context 使用默认 64000 字节，真实压缩测试显式改为 18000、保留最近 1 turn、摘要 2048 字节、摘要 HTTP 阶段超时 15 秒。密钥仅通过环境交给干净目录中的进程，没有复制私人 `.env`。search→todo 场景强制 `mock`，不代表实时天气或 Tavily 联网结果。

## 干净环境与复现（Windows PowerShell）

本轮将 Git 跟踪文件和本步新增测试复制到新的临时目录，新建虚拟环境，从包索引安装 `.[dev]`，没有复制旧 `.venv`、数据库、日志或 `.env`。这是同一 Windows 主机上的干净目录/虚拟环境验证，不是全新操作系统或 Linux 验证。依赖允许范围安装，实际版本保存在检查证据；项目尚无锁文件，未来安装版本可能变化。

已发布的 [e439144 代码](https://github.com/Nuru-Banmian/minimal-agent/tree/e43914454e26b4eba0fbd6561043148412d5280c)和远程分支 `codex/recovery-trace` 本轮经 GitHub API 与远程 SHA 核对。首次下载：

```powershell
git clone --branch codex/recovery-trace https://github.com/Nuru-Banmian/minimal-agent.git
Set-Location minimal-agent
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
# 在编辑器中填写本地 .env；不要把密钥贴进命令、Issue 或日志。
.\.venv\Scripts\python.exe -m minimal_agent --help
.\start.bat --user-id demo --session-id work --search-provider mock
```

该远程版本尚无 #8 新增文件；以下完整验收在本地交付分支运行，发布后才能从 GitHub 克隆得到本步材料。已有 `.env` 时不要重复覆盖。两个 PowerShell 窗口分别运行：

```powershell
# 窗口 1
.\start.bat --user-id demo --session-id work --db demo.sqlite3 --trace-file logs/work.jsonl --search-provider mock
# 窗口 2（切换到同一项目目录后）
.\start.bat --user-id demo --session-id home --db demo.sqlite3 --trace-file logs/home.jsonl --search-provider mock
```

窗口 1 输入“我叫小林，添加提交青竹报告的待办”，窗口 2 输入“我叫小王，添加购买铅笔的待办”。各自追问“我叫什么？列出我的待办”。输入 `/exit` 后使用相同 user/session/db 重启，追问姓名、查询并完成待办。第三个窗口尝试占用正在运行的相同 user/session 应被拒绝。身份是本地命名空间，不是账户认证。

安装/启动检查以无真实请求的占位配置验证 `.env` 解析、身份显示和 `/exit`；对话恢复的有效性来自下面的离线双进程和真实模型场景，不能由“进程退出码 0”单独证明。

```powershell
# 完整离线测试；不访问公网模型或搜索服务
Remove-Item Env:RUN_LIVE_API, Env:RUN_LIVE_SEARCH -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
# 可解释的离线故障/上限演示：脚本化模型、真实 CLI/SQLite
.\.venv\Scripts\python.exe -X utf8 examples/offline_recovery.py
```

真实验收使用临时数据库；明确开启后会调用配置的模型服务：

```powershell
$env:RUN_LIVE_API = '1'
try {
    .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py tests/test_live_memory.py tests/test_live_acceptance.py -q -s --tb=short
    $liveExit = $LASTEXITCODE
    Write-Output "live_exit=$liveExit"
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

这里不启用 `RUN_LIVE_SEARCH`。Tavily 是用户追加功能，既有独立测试为 `tests/test_live_search.py`；其历史成功记录见开发档案，本次不能当作重新通过。

## 总规格逐项矩阵

下列编号对应 #1 的 16 个 User Stories。自动测试路径均相对仓库根；命令中的 `python` 指 `.\.venv\Scripts\python.exe`。离线证据以真实应用处理脚本化外部 HTTP 响应，不能替代真实模型证据。

| 要求 | 实现 Issue / 版本 | 自动测试 | 演示命令或输入 | 本轮验收依据 |
| --- | --- | --- | --- | --- |
| 1. 普通 Python 主流程，无 Agent 框架 | #2/#3，`7c4ddc5` / `74702c7` | `tests/test_runtime.py` | 阅读 README 架构图和 `Runtime.run` | 代码审阅、pyproject 依赖清单 |
| 2. 终端真实回答 | #2，`d74ad82` | `tests/test_live.py::test_real_cli_remembers_name`；`test_cli_chat_followup_blank_and_exit` | 输入“我叫小林” | live 与 offline |
| 3. 模型决定直接回答或工具 | #3，`89b5a74` | `test_runtime_direct_reply_and_followup`、`test_runtime_executes_real_calculator_before_final_answer` | “你好” / “用计算器计算 12+8” | offline；live calculator |
| 4. 名称/描述/Schema 注册解析 | #3，`74702c7` | `tests/test_tools.py`、`test_runtime_protocol_errors_stop_without_executing` | `python -m pytest tests/test_tools.py tests/test_runtime.py -q` | offline；live Function Calling 协议 |
| 5. 计算与连续追问 | #3，`74702c7` | `test_runtime_continuous_calls_and_followup`；`test_real_calculator_loop_and_followup` | “用计算器计算 (12+8)*3”，再“结果再除以4” | 工具结果 20→60→15、status=ok |
| 6. 模拟搜索明确披露 | #5，`073d4e0` | `test_search_returns_fixed_mock_weather_through_runtime`、`test_search_no_match_is_explicit` | “查上海的示例天气” | offline；live 明确 mock=true/模拟/非实时 |
| 7. 待办增查改与追问 | #5，`073d4e0` | `test_todo_completion_is_isolated_idempotent_and_durable` | “添加带伞待办”“列出待办”“把带伞那项完成” | offline；live added/listed/completed |
| 8. 一次请求 search→todo | #5，`073d4e0` | `test_search_to_todo_chain_survives_restart`；`test_real_search_todo_sessions_and_clarification` | “查上海的示例天气，帮我记一个带伞的待办” | live 验证 search 成功先于 todo added |
| 9. 双窗口隔离 | #4，`2b42622` | `test_two_cli_processes_alternate_conflict_and_recover`；`tests/test_live_acceptance.py` | 上述两个窗口命令 | 同时存活的两个 CLI，姓名/待办互不串用 |
| 10. 关闭重启恢复 | #4，`2b42622` | `test_cli_displays_identity_and_restores_session`；`test_real_cli_sessions_resume` | `/exit` 后按相同身份重启 | live 四个独立进程计算 20→10、38→19；新双窗口测试重启 |
| 11. 对话与工具追问 | #4/#5 | `tests/test_sessions.py`；`test_real_cli_remembers_name` | “我叫什么？” / “结果再除以2” | offline 完整历史；live 事实和工具结果 |
| 12. 压缩旧内容保留事实/待办 | #6，`6dfbed2` | `tests/test_memory.py`；`tests/test_live_memory.py` | `python -m pytest tests/test_live_memory.py -q -s`（需显式开关） | live memory_compacted 后事实召回与完成原待办 |
| 13. 上限/报错/继续 | #7，`bf29726` | `tests/test_recovery.py`、`test_runtime_default_limit_counts_corrections_and_allows_next_turn` | `python examples/offline_recovery.py` | offline 故障注入，含 8 步/恢复/部分成功 |
| 14. 请求/调用/结果/停止 trace | #7，`bf29726` | `test_cli_jsonl_trace_is_bounded_redacted_and_complete`、`test_summary_trace_counts_actual_requests_and_compression` | 启动时 `--trace-file logs/demo.jsonl` | offline 字段/计数/脱敏；live 真实 trace |
| 15. 自动测试与真实证据 | #8，本步 | 本报告全部命令 | 完整离线与真实分开执行 | 下附原始退出码和数量，失败保留 |
| 16. Issue/版本/Prompt/问题记录 | #2–#8 | 文档与 Git 历史人工核对 | [Prompt 索引](prompts.md)、[开发档案](development-history.md) | 仅记录发生过的输入；缺少的公开审阅材料列在下方 |

额外实施约束对应关系：

| 约束 | 自动测试 / 文档 |
| --- | --- |
| content+tool_calls 继续循环；空 content 可调用；同响应多调用按序匹配 ID | `test_runtime_multiple_calls_pair_errors_and_success_in_order`、`test_runtime_executes_real_calculator_before_final_answer` |
| 不同 user 同名 session 隔离，拒绝模型注入身份，同 session 拒绝并发写 | `tests/test_sessions.py`、`test_summary_isolated_by_user_and_session` |
| system / 历史摘要 / 近期完整 turn / 当前调用取舍；todo 按需召回 | README Memory 表；`test_compression_restores_summary_and_recent_turn_after_restart` |
| 当前 turn 不摘要，工具调用与结果成对，大工具结果投影但保留原始历史 | `test_current_tool_turn_is_not_compressed_on_overflow`、`test_large_tool_result_is_bounded_but_raw_history_survives` |
| 一轮最多一次额外摘要，独立输入/输出/超时，失败不破坏历史 | `test_failed_summary_keeps_all_history_and_only_attempts_once`、`test_already_compacted_turn_does_not_make_second_summary_request` |
| 预算含 Schema、输出预留；不可压缩时明确失败 | `test_tool_schema_is_included_in_budget`、`test_irreducible_context_reports_error_without_committing_summary` |
| 错误分类/纠错受上限约束/HTTP 不重试/待办事务与恢复一致性 | `tests/test_recovery.py`、`tests/test_client.py` |
| 无密钥、私人数据库/聊天、虚拟环境进入交付 | 下方仓库检查说明与检查证据 |

## 限制与尚未完成项

- [ ] #8 新增提交尚未推送。远程 main 为 `b69943c`（#6），`codex/recovery-trace` 为 `e439144`（#7）。本地完成不等于 GitHub 已发布；最终代码发布需后续用户授权。
- [ ] 等待用户审阅最终差异与报告，#8 和总规格 #1 保持打开，不自动合并 main。
- [ ] 完整用户审阅对话没有导出到 GitHub。旧文档中记录的确认和审阅摘要不等于逐字聊天记录；#7/#8 本轮读取均无 Issue 评论。后续只能发布实际存在且获准公开的记录，不能补造。
- [ ] 本次未重新验收真实 Tavily；模拟天气始终不是实时信息。

真实验收是有限样本。名字、数值、对象 ID、工具状态、调用次序和压缩事件是断言依据，不固定整句模型措辞。自然语言仍可能遗漏要求或增加无依据细节：例如本轮压缩后回答把“周五交”扩写成“本周五下班前”，并附加不必要的权威核验提示。测试验证关键事实与待办能力，不证明生成文本毫无偏差。摘要可能丢失细节且没有全文检索；用户标识不提供认证；HTTP 阶段超时不是整轮墙钟截止时间。

仓库扫描仅证明所检查范围：当前跟踪内容、本步拟提交文件、Git 可达历史中的敏感文件路径及已配置密钥值。它不是通用秘密检测器，也不等于人工审阅了所有历史文本。日志只保留合成测试材料和脱敏 trace。

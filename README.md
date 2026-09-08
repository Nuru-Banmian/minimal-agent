# 最小 Agent

一个用于学习 Agent 运行原理的 Python 命令行项目：直接调用 Qwen 的 OpenAI 兼容接口，自行实现工具循环、SQLite session 隔离和长对话压缩，不依赖 Agent 框架。

当前支持普通对话、calculator 四则运算、mock/Tavily 搜索、持久 todo，以及 Issue #6 的基础 session memory。同步、非流式；模型显式返回的行动说明可以出现在 trace 中，但不读取或展示隐藏推理。

## 安装与启动

需要 Python 3.11+。在项目根目录的 PowerShell 执行（已有 `.venv` 时跳过创建）：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`，填写 `LLM_BASE_URL`、`DASHSCOPE_API_KEY`，核对 `LLM_MODEL`。地址从账号控制台获取，应包含 API 版本路径，不包含 `/chat/completions`，且与密钥地域、业务空间匹配。API 参数参考[阿里云官方接口文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。不要提交密钥。

```powershell
.\start.bat --user-id demo --session-id work
```

Windows 可以双击 `start.bat`，默认打开 `local/default`。脚本自动进入项目目录，以 `.venv` 和 UTF-8 启动。也可以直接运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m minimal_agent --user-id demo --session-id work
```

Linux/macOS 使用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -e '.[dev]'` 和 `.venv/bin/python -m minimal_agent`。实际运行验证在 Windows 完成。

程序只加载**当前工作目录**的 `.env`，已有环境变量优先（包括显式空值），不展开变量引用。`start.bat` 会先切到项目根目录。

## 试一轮对话

```text
我叫小林，项目代号是青竹，周五交报告，不安排周末工作。
12 加 8，再将结果乘以 3。
给我加一个提交青竹报告的待办。
列出我的待办。
把提交青竹报告那一项完成。
/exit
```

用同一启动命令重新进入，再问“我叫什么，哪天交报告？”即可恢复该 session。另开终端时使用不同 `--session-id`，其消息、摘要和待办独立。

- 空输入跳过；`/exit`、`/quit`、EOF 或 Ctrl+C 退出。
- `--db` 指定 SQLite 文件，默认当前目录 `agent.sqlite3`；`:memory:` 仅用于临时演示，退出即消失。
- 同一 session 同时只允许一个运行者，第二个终端会报告占用；退出或进程结束后操作系统释放锁。
- `user_id` 是本地命名空间，**不是认证**。能够访问数据库并知道标识的人可以读取对应会话。

## 工具

| 工具 | 行为 |
| --- | --- |
| `calculator` | add/subtract/multiply/divide，校验数值参数，不执行任意表达式代码 |
| `search` | 默认 mock；可选 Tavily 联网搜索，返回来源与摘要 |
| `todo` | add/list/complete；应用注入当前身份，模型不能指定其他 user/session |

mock 搜索只有固定的 **2026-09-01 上海小雨、22–27°C、建议带伞** 教学资料。输入“查上海的示例天气，帮我记一个带伞的待办”。回复必须说明模拟、非实时；无命中与搜索失败分别报告。

要联网搜索，配置：

```dotenv
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=你的密钥
```

再运行 `.\start.bat --search-provider tavily`，输入“搜索 Python 官方文档并添加一个阅读文档的待办，回答附来源链接”。命令行参数覆盖环境配置；`--search-provider mock` 切回模拟。缺少 Tavily 密钥会报错，不自动退回 mock。

Tavily 请求使用 basic 模式、最多 5 条结果，不请求全文或服务商生成的答案；10 秒 HTTP 阶段超时、响应体上限 1 MB，标题/摘要分别最多 300/2000 字符并标记裁剪。网页内容是外部资料，不能更改工具权限。联网结果也不保证实时。

完成待办前模型需 list 当前 ID；目标缺失或歧义时先澄清。SQL 强制身份隔离，complete 重复执行返回 already_completed，未知 ID 返回 not_found。自然语言歧义识别依赖模型；没有宣称其永远准确。

## 一次 turn 如何运行

每条用户输入是一个 turn；其中每次主模型请求是一个 step，默认最多 8 次。执行顺序：

1. 从 SQLite 读取当前 session 摘要与未覆盖的完整历史，准备 context。
2. 检查预算；必要时用一次独立模型请求摘要旧的完整 turn。
3. 将 system、历史摘要、近期消息、当前输入和工具 Schema 发送给模型。
4. 若返回 tool_calls，校验参数并按顺序执行，将带匹配 tool_call_id 的结果放回 context。下一次请求前再次检查预算。
5. 无 tool_calls 且有完整文本答案时结束，将当前 turn 的原始消息在事务中保存。

有 content 且有 tool_calls 时，content 只是行动说明，不能提前当成最终答案。工具错误可以让模型在剩余 steps 内纠正。`trace` 输出 model_request、action、tool、stop；压缩增加 `purpose=summary` 的 model_request 和 memory_compacted。每轮数全部 model_request 即实际尝试次数，最多 **8 次主请求 + 1 次摘要请求**，不自动重试。

## Memory：保存什么，什么时候召回

| 信息 | 存储 | 召回时机 | 放入 context 的位置与取舍 |
| --- | --- | --- | --- |
| 应用指令 | Runtime 代码 | 每次请求 | 最前面的 system；不从摘要生成 |
| 完整成功历史 | SQLite `messages` | 每 turn 读取摘要边界之后的消息 | 保留近期完整 turn；已覆盖原文不再发送，但仍存数据库 |
| 旧对话摘要 | SQLite `memories`，含 covered 序号 | 每 turn，按 user/session 读取 | system 后的 **user 历史资料消息**；不授予 system 权限 |
| 结构化待办 | SQLite `todos` | 模型调用 todo 时 | 作为 tool 结果返回；不自动读取所有 session 或整库待办 |
| 当前 turn | 运行内存，成功后保存 | 当前工具循环持续使用 | 始终保留，不能被摘要；调用与结果成对 |

默认数据库位于启动目录，`start.bat` 启动时即项目根目录；三个表共用同一 SQLite 文件。消息、摘要、待办均按 `(user_id, session_id)` 隔离。数据库明文保存数据，`.locks` 相邻目录保存占用锁文件；不要在运行时删除锁文件或使用硬链接别名绕过锁。本方案面向本机文件系统。

摘要只覆盖较旧的**完整 turn**。默认至少保留最近 2 个完整 turn，不拆开 assistant tool_calls 和 tool 结果。压缩输入包含旧摘要及新增的旧 turn；当前问题和当前工具循环不进入摘要。摘要须为非空文本、无工具调用且在字节上限内，并且新 context 能装下，才事务更新摘要与覆盖边界。重启后从边界继续，不重复摘要已覆盖内容。

若在工具循环中才超预算，且本轮尚未摘要，仍可压缩已存储的旧 turn；最多一次，不压缩当前 turn。大工具结果在进入 context 前转换为带 `truncated: true` 和 `preview` 的有界 JSON。数据库保留**裁剪前**的工具结果；旧工具结果召回与摘要前也经过裁剪。预览可能不含完整 ID 或全部条目，不能当作完整清单。

简单摘要可能遗漏细节、时间关系或精确措辞；多次摘要还会累积误差。它没有全文检索或自动找回已覆盖原文的能力，重要事实应由用户复核，待办状态应以 todo 为准。大量待办超过裁剪限额时也可能无法靠当前 list 接口完整处理；本步未增加分页或向量检索。

## 预算与配置

**这里的输入预算是 UTF-8 字节近似，不是精确 token 计数。** 主请求判定公式：

```text
UTF8字节数(JSON紧凑序列化({messages, tools})) + 4 × MEMORY_OUTPUT_TOKENS
    <= MEMORY_CONTEXT_BYTES
```

messages 已包含 system、摘要、近期完整消息与当前工具循环，tools 是全部工具 Schema。`4 × 输出 token` 是工程预留比例，不是 tokenizer 换算保证；阈值需按所选模型保守设置。主请求和摘要请求都发送 `max_tokens` 限制输出，服务商的真实 token 窗口仍可能拒绝请求。

| 环境变量 | 默认 | 含义 |
| --- | --- | --- |
| `LLM_MODEL` | 示例 qwen-plus | 必填模型名 |
| `LLM_BASE_URL` | 无 | 必填兼容 API 根地址 |
| `DASHSCOPE_API_KEY` | 无 | 必填模型密钥 |
| `LLM_TIMEOUT_SECONDS` | 30 | 主模型 HTTP 各阶段超时秒数 |
| `SEARCH_PROVIDER` | mock | mock 或 tavily |
| `TAVILY_API_KEY` | 无 | 仅 tavily 必填 |
| `MEMORY_CONTEXT_BYTES` | 64000 | 主请求预算，含输出预留 |
| `MEMORY_OUTPUT_TOKENS` | 1024 | 主请求与摘要请求的 max_tokens |
| `MEMORY_KEEP_RECENT_TURNS` | 2 | 不参与摘要的最近完整 turn 数，至少 1 |
| `MEMORY_SUMMARY_BYTES` | 4096 | 摘要文本 UTF-8 字节上限 |
| `MEMORY_SUMMARY_INPUT_BYTES` | 256000 | 摘要请求 messages 序列化的独立输入上限，另有输出 token 上限 |
| `MEMORY_SUMMARY_TIMEOUT_SECONDS` | 15 | 摘要 HTTP 各阶段独立超时，不是整个请求的绝对总时限 |
| `MEMORY_TOOL_RESULT_BYTES` | 8000 | 单条 tool content 字节上限，含裁剪标记，最小 64 |

所有整数配置必须为正数，context 必须大于输出预留；超时必须为正有限数。CLI 从环境读取，代码调用可传 `Runtime(..., memory=MemorySettings(...))`。

## 失败如何处理

配置错误退出码 2。模型鉴权、限流、网络、超时或协议错误给出安全提示，CLI 可继续输入。摘要失败、空摘要、过长摘要或压缩后仍超预算时，旧摘要/边界和原始历史不被更新；不静默丢弃用户问题，也不自动重试。

当前输入、Schema、保留的近期 turn 或工具循环不可缩减时明确报“过长”；缩短请求、调整预算或换 session 后再尝试。摘要输入超过独立预算也明确报错。本轮如果已经成功更新摘要，但后续模型失败，该有效摘要可以保留，原始历史仍在。

失败 turn 不写消息历史，但此前执行成功的 todo 已独立提交，不会回滚。请先查询状态再重试，add 不保证重试幂等。CLI 会给出这一提示。正常退出码 0 只代表进程正常结束，不代表期间每一轮都成功。

## 测试与真实演示

默认离线测试通过本机回环 HTTP 脚本化外部模型响应，使用真实 Runtime、CLI、SQLite 和 calculator/todo。联网搜索的离线测试仅替换外部搜索 HTTP，不能视为真实 Tavily 验收。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

运行前确保没有遗留的 `RUN_LIVE_API` 或 `RUN_LIVE_SEARCH` 环境变量。真实长对话演示显式启用，使用临时数据库，不修改已有待办：

```powershell
$env:RUN_LIVE_API = '1'
try {
    .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live_memory.py -q -s --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

演示使用真实 Qwen API、Runtime 与 todo，逐轮重新打开 session，加入长背景触发压缩，再追问“小林/青竹/周五/周末约束”，查询并完成原待办。它验证关闭重开 Runtime 的恢复；独立 CLI 子进程恢复另有既有 session 测试。本测试不调用搜索服务。其输出含实际测试 Prompt 和 trace，不含密钥。

| Issue #6 验收项 | 证据 |
| --- | --- |
| 可调预算、读取 memory、近期保留、重启不重复摘要 | `test_compression_restores_summary_and_recent_turn_after_restart` |
| 完整工具配对、失败/空/超长/超时、最多一次摘要 | `test_failed_summary_keeps_all_history_and_only_attempts_once` |
| user/session 摘要隔离 | `test_summary_isolated_by_user_and_session` |
| 工具裁剪标记、原始工具历史保留 | `test_large_tool_result_is_bounded_but_raw_history_survives` |
| 当前输入过长、近期不可缩减、摘要独立预算 | CLI 过长测试和 `test_irreducible_context_reports_error_without_committing_summary` |
| 当前 turn 不摘要，工具增长可压缩旧 turn | `test_current_tool_turn_is_not_compressed_on_overflow`、`test_tool_growth_can_compress_old_turns_once_without_splitting_current` |
| 压缩后的事实追问和 todo 操作 | `tests/test_live_memory.py`，真实 API 记录见下 |
| 存储、召回位置、信息取舍及局限 | 本 README 的 Memory 和预算章节 |

其他真实测试：`tests/test_live.py`（模型、CLI、calculator、session、mock search/todo）；`tests/test_live_search.py` 使用 `RUN_LIVE_SEARCH=1` 验证真实 Tavily。只执行与此次改动相关的真实演示；未运行项不能算作此次通过。

## 本次开发记录与代码导读

实际用户 Prompt：`[$implement](C:\Users\1\.agents\skills\implement\SKILL.md) #6`，随后确认 Runtime.run/CLI 测试边界及审阅基点 `240eaa1f3b0606a48a92d4b958998f3fea2efe8d`，追加“做完后readme重写一下”。Issue #5 开始时已关闭，本次使用独立分支 `codex/session-memory`。既有未跟踪 CONTEXT.md 保留，不纳入提交。

TDD 先观察缺少 memory 模块的失败，再实现压缩/重启；工具原始结果超过 400 字节的测试失败后增加 context 投影；CLI 忽略 MEMORY_CONTEXT_BYTES 的测试失败后接入环境配置。首次真实演示通过事实追问，但 todo 工具结果使 context 超预算，导致失败；增加“本轮尚未摘要时可压缩旧 turn”的回归测试并修复，仍不拆开当前调用与结果。Ruff 提示导入/格式问题后统一调整，mypy 检查源文件类型。

- [首次真实运行记录](docs/evidence/issue-6-live-first-attempt.txt)：如实保留失败。
- [后续真实运行记录](docs/evidence/issue-6-live.txt)：真实模型输出及测试结果。
- [旧步骤开发与验收档案](docs/development-history.md)：重写前 README 原文，仅作为当时记录，其中阶段描述、计数和状态不代表当前实现。

阅读顺序：`cli.py` 输入输出 → `runtime.py` turn/step 与压缩决策 → `memory.py` 字节预算及 context 投影 → `sessions.py` SQLite/占用锁 → `tools.py` 注册与执行 → `client.py` HTTP 协议。`config.py` 加载模型配置，`search.py` 实现模拟/联网搜索。

Issue #6 保持打开等待审阅；不自动进入下一 Issue，不推送或合并 main。

真实验收：2026-09-08 10:43:10 UTC 开始，qwen-plus，1 passed in 21.78s。首次运行 1 failed in 14.53s，失败点和修复见上，未记为通过。

本次全量离线结果：**138 passed, 8 skipped in 67.80s**；8 项需显式开启的真实测试默认跳过，本步真实 memory 演示已单独通过。mypy 检查 10 个源文件通过，Ruff 检查及全部 29 个 Python 文件格式检查通过，`git diff --check` 通过。

双轴只读审阅范围：`git diff 240eaa1f3b0606a48a92d4b958998f3fea2efe8d...6dfbed2`。Standards：0 项规范违反或需修改的代码异味；Spec：0 项缺失、范围外或错误实现。两个子代理分别核对规范与 Issue #6/#1，审阅后仅补充本段验证记录。

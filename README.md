# 最小 Agent：持久化独立 session

当前实现 [Issue #4](https://github.com/Nuru-Banmian/minimal-agent/issues/4)：按 user_id 与 session_id 隔离 SQLite 历史，支持退出后继续对话和 calculator 追问。本步保持 Issue 打开供审阅，不进入下一步。

## 安装与启动

已安装依赖并填写 `.env` 后，Windows 可直接双击项目根目录的 `start.bat`，或在 PowerShell 执行 `.\start.bat`。脚本会自动切到项目目录、使用 `.venv` 和 UTF-8 启动；启动失败时保留窗口供查看错误。输入 `/exit` 或 `/quit` 退出聊天。

支持 Python 3.11+；实际验证环境为 Windows、Python 3.13.5。使用 HTTPX 直接发送 HTTP，方便观察消息协议；python-dotenv 加载本地配置，不使用 Agent 框架。

在项目根目录的 PowerShell 中执行，无需激活虚拟环境：

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑项目根目录的 `.env`，填写 `LLM_BASE_URL` 和 `DASHSCOPE_API_KEY`，核对模型名称后保存。已有 `.env` 无需重新复制，然后启动：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m minimal_agent
```

若已创建 `.venv`，可跳过第一条命令。已安装的其他支持版本可替换 `-3.13`。安装后也可运行 `.\.venv\Scripts\minimal-agent.exe`。Linux/macOS 使用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -e '.[dev]'`，在环境中配置同名变量后运行 `.venv/bin/python -m minimal_agent`。

程序启动时自动加载当前工作目录的 `.env`（支持 UTF-8 BOM），不向父目录搜索文件；已有环境变量优先，包括显式空值。不展开配置中的变量引用。请从项目根目录启动。API key 只填写到本地 `.env`，不写入命令历史、README 或提交材料。`.gitignore` 忽略真实密钥配置文件、虚拟环境、数据库及日志，只有无密钥的 `.env.example` 入库；程序创建 SQLite 数据库和相邻的 `.locks` 目录，不创建日志文件。

| 环境变量 | 含义 |
| --- | --- |
| `LLM_MODEL` | 必填；候选 `qwen-plus`，以该账号可用模型为准 |
| `LLM_BASE_URL` | 必填；与 API key 的地域、业务空间匹配，包含 API 版本路径，不包含 `/chat/completions` |
| `DASHSCOPE_API_KEY` | 必填；百炼 API key |
| `LLM_TIMEOUT_SECONDS` | 可选，默认 30；正有限数，HTTP 连接及读写等各阶段的超时秒数，不是整个 turn 的总时限 |

2026-09-07 核验官方文档：北京示例为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，新加坡示例为 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`，必须将占位符替换为实际业务空间 ID，最终以账号控制台为准。不自动猜测地域。来源：[首次调用](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)、[国际站接口文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)。

官方 [Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling) 列出 Qwen-Plus 系列支持工具调用。本步固定发送 `stream: false`、`enable_thinking: false`，不依赖隐藏推理内容。2026-09-07 配置后已实测当前账号的 `qwen-plus` 普通对话、追问与原生 Function Calling；结果见下方验收记录。

## 使用与错误行为

启动后依次输入 `我叫小林`、`我叫什么`，模型应利用当前 session 的历史回答姓名。回答文本由模型生成，不保证逐字一致。

- 空输入或纯空白：跳过，不请求模型。
- `/exit`、`/quit`（不区分大小写）、EOF 或 Ctrl+C：结束进程，释放会话占用；已成功保存的历史保留。Windows EOF 为 Ctrl+Z 后回车，Linux/macOS 为 Ctrl+D。
- 配置缺失或无效：向 stderr 输出清楚提示，退出码 2，不请求模型。
- 鉴权失败、权限不足、限流、服务错误、连接失败或超时：向 stderr 输出安全提示，不输出服务端原始异常、密钥或堆栈，可继续输入。
- 请求失败或返回不完整/空白/畸形协议内容：不把它显示为成功回答，不将该轮问答写入历史，之前成功历史保留。需要重新输入失败的问题。
- 正常结束退出码 0；即使期间某轮失败，随后正常退出仍为 0。脚本验收真实请求成功应使用下面的显式真实 API 测试。

请求没有自动重试；HTTP 客户端不读取系统代理环境变量。当前历史随成功轮次增长，每 turn 最多 8 次主模型调用；已做 SQLite 持久化，尚未做压缩或跨 turn 总调用预算。

## 一次请求如何工作

`messages` 是按时间顺序排列的上下文：`system` 放应用指令，`user` 放用户输入，`assistant` 放已成功返回的模型答案。第二个问题的请求结构相当于：

```json
[
  {"role": "system", "content": "你是一个友好的中文助手。"},
  {"role": "user", "content": "我叫小林"},
  {"role": "assistant", "content": "你好，小林！"},
  {"role": "user", "content": "我叫什么"}
]
```

这是协议说明示例，不是真实 API 运行记录。服务端模型不会自动记住客户端未发送的历史；追问能回答，是因为 CLI 每次重新发送之前的成功问答。保存历史与发送 context 是两件事：SQLite 负责跨进程保留完整的成功 turn；Runtime 每次 turn 都按应用提供的 user_id/session_id 读取有序历史，把 system 指令放最前，再追加当前输入并重新发送给模型。保存但不发送的内容，模型无法用于追问。本步发送当前 session 的全部成功历史，后续再引入压缩。

代码阅读顺序：

1. `src/minimal_agent/config.py` 加载当前目录 `.env`，以已有环境变量优先，读取并校验配置。
2. `src/minimal_agent/cli.py` 负责输入输出和显示 trace，调用公共 `Runtime.run(text)`。
3. `src/minimal_agent/client.py` 负责 HTTP 请求、协议解析、错误转换；它不会自动保存历史，也不会执行工具。

4. `src/minimal_agent/runtime.py` 区分外层 turn 与内层 step，回填工具结果并判断继续或停止；只有完成的 turn 才进入历史。
5. `src/minimal_agent/tools.py` 注册工具，启动时检查 JSON Schema，执行前解析 JSON 并校验参数，调用真实 Python 四则运算函数。
6. `src/minimal_agent/sessions.py` 负责会话占用和 SQLite 有序消息读写。

## 测试与验收

默认测试使用本机回环 HTTP 服务模拟外部模型，CLI 测试运行真实 Python 子进程；不替换 CLI 或客户端内部逻辑，不需要密钥，也不访问公网。

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m mypy
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

如终端之前开启过真实验证，默认离线运行前执行 `Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue`。

配置真实账号后，可单独执行真实客户端两轮对话、真实 CLI 两轮对话及一次 Function Calling 协议探测（共五次模型请求，会消耗模型额度）：

```powershell
$env:RUN_LIVE_API = '1'
try {
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py -q -s -k "not calculator and not sessions_resume" --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

真实测试验证客户端与 CLI 追问能返回“小林”，只打印时间、模型和匹配结果，不打印 key 或原始响应。Function Calling 测试向真实服务发送 `echo_name` Schema 并强制选择该函数，检查返回的调用 ID、函数名及 JSON 参数，不执行工具，也不实现下一步 Runtime。实测 Qwen 强制工具调用可能返回 `finish_reason=stop`，因此按实际 `tool_calls` 校验，不能只靠结束标记判断有无工具调用。未显式开启时所有真实测试跳过（当前共五个），开启后配置错误或请求失败会失败，绝不切换到替身。

### Issue #2 验收证据（2026-09-07）

| 验收项 | 对应证据 | 状态 |
| --- | --- | --- |
| 最小 Python 项目、安装与启动命令 | `pyproject.toml`；可编辑安装成功；CLI 子进程测试 | 已完成 |
| 配置、忽略文件、账号模型及 Function Calling 支持 | 配置与协议离线测试；`test_real_api_supports_function_calling` | 已完成，当前账号实测通过 |
| 同步聊天、追问、空输入和退出 | `test_cli_chat_followup_blank_and_exit`；`test_cli_clean_exit_without_requests` | 离线已完成 |
| 配置、鉴权、超时提示 | `test_client_reports_safe_http_errors`；超时及 CLI 失败恢复测试 | 离线已完成 |
| 客户端协议与 CLI 冒烟 | `tests/test_client.py`、`tests/test_cli.py` | 离线已完成 |
| 真实 API 对话与追问、脱敏记录 | `test_real_api_remembers_name`、`test_real_cli_remembers_name` | 已完成：`qwen-plus` 两条路径均正确返回姓名 |
| 历史与原理说明 | 本 README“一次请求如何工作” | 已完成 |

初次实现全量结果：`39 passed, 1 skipped`（17.09 秒，当时尚无配置，真实 API 跳过）；mypy 检查 5 个源文件通过，Ruff 静态检查和格式检查通过，`git diff --check` 通过。安装生成的 `minimal-agent.exe` 在无配置时显示缺失的三个变量名称；`git check-ignore` 确认密钥文件、虚拟环境、数据库与日志路径均被忽略。

配置后的真实验证（2026-09-07）：客户端两轮测试 `1 passed`（1.71 秒，08:43 UTC）；真实 CLI 两轮与正常退出通过；Function Calling 最终 `1 passed`（1.27 秒），模型均为 `qwen-plus`，姓名匹配“小林”，函数 `echo_name` 与 JSON 参数匹配，调用 ID 非空。期间首次 Function Calling 测试因只接受 `finish_reason=tool_calls` 而失败；安全诊断确认实际为 `stop`，修正检查后重跑通过。以上为实际 API 返回的脱敏结论，未记录密钥、完整地址或原始响应。这是 Issue #2 当时的验收记录；本次开始时已确认它已关闭。

补充实现后的离线全量结果：`41 passed, 3 skipped`（19.07 秒，三个真实测试已在上面独立运行验证）；mypy、Ruff 静态与格式检查、`git diff --check` 通过。

## 实际 AI Prompt 与问题记录

- 实际用户输入：`[$implement](C:\Users\1\\.agents\skills\implement\SKILL.md) #2`。
- 实际审阅基点回复：`使用 cbd7e7c`。实现依据为读取到的 Issue #2 及父 Issue #1，不补造额外用户指令。
- 开发过程：先写客户端 HTTP 成功用例，确认缺少模块导致失败，再实现请求；随后添加失败响应、超时、CLI 追问和错误恢复用例并逐步通过。
- 遇到的问题：首次安装尚未结束时测试提示包不存在；等待安装成功后重跑，确认失败点变为待实现的客户端模块。Windows 的回环连接失败测试使用过短超时会先触发连接超时，调整为足够等到连接拒绝的 3 秒；读取超时另用延迟 HTTP 响应确定性验证。
- 初次配置检查仅查看变量名称/是否存在，没有读取或输出任何真实密钥；当时没有可用配置，因此没有真实 API 演示。后续用户填写本地 `.env` 后，程序读取配置并完成了上述真实验证，未将密钥输出或入库。离线脚本化回复不能作为真实模型可用性的证据。
- 实际审阅任务：以 `git diff cbd7e7c...HEAD` 审阅实现提交 `7c4ddc5`，两个只读子代理分别检查仓库规范与代码异味、Issue #2 及父 Issue #1 的需求覆盖。Standards：0 项发现；Spec：0 项代码问题、1 项已知待验证验收（真实账号可用性及 Function Calling）。未将待验证项记为通过。
- 后续实际用户输入：“你帮我创建一个.venv文件让我填写”“填好了”。创建了 `.env` 配置文件，随后补充自动加载、已有环境变量优先、UTF-8 BOM 测试，并完成真实 API 验证；未实现下一步工具循环。
- 配置接入后，以同一基点复审至 `d74ad82`：Standards 0 项发现；Spec 0 项发现，上轮真实账号待验证项已补齐。复审只读取提交差异，不读取 `.env`，不重复付费请求。


## Issue #3：使用、协议与验收

工具使用规则：现有工具能完成的任务或子任务必须调用工具，包括简单四则运算和追问中的计算；依据实际结果回答，失败时不得编造结果。不涉及工具能力的普通对话可直接回答。这条规则通过 system 指令交给模型遵守，当前没有应用层的语义检查来保证模型始终调用工具。

本规则来自用户追加指令：“给一个限制，就是能用工具的必须用工具”。修改后 Runtime 离线测试 25 项通过；2026-09-07 真实模型输入 `1+1等于多少？`，确认调用 calculator 并得到 2。该实测说明本次遵守规则，不代表模型在所有输入下都必然遵守。

更新依赖后照常运行 `start.bat` 或 `python -m minimal_agent`，输入 `用计算器计算 (12+8)*3`，再输入 `结果再除以 4`。CLI 默认在 stdout 输出 JSON trace，包含 turn、step、工具名称、原始 arguments JSON、调用 ID、状态、结果和停止原因。模型可直接回答，也可返回简短行动说明；不请求、展示或回灌完整隐藏思维链。trace 会显示本轮工具参数，适合本地学习，程序不自动写日志文件。

`calculator` 参数为 `operation`（`add`、`subtract`、`multiply`、`divide`）、`a`（左操作数）、`b`（右操作数）。不接受额外字段、字符串数值、布尔值、非有限数值、除零或任意表达式代码；不用 `eval`。采用 Python 数值运算，浮点数可能有通常的精度误差。

Runtime 每步发送注册信息，由模型的 `tool_calls` 决定路径，没有关键词路由。一个 assistant 消息先完整加入上下文，然后串行执行其全部调用；每条 tool 消息用 `tool_call_id` 配对，并以 JSON 返回 `status: ok/result` 或 `status: error/error`。即使同时有 content，仍继续工具循环。未知工具和非法参数回填错误，模型可在下一步修正；修正请求也计入默认 8 次上限。第 8 步有最终答案可成功，否则回填该步结果后停止并报告未完成，不额外请求第 9 次。当前 calculator 无外部副作用，失败 turn 整体不写入历史。

协议转换手写实现；无答案且无调用、重复调用 ID、缺失名称/ID、非字符串 arguments 或被截断的响应均报告协议错误。JSON arguments 的解析及 Schema 校验由注册表在实际执行前完成。注册表使用 JSON Schema Draft 2020-12；重复名称和无效 Schema 在注册时抛出异常，默认注册发生在 CLI 接受输入之前。

协议参考已于 2026-09-07 再次核对：[阿里云 Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)。`stop` 和 `tool_calls` 结束标记都可能携带有效调用，实际路径以解析后的调用列表为准。

### 真实 API 证据

显式运行本步演示（会消耗模型额度；没有配置会失败）：

```powershell
$env:RUN_LIVE_API = '1'
try {
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py -q -s -k calculator --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

2026-09-07 09:02:06 UTC，真实 `qwen-plus`，公共 Runtime + 真实 calculator：`1 passed, 3 deselected`（4.57 秒）。实际两条用户输入就是上述计算与追问；模型回答分别包含 60、15，不断言固定措辞。下面是实际事件的摘录，省略调用 ID，仅为易读性缩短字段：

| turn | step | 实际事件 | 结果/停止原因 |
| --- | --- | --- | --- |
| 1 | 1 | model_request；calculator add(12,8) | ok，20 |
| 1 | 1 | 同一响应第二个调用：calculator multiply(20,3) | ok，60 |
| 1 | 2 | model_request；stop | final_answer |
| 2 | 1 | model_request；calculator divide(60,4) | ok，15.0 |
| 2 | 2 | model_request；stop | final_answer |

共 4 次模型请求、3 次真实工具执行。第一响应一次提出两个调用，不代表模型在加法结果返回后才提出乘法；连续两次决策读取前次结果的路径另由确定性离线测试验证。离线模型是回环 HTTP 脚本化服务，Runtime 和 calculator 均是真实实现；只有注册表“执行前拒绝”测试使用记录调用的测试函数。

| Issue #3 验收项 | 证据 |
| --- | --- |
| 唯一名称、描述、Schema、执行函数；重复/无效定义拒绝 | `tests/test_tools.py` 注册表公共接口测试 |
| 注册信息发送模型、直接回答及追问 | `test_runtime_direct_reply_and_followup` |
| 手写协议解析、执行前参数校验 | `test_runtime_protocol_errors_stop_without_executing`、注册表测试 |
| calculator 四则运算、非法数值、除零 | `test_real_calculator_through_registry`、`test_runtime_bad_arguments_can_be_corrected` |
| 单次/连续/多调用、调用 ID 配对 | `tests/test_runtime.py` 中三个对应循环测试 |
| content 与调用并存、空答案协议错误 | `test_runtime_executes_real_calculator_before_final_answer`、协议错误测试 |
| 默认 8 次上限且计入修正轮次 | `test_runtime_default_limit_counts_corrections_and_allows_next_turn` |
| turn/step/参数/状态/停止原因 trace | Runtime trace 断言、`test_cli_calculator_loop_and_trace` |
| 公共 Runtime 离线覆盖且执行真实 calculator | `tests/test_runtime.py` |
| 真实模型计算与追问 | `test_real_calculator_loop_and_followup`，上述真实记录 |

### 本步实际 Prompt 与开发记录

- 实际用户输入：`[$implement](C:\Users\1\.agents\skills\implement\SKILL.md) #3`。实现依据为 Issue #3 与父 Issue #1，公共测试边界采用父 Issue 已指定的 Runtime、CLI、注册表及客户端 HTTP。
- 先运行直接回答测试，确认缺少 Runtime 模块导致失败；实现后通过。随后单调用测试因旧解析器拒绝工具响应失败，接入协议与执行循环后通过；CLI 工具测试也先因旧入口仅接受文本失败，再接入 Runtime 后通过。
- 实际问题：一次补丁对同一文件同时声明删除与新增，被工具拒绝且未应用；随后改为分别更新文件。初次静态检查发现测试导入位置和长行，调整导入并格式化。
- 真实模型把两次计算放在同一响应中；记录真实执行事实，没有改写为预想的多步决策。
- 当前分支 `codex/tools-first-slice`，实现开始基点 `5d353ca852765e52d6f61dea88f40c5f1cd11a36`；用户原有未跟踪的 `CONTEXT.md` 未修改、未纳入提交。

本步全量离线验证：73 passed, 4 skipped（32.72 秒，4 个真实 API 测试默认跳过）；本步真实 calculator 测试已单独运行通过。mypy 检查 7 个源文件通过，Ruff 静态与格式检查、git diff --check 通过。

本步双轴审查：基于 `git diff 5d353ca...74702c7`，Standards 0 项发现；Spec 发现 1 项旧 README 真实测试命令范围与请求数说明不一致，已将旧命令限定为原来的三项测试，并将当前默认跳过数更新为四个。未发现代码功能缺口。


## Issue #4：独立 session、SQLite 与重启

两个 PowerShell 终端在同一项目目录启动，使用同一数据库、不同 session：

```powershell
.\start.bat --user-id demo --session-id 1
.\start.bat --user-id demo --session-id 2
```

也可直接运行 `.\.venv\Scripts\python.exe -X utf8 -m minimal_agent --user-id demo --session-id 1`。CLI 显示当前标识；不传参数时为 `local/default`，数据库默认是当前目录 `agent.sqlite3`。`--db <路径>` 可指定已有父目录中的数据库；相对路径基于工作目录，恢复时必须指向同一文件。`--db :memory:` 仅保留本进程历史，供临时演示。Runtime 默认也是内存 SQLite；持久调用使用 `with Runtime(client, db_path=path, user_id="demo", session_id="1") as runtime:`，或显式 `close()` 释放占用。

在终端 1 输入“我叫小林，请计算 12+8”，终端 2 输入“我叫小王，请计算 30+8”。分别退出后按原标识重启，追问“我叫什么？上次结果再除以2”。两个 session 应分别得到小林/10、小王/19；同名 session 配上另一个 user_id 也属于新会话。

`user_id` 是应用传入的本地命名空间，**不是用户认证**。知道别人的标识并能访问数据库的人可以打开其会话；数据库以明文保存对话。模型参数不能指定或覆盖保存身份；calculator 的 Schema 拒绝额外 user_id/session_id 字段。

同一 session 从打开到关闭只有一个运行者：Windows 使用操作系统字节范围锁，Unix 使用 flock；第二个运行者立即提示占用并退出，其他 session 可以交替聊天。锁文件位于数据库相邻 `.locks` 目录，文件保留不代表仍被占用；正常退出、Ctrl+C、进程被强制结束后操作系统释放锁，无需手工删除。运行期间不要删除锁文件或通过硬链接别名打开同一数据库；本方案用于本机文件系统，不用于共享网络盘或分布式部署。

成功 turn 的 user、assistant（含完整 tool_calls/arguments）、tool（含 tool_call_id/result）按顺序在一个 SQLite 事务中追加。存储失败不会显示成功答案；模型失败或进程在 turn 完成前退出，该 turn 不保存，已完成历史仍可恢复。当前 calculator 没有外部副作用；本步不实现中断 turn 的续跑或后续 todo 的副作用恢复。不同 session 写入仅在短提交事务内串行，数据库忙超过 5 秒会明确报错，不静默覆盖历史。

### 本步验收对应证据

| 验收项 | 验证 |
| --- | --- |
| CLI 接收并显示标识、创建/恢复 | `test_cli_displays_identity_and_restores_session` |
| 有序持久消息、每 turn 历史、两个身份维度隔离 | `test_runtime_restores_ordered_history_and_isolates_sessions` |
| 完整调用/结果和计算追问 | `test_restart_preserves_complete_tool_pairs_and_rejects_model_identity` |
| 身份不能由模型覆盖 | 同上：伪造参数被拒绝，目标会话仍为空 |
| 两终端交替聊天、冲突、正常退出及异常退出后恢复 | `test_two_cli_processes_alternate_conflict_and_recover`，真实 CLI 子进程、真实临时 SQLite |
| 失败 turn 不损害旧历史 | `test_failed_tool_turn_does_not_damage_durable_history` |
| 原理和认证范围说明 | 本节和“一次请求如何工作” |

以上离线模型全部是回环 HTTP 脚本化响应，Runtime、calculator、SQLite 和 CLI 进程均为真实实现；没有直接查表代替行为断言。真实模型的重启追问另由 `test_real_cli_sessions_resume` 显式验证：

```powershell
$env:RUN_LIVE_API = '1'
try {
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py -q -s -k sessions_resume --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

### 本步实际 Prompt 与开发记录

- 用户实际输入：`[$implement](C:\Users\1\.agents\skills\implement\SKILL.md) #4`。读取 Issue #4、父 Issue #1，确认阻塞 #3 已关闭。
- 独立分支 `codex/session-persistence`，开始基点 `89b5a74aa63cf20123787a0edf4c3a8a853ad3c7`；原有未跟踪 CONTEXT.md 保持原样、不纳入提交。
- 公共测试边界直接采用 Issue 指定的 Runtime/CLI。先以不支持 db_path 的失败用例实现隔离/重启，再以同 session 未拒绝的失败用例实现进程锁，随后以 CLI 未显示身份的失败用例接入参数和持久存储。
- Windows mypy 最初无法识别 Unix fcntl 分支；改用静态可识别的 sys.platform 判断。Ruff 检出导入顺序和长行，已调整。没有新增外部依赖。

- 真实测试首跑错误地要求首轮回答复述姓名；模型只回答计算结果，该断言失败。改为只在明确询问姓名的重启追问轮检查姓名，保留计算结果及真实工具事件检查。

2026-09-07 09:44:03 UTC，真实 qwen-plus 重启验收：`1 passed, 4 deselected`（13.76 秒）。四个 CLI 进程依次打开/恢复两个 session，session 1 保留小林和 20，追问得到 10；session 2 保留小王和 38，追问得到 19。每轮都观察到真实 calculator 结果。双进程同时存活、冲突和强制结束由离线子进程测试覆盖。

本步全量离线验证：`83 passed, 5 skipped`（43.92 秒，5 个真实 API 测试默认跳过；本步真实重启测试已单独通过）。mypy 检查 8 个源文件通过，Ruff 静态与格式检查通过。

本步双轴审阅：固定差异 `git diff 89b5a74aa63cf20123787a0edf4c3a8a853ad3c7...2b42622`，Standards 0 项发现，Spec 0 项发现；两位只读子代理分别核对规范/代码异味和 Issue #4/#1 需求。Windows 与 Linux 目标的 mypy 均通过（实际运行测试环境仅 Windows），`git diff --check` 通过。实现提交 `2b42622`；Issue #4 保持打开，等待用户审阅，未推送或合并。

## Issue #5：mock search 与持久 todo

默认工具现在为 `calculator`、`search`、`todo`。Runtime 仍用同一个注册表执行循环：模型提出调用 → Schema 校验 → 执行函数 → 回填工具结果 → 再次请求模型。没有按新工具名称增加主循环分支。

`search` 是确定性本地模拟检索，不联网。当前仅有 **2026-09-01 上海小雨、22–27°C、建议带伞** 的教学资料，返回标题、`mock:weather:shanghai:2026-09-01` 来源、内容、`mock: true` 和提示。用短关键词，例如 `上海天气`、`上海 天气`；空白分隔关键词全部匹配才命中，不做语义搜索。无命中返回空列表和明确提示。模型被要求在最终回复保留固定日期及“模拟、非实时”，不能当成当天的天气预报。

`todo` 的参数只有 `action`、`content`、`id`：

| action | 参数 | 结果 |
| --- | --- | --- |
| add | 非空内容 content | added，返回 UUID 稳定 ID、内容和 completed=false |
| list | 无其他参数 | listed，按添加顺序返回当前 session 的全部待办及完成状态 |
| complete | 明确的 id | completed / already_completed / not_found；后者不会修改其他条目 |

注册时将当前 SessionStore 的方法绑定为执行函数，模型没有 user_id/session_id 参数；所有读写 SQL 都带应用提供的两个身份条件。同一数据库支持不同 session 交替运行，既有 SQLite 文件会自动创建待办表，无需重建消息表。状态以工具的 `result.outcome` 和结构化条目为准：外层 `status: ok` 表示调用正常返回，不表示 `not_found` 的完成请求成功。

待办写入在工具返回前以短事务提交，不在等待模型网络响应时持有写事务。后续模型失败或 turn 未写入历史，**此前已提交的待办仍保留**；CLI 会提醒先查询再重试。add 不承诺重试幂等；complete 可重复调用，已完成时返回 already_completed。中断 turn 自动恢复留待后续步骤处理。

### 两个窗口的演示

两个终端分别启动（在相同目录使用同一数据库）：

```powershell
.\start.bat --user-id demo --session-id 1
.\start.bat --user-id demo --session-id 2
```

1. 窗口 1：`查上海的示例天气，帮我记一个带伞的待办`
2. 窗口 2：`根据我提供的本周工作内容写周报，并记一个提交周报的待办。本周已完成登录页开发和三个缺陷修复，下周准备联调。`
3. 窗口 1：`列出我的待办`，再输入 `把带伞那项完成`。
4. 窗口 2：`列出我的待办`，周报待办应仍未完成。
5. `/exit` 后用原命令重启，继续查询；窗口 1 再说 `再把带伞那项完成`，应如实报告早已完成。

对象未提供或“提交报告”同时可能指周报、月报时先澄清；应用拒绝缺少 ID 的 complete，不按内容猜测条目。自然语言歧义识别和模拟信息措辞由模型指令引导，真实演示验证具体案例；Schema 与 SQL 的身份隔离由应用强制执行。

### 验收与实际证据

| Issue #5 验收项 | 证据 |
| --- | --- |
| 注册 search/todo，复用 Runtime | `default_registry` 及 `test_search_to_todo_chain_survives_restart`，模型 HTTP 请求包含工具和前次执行结果 |
| mock 数据、来源、日期、无命中 | `test_search_returns_fixed_mock_weather_through_runtime`、`test_search_no_match_is_explicit` |
| 最终回复保留模拟、非实时 | 真实 CLI 演示 session 1 的第一轮 |
| 稳定 ID、持久化、user/session 隔离 | `test_search_to_todo_chain_survives_restart`、`test_todo_completion_is_isolated_idempotent_and_durable` |
| 模型不能切换身份；非法参数拒绝 | `test_invalid_todo_arguments_do_not_change_state`、发送模型的 Schema 断言 |
| 天气→待办、周报→待办、返回窗口追问 | `test_real_search_todo_sessions_and_clarification`，九个真实 CLI 子进程交替创建/恢复 session |
| 缺失/歧义先澄清，未知 ID 不谎报成功 | 真实演示 session 3；离线测试断言跨 session ID 返回 not_found、缺少 ID 不执行 |
| 跨工具链、追问、无结果、重复完成、跨 session | `tests/test_search_todo.py` 的 Runtime 集成测试；真实模型演示独立开启 |
| 后续模型失败后的已写入待办可查询 | `test_committed_todo_can_be_queried_after_model_failure` |

离线测试只替换外部模型 HTTP 服务；Runtime、工具、SQLite 都是真实实现，没有直接查表代替用户行为验证。脚本化模型用例验证连续决策：收到 search 结果后再请求 todo。真实首轮模型则在同一响应提出 search 和 add 两个调用，应用按顺序执行；不能把它记成“模型收到搜索结果后才决定添加”。真实天气工具本身仍是 mock，真实的是 qwen-plus API 与 CLI 执行路径。

单独运行本步真实演示（使用已配置的本地环境，不输出密钥）：

```powershell
$env:RUN_LIVE_API = '1'
try {
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py -q -s -k search_todo --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

2026-09-07 11:08:55 UTC 开始的 qwen-plus 演示：`1 passed, 5 deselected`（37.85 秒）。[完整脱敏记录](docs/evidence/issue-5-live.txt)包含实际 Prompt、回答、工具参数/结果和执行 ID。两个 session 的待办独立，重复完成返回 already_completed；缺失对象和周报/月报歧义都没有执行 complete。此证据通过反复启动真实 CLI 进程模拟两个窗口的交替使用；同时打开窗口的进程占用策略已由 Issue #4 测试覆盖。

### 本步实际 Prompt 与问题处理

- 用户输入：`[$implement](C:\Users\1\.agents\skills\implement\SKILL.md) #5`，并确认 Runtime.run 测试接口和审阅基点 `978ed5f22fa8e0cbec45345b319da6eb9e49487e`。读取 Issue #5/#1，确认 #4 已关闭。
- 独立分支 `codex/search-todo`；原有未跟踪 CONTEXT.md 未修改、不纳入提交。
- TDD：search 因 unknown_tool 失败后实现；跨工具持久待办用例因 todo 未注册失败后实现 add/list；跨 session 完成用例因 complete 不支持失败后实现隔离和重复完成；模拟/澄清指令用例先失败再补充。随后补充非法参数、无结果与模型失败的回归测试。
- 首次真实验证在重复完成时发现模型只引用历史，不调用工具（`1 failed, 5 deselected`，25.87 秒）。[首次记录](docs/evidence/issue-5-live-first-attempt.txt)如实保留；加强 system 指令要求每次判断待办状态都读取工具，第二次完整演示通过。没有将失败记成通过。
- 静态检查发现新增代码的长行与导入格式，已修正；本步未新增外部依赖。

全量离线测试：`98 passed, 6 skipped`（51.37 秒，6 项真实 API 测试默认跳过；本步真实测试已单独通过）。mypy 检查 9 个源文件通过，Ruff 静态/格式检查通过。Issue #5 保持打开供用户审阅，本步不进入后续 Issue，不推送或合并 main。

本步双轴审阅：固定差异 `git diff 978ed5f22fa8e0cbec45345b319da6eb9e49487e...073d4e0b83ebb7fcf7a5b6dda4ae7f3d25162b69`。Standards：0 项规范违反、0 项代码异味；Spec：0 项缺失、范围外或错误实现。两位只读子代理分别完成检查；明确保留真实模型同响应多调用与离线连续决策的证据区别。最终指令调整后重新运行本步离线文件：`15 passed`（6.85 秒）；Windows/Linux 目标 mypy、Ruff 和 `git diff --check` 均通过（实际测试环境为 Windows）。实现提交 `073d4e0`。

## 联网搜索（用户追加需求）

用户在 Issue #5 之后提出“编写一个联网的好吗”，并选择“使用搜索 API，接受配置密钥”。本次增加可选的 Tavily 搜索，原来的 mock 模式和教学验收仍可运行；这项追加需求扩展了原规划中“不接真实搜索”的范围，不涉及后续上下文压缩步骤。

在 [Tavily 控制台](https://app.tavily.com/) 获取 API key，填写本地 `.env`（不要提交或发送密钥）：

```dotenv
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=你的真实密钥
```

模型的 `LLM_MODEL`、`LLM_BASE_URL`、`DASHSCOPE_API_KEY` 仍按原配置保留，然后启动：

```powershell
.\start.bat --user-id demo --session-id web --search-provider tavily
```

可以输入：`搜索 Python 官方文档并添加一个阅读文档的待办，回答附来源链接。`

CLI 会显示搜索模式。命令行参数优先于 `.env` 中的 SEARCH_PROVIDER；未配置模式默认 mock。`--search-provider mock` 可切回原来的模拟天气演示。选择 tavily 却缺少密钥时明确报配置错误，不会悄悄回退 mock；同一 session 历史可以保留，但旧 mock 搜索结果仍是模拟资料。

联网模式使用 [Tavily 官方 Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)：POST 到固定 HTTPS 地址，密钥只放 Authorization 请求头，不发给模型。使用 basic 搜索，最多返回 5 条标题、网页 URL 和摘要，不请求服务商生成的答案或全文。结果标记 `mock: false`，模型被要求引用来源链接；网页摘要不保证实时，不能把联网检索当成实时天气服务。

每次 HTTP 操作设 10 秒超时，不自动重试或跟随重定向；响应体最多 1 MB、单条标题最多 300 字符、摘要最多 2000 字符，裁剪会标记 truncated。模型参数只有 query，不能指定 API key 或请求地址。网络错误、超时、鉴权失败、限流、额度不足、异常响应分别返回固定工具错误码，不把服务原始错误/密钥写入 trace，不混同于“无命中”。网页内容只是外部数据，system 指令禁止执行摘要内的指令。

### 联网搜索的验证

`tests/test_web_search.py` 在已确认的 Runtime/CLI 接口验证：先返回网页资料再调用 todo、来源与 mock 标记、无命中、异常响应、超时/断网/鉴权/限流/额度、结果裁剪、配置缺失和命令行覆盖。模型仍是回环 HTTP 脚本服务；搜索 HTTP 使用 httpx.MockTransport，**这些通过不代表访问过真实 Tavily**。

配置密钥后可显式运行真实 CLI + 模型 + Tavily 验证：

```powershell
$env:RUN_LIVE_SEARCH = '1'
try {
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live_search.py -q -s
} finally {
    Remove-Item Env:RUN_LIVE_SEARCH -ErrorAction SilentlyContinue
}
```

实现时本地尚未配置 TAVILY_API_KEY，因此当时未执行真实联网验收；用户配置后的验证见下文。实际开发先以缺少 TavilySearch 的失败测试接入搜索，再以 HTTP 401 导致 Runtime 抛异常的失败用例补齐安全工具错误，最后以 CLI 不支持模式参数的失败用例接入配置。沿用现有 httpx，无新增依赖。

本次全量离线验证：`113 passed, 7 skipped`（58.67 秒；包括新增真实联网测试在内的 7 个真实 API 测试默认跳过）。mypy、Ruff 静态与格式检查、`git diff --check` 通过。旧 CLI 演示测试显式指定 mock，避免本地切换 Tavily 配置后改变原有验收的含义。

联网增量实现提交 `d14188b`，双轴只读审阅基于 `978ed5f...d14188b`（重点 `2289524...d14188b`）：Standards 0 项、Spec 0 项；审阅时尚未验证真实 Tavily。CLI 测试隔离调整后，双进程用例复验 `2 passed, 28 deselected`（6.22 秒）。

用户确认密钥“添加完毕”后，于 2026-09-07 11:49 UTC 显式运行上述 `tests/test_live_search.py`：**1 passed in 9.98s**。实际使用真实 CLI、qwen-plus 和 Tavily API，没有替换搜索响应；请求“搜索 Python 官方文档并添加一个阅读文档的待办，回答附来源链接。”验证了搜索有结果、`mock=false`、最终答案引用返回的来源链接，以及 todo 返回 added。测试使用内存数据库，没有向用户已有 session 添加测试待办。输出仅记录验证摘要，不包含密钥。

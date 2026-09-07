# 最小 Agent：calculator 工具循环

当前实现 [Issue #3](https://github.com/Nuru-Banmian/minimal-agent/issues/3)：在已有真实模型 CLI 上加入工具注册、calculator 和手写 Runtime 循环，支持本进程内追问。实现后保持 Issue 打开供用户审阅；后续 session 持久化等功能尚未开始。

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

程序启动时自动加载当前工作目录的 `.env`（支持 UTF-8 BOM），不向父目录搜索文件；已有环境变量优先，包括显式空值。不展开配置中的变量引用。请从项目根目录启动。API key 只填写到本地 `.env`，不写入命令历史、README 或提交材料。`.gitignore` 忽略真实密钥配置文件、虚拟环境、数据库及日志，只有无密钥的 `.env.example` 入库；程序自身不创建日志或数据库。

| 环境变量 | 含义 |
| --- | --- |
| `LLM_MODEL` | 必填；候选 `qwen-plus`，以该账号可用模型为准 |
| `LLM_BASE_URL` | 必填；与 API key 的地域、业务空间匹配，包含 API 版本路径，不包含 `/chat/completions` |
| `DASHSCOPE_API_KEY` | 必填；百炼 API key |
| `LLM_TIMEOUT_SECONDS` | 可选，默认 30；正有限数，HTTP 连接及读写等各阶段的超时秒数，不是整个 turn 的总时限 |

2026-09-07 核验官方文档：北京示例为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，新加坡示例为 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`，必须将占位符替换为实际业务空间 ID，最终以账号控制台为准。不自动猜测地域。来源：[首次调用](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)、[国际站接口文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)。

官方 [Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling) 列出 Qwen-Plus 系列支持工具调用。本步固定发送 `stream: false`、`enable_thinking: false`，不依赖隐藏推理内容。2026-09-07 配置后已实测当前账号的 `qwen-plus` 普通对话、追问与原生 Function Calling；结果见下方验收记录。

## 使用与错误行为

启动后依次输入 `我叫小林`、`我叫什么`，模型应利用本进程的历史回答姓名。回答文本由模型生成，不保证逐字一致。

- 空输入或纯空白：跳过，不请求模型。
- `/exit`、`/quit`（不区分大小写）、EOF 或 Ctrl+C：结束进程，历史随之消失。Windows EOF 为 Ctrl+Z 后回车，Linux/macOS 为 Ctrl+D。
- 配置缺失或无效：向 stderr 输出清楚提示，退出码 2，不请求模型。
- 鉴权失败、权限不足、限流、服务错误、连接失败或超时：向 stderr 输出安全提示，不输出服务端原始异常、密钥或堆栈，可继续输入。
- 请求失败或返回不完整/空白/畸形协议内容：不把它显示为成功回答，不将该轮问答写入历史，之前成功历史保留。需要重新输入失败的问题。
- 正常结束退出码 0；即使期间某轮失败，随后正常退出仍为 0。脚本验收真实请求成功应使用下面的显式真实 API 测试。

请求没有自动重试；HTTP 客户端不读取系统代理环境变量。当前历史随成功轮次增长，每 turn 最多 8 次主模型调用；尚未做持久化、压缩或跨 turn 总调用预算，这些属于后续 Issue。

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

这是协议说明示例，不是真实 API 运行记录。服务端模型不会自动记住客户端未发送的历史；追问能回答，是因为 CLI 每次重新发送之前的成功问答。历史仅在当前进程的列表中；重新启动没有之前的内容，同一用户的不同进程也不会共享历史。持久化和独立 session 由后续 Issue 提供。

代码阅读顺序：

1. `src/minimal_agent/config.py` 加载当前目录 `.env`，以已有环境变量优先，读取并校验配置。
2. `src/minimal_agent/cli.py` 负责输入输出和显示 trace，调用公共 `Runtime.run(text)`。
3. `src/minimal_agent/client.py` 负责 HTTP 请求、协议解析、错误转换；它不会自动保存历史，也不会执行工具。

4. `src/minimal_agent/runtime.py` 区分外层 turn 与内层 step，回填工具结果并判断继续或停止；只有完成的 turn 才进入历史。
5. `src/minimal_agent/tools.py` 注册工具，启动时检查 JSON Schema，执行前解析 JSON 并校验参数，调用真实 Python 四则运算函数。

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
    & .\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_live.py -q -s --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

真实测试验证客户端与 CLI 追问能返回“小林”，只打印时间、模型和匹配结果，不打印 key 或原始响应。Function Calling 测试向真实服务发送 `echo_name` Schema 并强制选择该函数，检查返回的调用 ID、函数名及 JSON 参数，不执行工具，也不实现下一步 Runtime。实测 Qwen 强制工具调用可能返回 `finish_reason=stop`，因此按实际 `tool_calls` 校验，不能只靠结束标记判断有无工具调用。未显式开启时三个真实测试跳过，开启后配置错误或请求失败会失败，绝不切换到替身。

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

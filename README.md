# 最小 Agent：第一步普通聊天

实现 [Issue #2](https://github.com/Nuru-Banmian/minimal-agent/issues/2)：Python CLI 通过阿里云百炼 OpenAI 兼容接口请求真实模型，支持本进程内连续追问。当前没有工具执行或 Agent Runtime 循环，下一步需经用户审阅后再开始。

## 安装与启动

支持 Python 3.11+；本轮实际验证环境为 Windows、Python 3.13.5。运行依赖只有 HTTPX，用它直接发送 HTTP，方便观察消息协议；不使用 Agent 框架。

在项目根目录的 PowerShell 中执行，无需激活虚拟环境：

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'

$env:LLM_MODEL = 'qwen-plus'
$env:LLM_BASE_URL = Read-Host '粘贴控制台给出的所属地域 API base URL'
$credential = Get-Credential -UserName 'dashscope' -Message '在密码栏输入 API key'
$env:DASHSCOPE_API_KEY = $credential.GetNetworkCredential().Password
Remove-Variable credential
$env:LLM_TIMEOUT_SECONDS = '30'
$env:PYTHONUTF8 = '1'

& .\.venv\Scripts\python.exe -m minimal_agent
```

若已创建 `.venv`，可跳过第一条命令。已安装的其他支持版本可替换 `-3.13`。安装后也可运行 `.\.venv\Scripts\minimal-agent.exe`。Linux/macOS 使用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -e '.[dev]'`，在环境中配置同名变量后运行 `.venv/bin/python -m minimal_agent`。

本程序只读取环境变量，不自动加载 `.env`。API key 只输入到本地终端密码栏，不写入命令历史、README 或提交材料。`.gitignore` 忽略密钥配置文件、虚拟环境、数据库及日志；程序自身不创建日志或数据库。

| 环境变量 | 含义 |
| --- | --- |
| `LLM_MODEL` | 必填；候选 `qwen-plus`，以该账号可用模型为准 |
| `LLM_BASE_URL` | 必填；与 API key 的地域、业务空间匹配，包含 API 版本路径，不包含 `/chat/completions` |
| `DASHSCOPE_API_KEY` | 必填；百炼 API key |
| `LLM_TIMEOUT_SECONDS` | 可选，默认 30；正有限数，HTTP 连接及读写等各阶段的超时秒数，不是整个 turn 的总时限 |

2026-09-07 核验官方文档：北京示例为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，新加坡示例为 `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`，必须将占位符替换为实际业务空间 ID，最终以账号控制台为准。不自动猜测地域。来源：[首次调用](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)、[国际站接口文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)。

官方 [Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling) 列出 Qwen-Plus 系列支持工具调用；这只证明文档声明，不证明当前账号可用。本步固定发送 `stream: false`、`enable_thinking: false`，不依赖隐藏推理内容。账号模型可用性与账号下实际 Function Calling 验证仍待完成。

## 使用与错误行为

启动后依次输入 `我叫小林`、`我叫什么`，模型应利用本进程的历史回答姓名。回答文本由模型生成，不保证逐字一致。

- 空输入或纯空白：跳过，不请求模型。
- `/exit`、`/quit`（不区分大小写）、EOF 或 Ctrl+C：结束进程，历史随之消失。Windows EOF 为 Ctrl+Z 后回车，Linux/macOS 为 Ctrl+D。
- 配置缺失或无效：向 stderr 输出清楚提示，退出码 2，不请求模型。
- 鉴权失败、权限不足、限流、服务错误、连接失败或超时：向 stderr 输出安全提示，不输出服务端原始异常、密钥或堆栈，可继续输入。
- 请求失败或返回不完整/空白/工具调用内容：不把它显示为成功回答，不将该轮问答写入历史，之前成功历史保留。需要重新输入失败的问题。
- 正常结束退出码 0；即使期间某轮失败，随后正常退出仍为 0。脚本验收真实请求成功应使用下面的显式真实 API 测试。

请求没有自动重试；HTTP 客户端不读取系统代理环境变量。当前历史随成功轮次增长，尚未做持久化、压缩或总调用预算，这些属于后续 Issue。

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

1. `src/minimal_agent/config.py` 从环境读取并校验配置。
2. `src/minimal_agent/cli.py` 负责输入输出，准备历史并在成功后追加问答。
3. `src/minimal_agent/client.py` 负责 HTTP 请求、协议解析、错误转换；它不会自动保存历史，也不会执行工具。

当前每条非空输入只发起一次模型 API 请求。Agent Runtime 则需要由应用读取模型的工具调用、执行工具、回填结果，并决定是否继续请求以及何时停止；那是下一步要实现的控制流。

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

配置真实账号后，可单独执行两轮真实请求（会消耗模型额度）：

```powershell
$env:RUN_LIVE_API = '1'
try {
    & .\.venv\Scripts\python.exe -m pytest tests/test_live.py -q -s --tb=short
} finally {
    Remove-Item Env:RUN_LIVE_API -ErrorAction SilentlyContinue
}
```

真实测试调用相同的模型客户端，验证追问能返回“小林”，只打印时间、模型和匹配结果，不打印 key 或原始响应。它不验证 Function Calling；该项仍需在实际账号上独立核验。未显式开启时跳过，开启后配置错误或请求失败会失败，绝不切换到替身。

### Issue #2 验收证据（2026-09-07）

| 验收项 | 对应证据 | 状态 |
| --- | --- | --- |
| 最小 Python 项目、安装与启动命令 | `pyproject.toml`；可编辑安装成功；CLI 子进程测试 | 已完成 |
| 配置、忽略文件、账号模型及 Function Calling 支持 | `test_cli_configuration_errors_are_clear`；`test_client_sends_configured_non_streaming_chat`；官方文档核验 | 部分完成：账号实测未完成 |
| 同步聊天、追问、空输入和退出 | `test_cli_chat_followup_blank_and_exit`；`test_cli_clean_exit_without_requests` | 离线已完成 |
| 配置、鉴权、超时提示 | `test_client_reports_safe_http_errors`；超时及 CLI 失败恢复测试 | 离线已完成 |
| 客户端协议与 CLI 冒烟 | `tests/test_client.py`、`tests/test_cli.py` | 离线已完成 |
| 真实 API 对话与追问、脱敏记录 | `tests/test_live.py` 显式开启入口 | **未完成：本进程无真实模型配置，未执行** |
| 历史与原理说明 | 本 README“一次请求如何工作” | 已完成 |

本轮全量结果：`39 passed, 1 skipped`（17.09 秒，跳过项为真实 API）；mypy 检查 5 个源文件通过，Ruff 静态检查和格式检查通过，`git diff --check` 通过。已实际运行安装生成的 `minimal-agent.exe`，无配置时显示缺失的三个变量名称；`git check-ignore` 确认密钥文件、虚拟环境、数据库与日志路径均被忽略。保持 Issue #2 打开，等待用户审阅；不进入下一步。

## 实际 AI Prompt 与问题记录

- 实际用户输入：`[$implement](C:\Users\1\\.agents\skills\implement\SKILL.md) #2`。
- 实际审阅基点回复：`使用 cbd7e7c`。实现依据为读取到的 Issue #2 及父 Issue #1，不补造额外用户指令。
- 开发过程：先写客户端 HTTP 成功用例，确认缺少模块导致失败，再实现请求；随后添加失败响应、超时、CLI 追问和错误恢复用例并逐步通过。
- 遇到的问题：首次安装尚未结束时测试提示包不存在；等待安装成功后重跑，确认失败点变为待实现的客户端模块。Windows 的回环连接失败测试使用过短超时会先触发连接超时，调整为足够等到连接拒绝的 3 秒；读取超时另用延迟 HTTP 响应确定性验证。
- 配置检查仅查看变量名称/是否存在，没有读取或输出任何真实密钥；本轮没有可用配置，因此未发生真实 API 演示。离线脚本化回复不能作为真实模型可用性的证据。

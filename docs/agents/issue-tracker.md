# 任务跟踪：GitHub

任务和规格保存在 GitHub Issues 中，使用 `gh` CLI 操作。

## 目标仓库

通过 `git remote -v` 确定 GitHub 仓库。在克隆的仓库内运行时，`gh` 通常会自动识别目标。

若没有 GitHub 远程地址，先向用户获取 `owner/repo`，再为 issue 命令传入 `--repo owner/repo`。所有任务跟踪操作都必须先确定目标仓库。

## 常用操作

- 创建：`gh issue create --title "..." --body-file <path>`
- 读取：`gh issue view <number> --comments`
- 列表：`gh issue list --state open`，按需添加标签或状态筛选。
- 评论：`gh issue comment <number> --body-file <path>`
- 添加标签：`gh issue edit <number> --add-label "..."`
- 移除标签：`gh issue edit <number> --remove-label "..."`
- 关闭：`gh issue close <number>`

多行正文写入 UTF-8 文件，再通过 `--body-file` 传入。创建或更新后读取结果，核对正文和中文显示。

技能要求“发布到任务跟踪系统”时，创建 GitHub issue；要求“获取相关任务”时，读取该 issue 及其评论。

## Pull requests as a triage surface

PRs as a request surface: no.

## Wayfinding 操作

- **地图**：使用一个标记为 `wayfinder:map` 的 issue，记录笔记、已有决策和待澄清问题。
- **子任务**：优先通过 GitHub sub-issues 关联到地图；不可用时，在地图正文使用任务列表，并在子任务顶部记录 `Part of #<map>`。类型标签为 `wayfinder:<type>`，其中类型为 `research`、`prototype`、`grilling` 或 `task`。
- **阻塞关系**：优先使用 GitHub 原生 issue dependencies；不可用时，在子任务顶部记录 `Blocked by: #<number>`。所有阻塞任务关闭后，该任务才可执行。
- **下一任务**：按地图中的顺序，选择第一个仍开放、没有指派人且所有阻塞任务均已关闭的子任务。
- **领取**：将子任务指派给实际执行的开发者，再开始工作。
- **完成**：评论记录答案，关闭子任务，再将摘要和链接补充到地图的 Decisions-so-far 部分。

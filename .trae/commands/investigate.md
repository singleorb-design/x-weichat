---
description: "Root-cause investigation. Gathers evidence, generates competing hypotheses in parallel, adversarially refutes each one, and produces a written root-cause report with a suggested fix."
argument-hint: "[args 自然语言]"
allowed-tools: Bash, BashOutput, TaskCreate, Read
---

# Workflow: investigate

> Root-cause investigation. Gathers evidence, generates competing hypotheses in parallel, adversarially refutes each one, and produces a written root-cause report with a suggested fix.

> **When to use**: When the user wants the root cause of an incident, error, log, trace, or puzzling behavior found — without necessarily fixing it. This workflow collects evidence, runs parallel hypothesis agents, tries to refute each hypothesis, and writes up the surviving root cause with next steps. It produces a report, not a PR.
**Phases**（仅供参考，实际由脚本动态决定）: Gather → Hypothesize → Verify → Report
**Source**: `/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/workflows/investigate.js` (builtin)

用户参数（自由文本）：`$ARGUMENTS`

> **设计**：non-interactive 后台启动。runtime 自跑，main agent 只负责启动 + 返回 workflow id。**不要轮询** —— 进度由 `/coco-workflow:workflows` 拉状态文件渲染，跑完用 `/coco-workflow:workflow-result <id>` 看报告。

## Step 1 — args schema（已 grep 自 source，无需现场探测）

此 workflow 实际读的字段：**raw string (`typeof args === "string"`)**

> 由 `sync-commands.js` 在 session_start 时从 `/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/workflows/investigate.js` grep `args.XXX` 而得。若以下字段名跟你预期不符，说明 workflow 源码已变，重启 coco session 会自动刷新此命令。

## Step 2 — 把 `$ARGUMENTS` 转成 JSON

| 用户输入 | 你构造 |
|---|---|
| 无参 | `{}` |
| 单值 `/<name> foo` | `"foo"` |
| 多词 `/<name> foo bar` | `"foo bar"` |

这个 workflow 直接把 `args` 当字符串读；`--args` 仍然必须是合法 JSON，所以要传 JSON string（带引号），不是 `{"trim":"..."}` 这类对象。

cli 强制 `--args` 是合法 JSON，乱传会被拒。混杂自然语言（如 `"docs/x.md 这是技术方案"`）只取有用的（路径/数据），忽略描述。

## Step 3 — 后台启动 + 一次 `BashOutput` 拿 wfid

```bash
COCO_WF_BACKEND=traex node "/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/runtime/cli.js" run "investigate" --args='<把 Step 2 的 JSON 嵌这里>' --no-tui --events-ndjson 2>&1
```

`run_in_background: true`。然后**等约 2 秒**一次 `BashOutput` 拉前几行，从 `workflow:start` 事件里抓 `wfid` 字段（这是 workflow run id）。

> Runtime 绝对路径已硬编码：`/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/runtime/cli.js` —— Step 5 输出 TUI 命令时直接复用，不需要再去拿 PLUGIN_ROOT。

如果第一个事件就是 `error`，立即告诉用户、**不要 TaskCreate**。

## Step 4 — `TaskCreate` root task（**subject 必须带 wfid**）

不要预建 phase 子任务（违反 JS 动态编排）。**必须先在 Step 3 拿到 wfid 再 TaskCreate**，否则 `/coco-workflow:workflow-result` 无法精确回查到这条 task。

- `subject`: `workflow: investigate (<wfid>)`  ← **wfid 必填**
- `activeForm`: `Running investigate (<wfid>)`
- `description`: `Root-cause investigation. Gathers evidence, generates competing hypotheses in parallel, adversariall...` + `\nwfid=<wfid>` + `\nargs=<你构造的 JSON>` + `\n实时进度: /coco-workflow:workflows`

## Step 5 — 立即返回（**这条 turn 必须短**）

向用户输出：

```
✓ investigate 已后台启动
  workflow id: <wfid>
  bash id: <bash_id>

实时进度（coco 内）:  /coco-workflow:workflows
交互 TUI（另开终端）: node /Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/runtime/cli.js watch <wfid>
跑完查报告:           /coco-workflow:workflow-result <wfid>
```

替换 `<wfid>` 为真实 id。TUI 是只读 viewer（按 q 退出，不影响 workflow），必须**在另一个终端跑**，因为它要占 stdin。

然后**结束 turn**。不要继续 polling、不要叙述 phase。

<!-- coco-workflow:auto-generated source=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/workflows/investigate.js scope=builtin -->

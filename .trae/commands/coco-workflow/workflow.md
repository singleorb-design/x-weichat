---
description: 后台启动一个 coco-workflow（.claude/workflows 下的 .js）。立即返回 workflow id；进度看 /coco-workflow:workflows；完成后 /coco-workflow:workflow-result <id>。
argument-hint: <workflow-name> [args 自然语言]
allowed-tools: Bash, BashOutput, TaskCreate, Read
---

# Workflow `$1`

用户参数（自由文本）：`$ARGUMENTS`

> **设计原则**：non-interactive 后台启动。runtime 自跑，main agent 只负责启动 + 返回 wfid。**不要轮询** —— 进度由 `/coco-workflow:workflows` 拉状态文件渲染（实时 ASCII 面板）。这条 turn 必须**短** —— 用户可能马上想 `/coco-workflow:workflows` 看进度，长 turn 会让 slash command 排队卡死。

---

## Step 1 — 读 workflow 元信息 + 探测 args schema

`Read` `.claude/workflows/$1.js`（或 `.agents/`、`.trae/`、`.coco/workflows/`、`~/.coco/workflows/` 兜底）。

需要从 source 提取**两样东西**：

1. **`meta.description`**：用作 root task 描述
2. **`args` 的实际字段名**：**不要猜，去 grep**。在源码里找 `args\.\w+` / `args\s*&&\s*args\.\w+` / `args?.` 的所有出现，记下所有字段名（可能多个）。

例如源码里有 `const docsRaw = (args && args.docs) || []` → 字段名是 `docs`。源码里有 `args.targets` → 字段名是 `targets`。**字段名因 workflow 而异，没有默认值**。

如果一个 workflow 用了 3 个字段（`args.docs` / `args.scope` / `args.depth`），都要识别出来。

---

## Step 2 — 构造 args JSON

把 `$ARGUMENTS`（自然语言）按 **Step 1 探测到的字段名**塞进 JSON，**不要套用其他 workflow 的字段名**。

通用启发（在没有 schema 文档时的判断标准）：

- 路径/数据 → 放进**第一个**看起来语义对得上的字段（通常是 docs/files/targets/paths/path/url 这类）
- 多个值且字段名是复数 / 源码里看到当数组用 → 用 JSON 数组
- 用户混杂自然语言描述（如 `"docs/x.md 这是技术方案"`）→ 只取有用的（路径/数据），忽略描述
- 无参或无法识别 → `{}`
- **永远不要**把整段中文塞进 `--args`，cli 会拒绝非 JSON 输入

例（假设 Step 1 找到 `args.docs`）：

| 用户输入 | 你构造 |
|---|---|
| `/<name> docs/x.md` | `{"docs":"docs/x.md"}` |
| `/<name> a.md b.md` | `{"docs":["a.md","b.md"]}` |
| `/<name>` | `{}` |

如果 Step 1 找到的字段名是 `targets` 而不是 `docs`，把上表的 `docs` 全部换成 `targets`。

---

## Step 3 — 后台启动 runtime（**不等结果**）

```bash
echo "[meta] PLUGIN_ROOT=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows" 1>&2
COCO_WF_BACKEND=traex node "/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/runtime/cli.js" run "$1" --args='<把 Step 2 的 JSON 嵌这里>' --no-tui --events-ndjson 2>&1
```

`Bash` 调用必须带 `run_in_background: true`。

**等大约 2 秒**（一次性 `BashOutput`）拉前几行事件：
- 找 `wfid` 字段（形如 `wf_xxxxx_yyy`，这是 workflow run id）
- 找 `[meta] PLUGIN_ROOT=...` 那行，记下绝对路径（Step 5 输出 TUI 命令时要展开）

如果第一个事件已经有 `error`，说明 args/路径错了，立即告诉用户、**不要 TaskCreate**。

---

## Step 4 — `TaskCreate` 一个 root task（**subject 必须带 wfid**）

**唯一一个 task**，不要预建 phase 子任务（phase 由 workflow 脚本动态决定，强行预建会破坏编排灵活性）。

**注意顺序**：必须先在 Step 3 拿到 wfid，再 TaskCreate，subject 里塞 wfid 才能让 `/coco-workflow:workflow-result` 精确回查到这条 task。

- `subject`: `workflow: $1 (<wfid>)`  ← **wfid 必填，不能省**
- `activeForm`: `Running $1 (<wfid>)`
- `description`: `<meta.description>`（一句话）+ `\nwfid=<wfid>` + `\nargs=<你构造的 JSON>` + `\n查看实时进度: /coco-workflow:workflows`

---

## Step 5 — 立即返回

向用户输出（**短，不要叙述执行过程**）：

```
✓ workflow [$1] 已后台启动
  workflow id: <wfid>
  bash id: <bash_id>

实时进度（coco 内）:  /coco-workflow:workflows
交互 TUI（另开终端）: node <PLUGIN_ROOT>/runtime/cli.js watch <wfid>
跑完查报告:           /coco-workflow:workflow-result <wfid>
```

其中：
- `<PLUGIN_ROOT>` 替换为 Step 4 拿到的 `PLUGIN_ROOT=...` 绝对路径（用户在自己终端没有这个 env）
- `<wfid>` 替换为真实 id
- TUI 是只读 viewer，按 `q` 退出，不会影响 workflow 本身；coco 内不能开（抢 stdin），所以必须在另一个终端运行

然后**这条 turn 结束**。**不要继续 polling** `BashOutput`、不要叙述 phase 进度。

<!-- coco-workflow:support-command source=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/commands/workflow.md -->

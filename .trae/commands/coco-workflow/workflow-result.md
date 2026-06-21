---
description: 查看一个 coco-workflow 跑完后的最终 report（从状态文件读 result.report）
argument-hint: <workflow-id | latest>
allowed-tools: Bash, TaskUpdate, TaskList
---

# Workflow 结果

参数：`$1`（workflow id，形如 `wf_xxxxx_yyy`；或 `latest` 取最近一个）

## Step 1 — 拉状态文件

```bash
node "/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/scripts/show-result.js" "$1"
```

输出格式：第一行是 `STATUS=running|done|error|notfound`，第二行是 `WFID=<workflow-id>`，之后是 markdown report（或错误信息）。

记下输出里 `WFID=` 后面那串真实 wfid（用户传的可能是 `latest`，要用脚本回填的 wfid）。

## Step 2 — 根据 STATUS 处理

### `running`

workflow 还没跑完。告诉用户当前进度（已完成 phase 数），引导他用 `/coco-workflow:workflows` 看实时。**不要动 task。**

### `notfound`

告诉用户没找到对应的 workflow id，列最近 5 个让他选（脚本会输出候选）。**不要动 task。**

### `done` / `error`

先把 report 段（或错误信息）原样 markdown 展示给用户，**这是必做的，不依赖 task 操作的成败**。

然后**尝试**回写 root task 状态（**找不到就跳过，不要报错**）：

1. 调 `TaskList` 拿到所有 task
2. 在结果里找 subject **包含上面那个 wfid** 的 root task（`workflow.md` 现在会把 wfid 写进 subject，例如 `workflow: bughunt (wf_xxxxx_yyy)`）
3. **如果找到**：取出它的 `taskId`，再调 `TaskUpdate(taskId=<取到的>, status=completed, description=...)`
   - `done` 时 description 加 `done · <duration> · <agents> agents · <tok> tok`
   - `error` 时 description 加 `FAILED: <reason>`
4. **如果没找到**：什么都不做，**不要**调 `TaskUpdate`（缺 taskId 一定会报 "taskId value required"）。可以在最终输出末尾轻量提一句"未找到匹配的 root task，跳过状态同步"。

> 兼容旧 task：老版本 `workflow.md` 的 subject 不带 wfid，只有 `workflow: <name>`。这种情况只能模糊匹配 workflow 名，可能命中错的，所以**优先精确匹配 wfid**，匹配不到再考虑 fallback；fallback 不到就直接跳过。

<!-- coco-workflow:support-command source=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/commands/workflow-result.md -->

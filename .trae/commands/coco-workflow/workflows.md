---
description: 显示所有正在跑或最近完成的 coco-workflow 的 ASCII 进度面板（cc-style 的 /workflows 视图）
argument-hint: "[--all | --id=<workflow-id>]"
allowed-tools: Bash
---

# Workflows 进度面板

下面是当前所有 workflow 的 ASCII phase 框图：

!`node "/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/scripts/render-workflows.js" $ARGUMENTS`

---

**输出规则（严格遵守）**：

1. **把上面那段 ASCII 框图原样、完整地输出给用户**。这是 cc-style 状态面板的核心呈现，用户**就是要看那个图**。不要用 bullet list 重新叙述、不要总结、不要换格式。
2. 如果上面什么都没显示（脚本静默或没结果），告诉用户：还没有 workflow 跑过，用 `/<workflow-name>` 或 `/coco-workflow:workflow <name>` 起一个。
3. 不要追加你自己的分析、预测、下一步建议 —— 用户问的是"现在状态"，给状态就够了。

<!-- coco-workflow:support-command source=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/commands/workflows.md -->

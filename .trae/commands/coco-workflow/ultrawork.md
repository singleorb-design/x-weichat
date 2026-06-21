---
description: 自动编排 —— 针对你给的任务现场 author 一个 workflow 并后台跑（不需要预存 .js）。等价 cc 主 agent 内联调 Workflow 传 script。
argument-hint: <要编排的任务，自由文本>
allowed-tools: Bash, BashOutput, Read, Write, Grep, Glob, TaskCreate
---

# ultrawork：编排并后台跑 `$ARGUMENTS`

用户要你把下面这个任务**动态拆成多 agent 的 workflow 并后台跑**，而不是套用某个固定 workflow：

> $ARGUMENTS

## 怎么做

**严格按 `ultrawork` skill 的全流程执行**（Step 0→5）：

0. **判断该不该编排 + 查 builtin**：要全面 / 要可信 / 要规模，三者之一才编排；否则直接内联做。**先看 builtin 是否正好覆盖**（`coco-workflow/workflows/`：bughunt / deep-research / review-branch / investigate / plan-hunter …）——**调研类任务多半就是 `deep-research`**，命中就直接跑它或拿它当模板，别从零写。
1. **内联 scout = 只为得出工作清单，绝不替 workflow 干活** ⚠️：scout 只决定「fan out 哪些维度 / 哪些文件」。
   - 🚫 **最致命的错误**：在主 agent 里把任务本身先做了。比如用户让你「调研最佳生图/生视频工作流」，你却自己 `WebSearch` 了几次——错。那是替 workflow 干活，编排失去意义。
   - ✅ 正确：主 agent **一次搜索都不做**，只定出调研维度（如 生图 / 生视频 / 配音 / 剪辑 / 短剧端到端编排），每条作为一个 item，author 一个「每维度一个 research agent + 验证」的 workflow。**WebSearch / WebFetch / 深读 / 验证全部在 workflow agent 里发生。**
   - scout 允许：列文件 / grep / 圈范围 / 明确子问题维度。scout 禁止：WebSearch / WebFetch / 读长文 / 写结论。
2. **选形状**：默认 `pipeline`；要全量去重才用 `parallel` 屏障；未知规模用 loop-until-dry；要高可信用对抗性 N 票。
3. **写 scratch 脚本** 到 `~/.coco/workflows/.scratch/ow_<slug>.js`（slug 用任务关键词，不要时间戳）。
4. **后台启动**：
   ```bash
   mkdir -p ~/.coco/workflows/.scratch
   echo "[meta] PLUGIN_ROOT=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows" 1>&2   # Step 5 输出 watch 命令要用绝对路径
   COCO_WF_BACKEND=traex node "/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/runtime/cli.js" run ~/.coco/workflows/.scratch/ow_<slug>.js \
     --args='<JSON 或省略>' --no-tui --events-ndjson 2>&1
   ```
   `run_in_background: true`，2 秒后一次 `BashOutput` 抓 `wfid` + `PLUGIN_ROOT`。
   - **dry-run 只对现场写的 scratch 脚本做**（抓语法错）；**走 Step 0 命中的 builtin（如 `deep-research`）不要 dry-run**，已验证过、多余。
5. **TaskCreate**（subject 带 wfid）**+ 立即返回**，输出和原生 `/coco-workflow:workflow` 一致的三行（含 `node <PLUGIN_ROOT>/runtime/cli.js watch <wfid>` 交互 TUI）：
   ```
   ✓ ultrawork [<slug>] 已后台启动
     workflow id: <wfid>

   实时进度（coco 内）:  /coco-workflow:workflows
   交互 TUI（另开终端）: node <PLUGIN_ROOT>/runtime/cli.js watch <wfid>
   跑完查报告:           /coco-workflow:workflow-result <wfid>
   ```
   不要轮询。

## coco 硬约束（skill 里有完整版，这里挑最容易踩的）
- `meta` 纯字面量；脚本里禁 `Date.now()` / `Math.random()` / 无参 `new Date()`。
- `parallel`/`pipeline` 内 `agent()` 必须显式 `{phase:'X'}`。
- **不要用 `budget` 缩放**（coco 不计 token，`budget.total` 恒 null，会静默走兜底）。
- schema 保持**扁平**（文本抠 JSON，只重试 1 次，复杂嵌套易失败）。
- 只读侦查用 `agentType:'Explore'`；结果 `return { report: '...' }`。

跑完进度看 `/coco-workflow:workflows`，报告 `/coco-workflow:workflow-result <wfid>`。

<!-- coco-workflow:support-command source=/Users/bytedance/Library/Caches/coco/plugins/coco_plugin_workflows/commands/ultrawork.md -->

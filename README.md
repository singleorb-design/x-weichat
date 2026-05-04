# x-to-wechat-agent

本地优先的 `X URL -> 中文翻译 -> 审校 -> 路由判断 -> 终稿 -> 微信 HTML` 流水线，包含 Python Agent Core、Web UI 和 Node Renderer。

## Overview

- 输入：单条 X 推文 URL，或 X Article URL。
- 输出：结构化中间产物、最终发布用 `10-final.md`、以及渲染后的 `11-wechat.html`。
- 运行方式：固定串行流水线，不做批处理、审批流、自动发布。
- Web UI 支持任务轮询、阶段重跑、Prompt 查看、Markdown 预览、HTML 新标签预览。

## Pipeline

固定阶段顺序如下：

1. `x-fetch`
2. `translate`
3. `review`
4. `route`
5. `light-polish`
6. `wechat-rewrite`
7. `final-check`
8. `targeted-fix`
9. `final-output`
10. `render-html`

### Stage intent

- `x-fetch`：抓取 X 内容，产出原文 Markdown，并单独写入元数据。
- `translate`：完整翻译，不允许总结、删减或改写结构。
- `review`：对照原文做审校，并带长度保护，避免内容明显缩水。
- `route`：在审校后决定走 `PASS`、`LIGHT_POLISH` 或 `REWRITE`。
- `light-polish`：仅做轻量可读性优化，不允许信息损失。
- `wechat-rewrite`：仅在路由判定为 `REWRITE` 时执行更强的公众号化改写。
- `final-check`：对候选终稿做发布前质检，产出结构化 JSON 结果。
- `targeted-fix`：只按终检问题做定点修复，不做整稿重写。
- `final-output`：清洗最终 Markdown，确保适合发布。
- `render-html`：把最终 Markdown 渲染成微信 HTML。

## Routing and quality gates

- `route` 只允许输出三种决策：`PASS`、`LIGHT_POLISH`、`REWRITE`。
- 路由结果会做归一化；当 JSON 解析失败、决策不合法、或 `PASS` 伴随非低风险时，会回退到 `LIGHT_POLISH`。
- `review`、`light-polish`、`wechat-rewrite`、`targeted-fix` 都带长度比保护，防止模型把内容越改越短。
- `final-check` 先检查候选稿；若允许自动修复，则进入 `targeted-fix` 后再次复检。
- `final-output` 会执行发布前清洗：
  - 把顶层 `#` 标题降为 `##`
  - 去除 AI 腔、自我说明和元数据泄漏
  - 统一空白与段落边界

## Artifacts

### Main artifacts

| 文件 | 含义 |
| --- | --- |
| `01-source.md` | 抓取后的原文 Markdown |
| `02-translation.md` | 中文翻译稿 |
| `03-reviewed.md` | 审校稿 |
| `04-route.json` | 路由决策 JSON |
| `05-polished.md` | 轻编辑稿 |
| `06-rewritten.md` | 强改写稿 |
| `07-final-candidate.md` | 终检输入候选稿 |
| `08-final-check.json` | 终检结果 |
| `09-final-fixed.md` | 定点修复稿 |
| `10-final.md` | 最终发布稿 |
| `11-wechat.html` | 渲染后的微信 HTML |

### Auxiliary artifacts

- `metadata.json`：保存 `url`、`requestedUrl`、`source_type`、`title`、`coverImage`。
- `final_check_raw.txt`：终检 JSON 解析失败时保留的原始模型输出。
- `final_check_failed.json`：终检无法自动修复时的失败记录。
- `final_candidate_failed.md`：终检失败时对应的候选正文快照。

说明：`metadata.json` 不进入正文；最终正文以 `10-final.md` 为准。

## Web UI

- Prompt 面板支持折叠查看，并显示当前任务实际使用的 Prompt 文件名和模型。
- Markdown 类产物采用渲染预览；原文保留纯文本查看方式。
- HTML 预览除内嵌查看外，还支持新标签页全屏打开。
- 重跑冲突返回结构化错误：包含 `code`、`message`、`suggestion`、`can_change_stage`，方便前端给出下一步提示。

## Commands

### Setup

- `make setup`
- `make install-playwright`

### Local development

- `make backend`
- `make frontend`
- `make dev`

### Verification

- `make test`
- `make build`
- `make check-api`

## Retry behavior

- 失败任务可以从失败阶段重跑。
- 已完成或失败任务可以从任意指定阶段重新开始。
- 重跑会清理该阶段及后续阶段的产物、阶段元数据和失败快照，避免新旧结果混用。

## Publishing contract

- 最终发布正文使用 `10-final.md`。
- 正文不应包含 `url`、`requestedUrl`、`coverImage` 等元数据字段。
- 最终稿不应包含“以下是整理后的内容”“我已按要求优化”等 AI 式说明。
- 最终正文从 `##` 开始，不使用顶层 `#` 标题。

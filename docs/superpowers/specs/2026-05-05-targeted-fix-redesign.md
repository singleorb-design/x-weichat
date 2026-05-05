# targeted-fix（定点修复）改造：规则优先 + LLM 兜底（硬超时/降级）

日期：2026-05-05

## 背景与问题

现象：部分任务在 `targeted-fix` 阶段“看似卡住”，超过 10–15 分钟无进展。

复盘（基于 job `7ab7d8d54ac04cc487fdf5bdc80244c0`）：

- `targeted-fix` 的模型连通性探测（probe）已通过，说明不是模型不可达。
- 任务在 `targeted-fix` 阶段发起真实生成请求后长时间不返回；用户点击“停止任务”后，任务状态会被标记为 `canceled`，但当前实现不会中断正在进行的那次模型请求。
- 流水线只在“阶段之间”检查 canceled，无法在阶段内部打断同步调用，因此 UI 表现为长期停留在 `targeted-fix`。

## 目标与非目标

### 目标

1. **最坏情况耗时收敛**：`targeted-fix` 阶段对外保证可控的上限耗时。
2. **规则优先**：对可规则化的 issues 采用确定性修复（0 模型调用），最大化稳定性与可解释性。
3. **LLM 兜底但可降级**：仅在规则无法安全处理的情况下调用模型，并且强制硬超时；超时/异常/校验不通过时自动回退为规则修复稿，流水线继续跑 `final-output`。
4. **可解释性与排查**：每次修复都要产出 trace/diff，能回答“修了什么/为什么回退”。

### 非目标

- 实现“立即取消正在执行的 OpenAI SDK 请求”。现有同步调用链路中很难可靠做到；本次通过硬超时 + 降级实现用户可感知的“不会卡死”。

## 总体设计

### 输入与输出

- 输入：
  - `07-final-candidate.md`
  - `08-final-check.json`
- 输出：
  - 必须保证写出 `09-final-fixed.md`（即使回退也要写：回退到规则修复稿或候选稿）
  - 补充 trace/diff：见“产物与 trace 规范”。

### 组件拆分

#### 1) RuleFixer（确定性规则修复）

默认必跑，目标是覆盖大部分 issues，且 0 模型调用。

规则集合（按 issue 类型映射）：

- 元信息泄露：`remove_frontmatter()`
  - 删除 YAML front matter（从首个 `---` 到下一个 `---` 的整段）。
- 标题夸张或偏离正文：`soften_title()`
  - 如果 `fix_suggestion` 中包含明确替代标题，直接采用。
  - 否则采用“最小改动去夸张”规则（例如去掉“24/7 全天候开发团队”等易误读短语，保留事实性描述）。
- 重复段落：`dedupe_sections()`
  - 优先按标题锚点（如 `/part x`）进行块级去重。
  - 兜底按相似度阈值（段落 hash/窗口）识别重复块，保留一处。
- AI 痕迹/对话式引导：`remove_ai_cta_or_convert()`
  - 对典型“你现在…？”类收尾，替换为陈述式收尾模板（不引入新事实）。
- 图片引用缺乏引导语：`add_image_leadin()`
  - 对每个 `![alt](url)` 在前一行插入一句引导语（可引用 alt 文案）。

幂等性要求：每条规则必须可重复执行且不会重复插入/越改越多。

#### 2) LLMFallbackFixer（可选兜底）

仅当 RuleFixer 无法覆盖的 issues 仍存在时触发。

关键约束：

- 单次调用强制“硬超时”（建议 60–120 秒），不沿用全局 900 秒。
- 默认 `max_attempts=1`，避免把尾部耗时拉爆。
- 必须通过既有护栏校验：
  - 引用块 URL 必须仍在引用块中
  - 疑似截断检测（结构缺失 + 过短）
- 任一失败 → 回退到规则修复稿，仍写 `09-final-fixed.md`，并写明回退原因。

### 处理流程

1. 读取 `08-final-check.json` 得到 issues
2. 对 `07-final-candidate.md` 依次应用 RuleFixer 规则集
3. 若 issues 全部被规则覆盖 → 写 `09-final-fixed.md`，结束
4. 若仍有未覆盖 issues → 触发 LLMFallbackFixer（硬超时、最多 1 次）
5. LLM 输出通过校验 → 写 `09-final-fixed.md`
6. LLM 超时/异常/校验失败 → 写 `09-final-fixed.md = 规则修复稿`，并记录 fallback trace

## 产物与 trace 规范

为保证排查能力，新增或强化以下 trace：

### 必须产物

- `09-final-fixed.md`
- `diff.assets/targeted-fix/07-final-candidate_vs_09-final-fixed.patch`

### 规则修复 trace

- `trace.assets/targeted-fix/rules.json`
  - 结构包含：命中的 issue 类型、执行的规则、修改摘要、覆盖/未覆盖 issues 列表。

### 兜底与回退 trace

- `trace.assets/targeted-fix/llm.attempt-1.error.txt`（若超时/异常）
- `trace.assets/targeted-fix/fallback.json`（任何回退都必须有）
  - 字段建议：`checked_at`、`timeout_seconds`、`reason`、`uncovered_issues`、`behavior`。

## 配置建议

新增 targeted-fix 专属配置（名称待实现阶段确定）：

- `X2W_TARGETED_FIX_TIMEOUT_SECONDS`（默认 90）
- `X2W_TARGETED_FIX_MAX_ATTEMPTS`（默认 1）
- `X2W_TARGETED_FIX_ENABLE_LLM_FALLBACK`（默认 true；允许在某些环境直接禁用兜底）

## 测试策略

- 单元测试：
  - frontmatter 删除正确、幂等
  - 图片引导语插入正确、幂等
  - 去重在有明确重复块时生效
- 集成测试：
  - 构造 `08-final-check.json`（含多条 issues），验证 RuleFixer 能覆盖并写出 `09-final-fixed.md`
  - 模拟 LLM 超时（抛 `APITimeoutError`），验证回退逻辑：写 fallback trace、仍然写 `09-final-fixed.md`

## 相关图示

见：

- `diagram/targeted-fix-redesign/targeted-fix-flow.svg`
- `diagram/targeted-fix-redesign/targeted-fix-flow@2x.png`


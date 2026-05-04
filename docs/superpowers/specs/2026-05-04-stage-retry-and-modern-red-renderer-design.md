# x-to-wechat-agent 阶段重试与 modern red 内嵌渲染设计

## 1. 背景

当前仓库的任务执行模型是单 job、固定五阶段、原地写产物：

1. `x-fetch`
2. `translate`
3. `review`
4. `wechat-rewrite`
5. `render-html`

现状存在两个缺口：

- 任务一旦在中间阶段失败，只能整体重新跑，无法从失败点恢复。
- `render-html` 当前使用仓库内的简化模板，和目标参考实现 `baoyu-markdown-to-html --theme modern --color red` 的结构与视觉存在明显差距。

本设计在不推翻现有 job 模型的前提下，同时补足：

- 每个阶段都可重试
- 默认主入口强调“失败阶段重试”
- 高级入口支持“从任意阶段重跑”
- `render-html` 改为仓库内置、可版本化、可测试的 `modern red` 渲染实现

## 2. 目标与非目标

### 2.1 目标

- 支持从指定阶段重新执行，并继续串行执行后续阶段直到结束。
- 保持单 job / 单工作目录模型，不引入新的 run 实体。
- 对用户默认暴露“失败阶段重试”，同时保留“从任意阶段重跑”的高级能力。
- `render-html` 不再依赖外部 skill 路径；所需模板、样式、逻辑直接进入本仓库维护。
- 最终 HTML 在主要 DOM 结构和主要视觉样式上尽量对齐 `modern red` 模式。

### 2.2 非目标

- 不引入多 run 历史列表或 run 版本浏览器。
- 不引入并行阶段执行或新的状态机类型。
- 不在这次改动中一次性搬运 `baoyu-markdown-to-html` 的全部主题与全部 CLI 功能。
- 不改变现有固定阶段顺序与固定产物命名。

## 3. 总体方案

### 3.1 阶段重试模型

采用“同一个 job 原地重跑”的模式。

- 不新建 job
- 不新建 run 目录
- 重跑时清理目标阶段及后续阶段的产物与元数据
- 保留目标阶段之前已经成功的结果
- 任务重新进入 `running`
- 流水线从指定阶段开始继续跑到 `render-html`

这种模型与当前仓库最一致：

- `artifacts/<job_id>/` 继续作为唯一真相目录
- `job.json` 继续表示当前最新有效结果
- 前端现有轮询模型无需推翻

### 3.2 渲染器模型

`render-html` 仍然保持“Python 调用本仓库 Node renderer”的边界，但 renderer 的实现改为：

- 把 `baoyu-markdown-to-html` 中本项目真正需要的 `modern red` 实现子集 vendor 到本仓库
- 运行时不再读取或调用 `/Users/bytedance/.agents/skills/baoyu-markdown-to-html`
- 样式、模板、必要辅助函数、必要图片占位替换逻辑都在仓库内维护

目标是：

- 同一份 Markdown 输入，输出 HTML 的主要结构与观感尽量向 `modern red` 对齐
- 后续修改、测试、构建、发布都只依赖当前仓库

## 4. 详细设计：阶段重试

### 4.1 用户语义

支持两种重试模式：

#### 模式 A：失败阶段重试

- 只允许对失败任务使用
- 目标阶段必须等于当前失败阶段
- 作为默认主按钮对外暴露
- 适合“失败恢复”主路径

#### 模式 B：从任意阶段重跑

- 允许从任意合法阶段开始重新执行
- 对 `succeeded` 和 `failed` 任务都可用
- 作为高级操作入口提供
- 适合调试或内容迭代，例如只重跑 `wechat-rewrite` 或 `render-html`

默认产品策略采用 `C`：

- 主路径用“失败阶段重试”
- 高级路径用“从任意阶段重跑”

### 4.2 API 设计

新增接口：

`POST /api/jobs/{job_id}/retry`

请求体：

```json
{
  "stage": "review",
  "mode": "failed-stage"
}
```

其中：

- `stage` 必须属于固定 stage 集合
- `mode` 允许值：
  - `failed-stage`
  - `from-stage`

返回值沿用当前 run 风格：

```json
{
  "job_id": "...",
  "status": "accepted",
  "stage": "review",
  "mode": "from-stage"
}
```

### 4.3 接口校验规则

- `job` 不存在：返回 `404`
- `job.status == running`：返回 `409`
- `stage` 非法：返回 `422` 或 `400`
- `mode == failed-stage` 且 job 不是 `failed`：返回 `409`
- `mode == failed-stage` 但 `stage != current_stage`：返回 `409`
- `mode == from-stage` 且 job 为 `pending`：返回 `409`

### 4.4 PipelineRunner 扩展

`PipelineRunner` 从“只能从第一阶段执行”扩展为“从任意指定阶段开始执行”。

新增能力：

- 解析起始阶段
- 截取从该阶段到末尾的阶段序列
- 先执行重置逻辑
- 再按现有串行方式执行剩余阶段

保持不变：

- `_run_stage()` 的分发逻辑
- `_record_stage_success()` / `_record_stage_failure()` 的记录方式
- 统一错误归一化逻辑

### 4.5 JobStore 扩展

需要在 `JobStore` 新增一个“按阶段重置后续结果”的能力。

给定起始阶段 `stage`，它需要：

1. 找到 `stage` 在固定阶段顺序中的索引
2. 计算该阶段及其后续阶段集合
3. 删除这些阶段对应的产物文件（如果存在）
4. 从 `job.json` 中移除这些阶段的：
   - `stage_errors`
   - `stage_durations`
   - `stage_models`
   - `prompt_versions`
5. 清理 terminal 时间戳与状态，使任务重新回到可运行态

重置后，任务将重新由 `PipelineRunner` 置为 `running`。

### 4.6 产物覆盖规则

固定映射：

- `x-fetch -> 01-source.md`
- `translate -> 02-translation.md`
- `review -> 03-reviewed.md`
- `wechat-rewrite -> 04-wechat.md`
- `render-html -> 05-wechat.html`

重跑时：

- 从 `translate` 开始：保留 `01-source.md`，删除其后四类结果中的后三类与本阶段产物
- 从 `review` 开始：保留 `01-source.md` 和 `02-translation.md`
- 从 `render-html` 开始：只删除 `05-wechat.html`

### 4.7 并发控制

继续复用现有 claim 语义，避免同时触发：

- `run`
- `retry`
- 多次重复 `retry`

实现策略：

- `retry` 与 `run` 共用一套 claim 文件机制
- 已处于 `running` 或已有有效 claim 的 job 不允许再次启动

## 5. 详细设计：前端重试交互

### 5.1 默认入口

在 `JobStatus` 的失败阶段错误卡片中增加按钮：

- `重试此阶段`

该按钮：

- 仅在任务失败时展示
- 自动使用：
  - `mode = failed-stage`
  - `stage = job.current_stage`

### 5.2 高级入口

在任务详情中增加一个轻量高级区：

- 阶段下拉框
- `从该阶段重跑` 按钮

行为：

- 对 `succeeded` 和 `failed` 任务可见
- `running` 时禁用
- `pending` 时禁用

### 5.3 前端状态处理

发起重试后：

- 清空当前缓存的 artifact 文本内容，避免继续显示旧数据
- 保持当前 job 选中状态
- 继续沿用现有 `getJob()` 轮询
- 当 job 重新进入 `running` 后，由现有进度派生逻辑刷新 UI

### 5.4 UI 文案策略

- 默认按钮强调“恢复失败任务”
- 高级按钮强调“从某阶段重新生成后续内容”
- 对 `from-stage` 模式可在 UI 提示该阶段及其后续产物会被覆盖

## 6. 详细设计：modern red 内嵌渲染器

### 6.1 目标基线

目标基线是：

`baoyu-markdown-to-html --theme modern --color red`

这里的“一致”优先指：

- HTML 主体结构
- 主要容器层次
- 标题区结构
- 正文排版风格
- blockquote / code / table / image 等关键元素样式

### 6.2 依赖策略

不允许运行时依赖以下路径：

- `/Users/bytedance/.agents/skills/baoyu-markdown-to-html/...`

允许的方式是 vendor 必要子集到本仓库，例如进入：

- `packages/renderer/src/vendor/...`

或等价的 renderer 内部目录。

此 vendor 子集仅包含本仓库当前需要的能力。

### 6.3 需要内嵌的能力子集

最小必要能力包括：

- frontmatter 解析
- title / summary 提取中的必要部分
- `keepTitle` 相关正文处理
- `modern` 主题模板与样式
- `red` 主色配置
- 内容图片占位替换与回填
- Markdown 渲染的必要包裹结构

不要求本次全部内嵌：

- 其他主题
- 全部 CLI 参数
- 所有代码高亮主题
- 引用链接到底部的完整引用系统
- 阅读时长/字数统计

除非实现过程中发现 `modern red` 的正确输出依赖其中某一项，那就仅补齐其必要子集。

### 6.4 当前 renderer 的演进方式

当前仓库 renderer：

- `packages/renderer/src/render.ts`
- `packages/renderer/src/template.ts`

设计上将其改造成：

- 保留 `index.ts` 作为仓库 CLI 入口
- 用仓库内嵌的 modern red 渲染实现替代当前简化模板输出
- 继续保留现有安全措施：
  - 顶层 markdown fence 去除
  - 不安全链接方案过滤
  - HTML 转义保护

### 6.5 HTML 对齐策略

不追求字节级一致，但要求：

- 同类内容的 DOM 层次尽量一致
- 关键 class / wrapper 结构尽量一致
- 主要视觉效果对齐到“用户肉眼基本等价”

允许差异：

- 非关键属性顺序
- 轻微的空白/换行差异
- 与当前仓库无关的扩展块

## 7. 错误处理

### 7.1 阶段重试相关

- 非法模式或非法阶段：返回明确错误，不静默回退
- 尝试重试运行中任务：返回冲突错误
- 重置阶段过程中发生文件删除或元数据写入异常：
  - 不保留半完成状态
  - 优先保证 `job.json` 与产物目录一致

### 7.2 renderer 相关

- 若 vendor 的 renderer 构建缺失：沿用当前 `render_html.py` 的 fail-fast 行为，给出清晰错误
- 若 modern red 模板渲染失败：
  - 让 `render-html` 阶段失败
  - 通过 `StageError` 暴露结构化错误

## 8. 测试方案

### 8.1 后端单测

新增用例覆盖：

- 从失败阶段重试成功
- 从任意阶段重跑成功
- 从 `render-html` 重跑只覆盖 HTML
- 从 `review` 重跑会覆盖 `03/04/05`
- `running` 状态禁止 retry
- `failed-stage` 模式下阶段不匹配时报错
- retry 后 `stage_errors` / `stage_durations` / `stage_models` / `prompt_versions` 清理正确

### 8.2 API 测试

新增路由测试覆盖：

- `POST /api/jobs/{job_id}/retry` 正常返回 `202`
- 非法阶段 / 非法模式
- 任务不存在
- 任务运行中冲突
- `failed-stage` 的失败任务校验

### 8.3 前端测试

新增测试覆盖：

- 失败阶段卡片展示 `重试此阶段`
- 点击后调用 retry API
- 高级入口可选择阶段并发起 `from-stage`
- 运行中状态下按钮禁用
- 重跑后旧 artifact 内容被清空并重新加载

### 8.4 renderer 测试

新增或重写 renderer 测试：

- 标题提取
- frontmatter title 覆盖
- 顶层 markdown fence 去除
- blockquote 输出结构
- code block 输出结构
- table 输出结构
- image 输出结构
- 不安全链接过滤
- `modern red` 样例快照或关键片段断言

## 9. 实施顺序

建议实现顺序：

1. 后端 `retry` 能力与 `JobStore` 重置逻辑
2. API 路由与后端测试
3. 前端失败阶段重试按钮与高级入口
4. renderer vendor 与 `modern red` 替换
5. renderer 对齐测试与端到端链路测试

## 10. 风险与控制

### 风险 1：原地重跑导致 job 状态与产物不一致

控制：

- 所有重置逻辑收口到 `JobStore`
- 用测试锁定“按阶段清理”的精确范围

### 风险 2：modern red 搬运过大，导致维护成本失控

控制：

- 只 vendor 本项目所需最小子集
- 保留边界文档，避免后续把整个外部 skill 当黑盒继续复制

### 风险 3：对齐目标模糊，导致“像但不一致”

控制：

- 明确以 `--theme modern --color red` 为基线
- 用固定 Markdown 样例做结构断言和渲染快照

## 11. 最终决策摘要

- 阶段重试采用单 job 原地重跑，不引入新 run 模型。
- 默认主入口支持失败阶段重试，高级入口支持从任意阶段重跑。
- `retry` 会清理目标阶段及后续阶段的产物与元数据，然后从目标阶段跑到结束。
- `render-html` 改为仓库内部维护的 modern red 渲染实现，不依赖外部 skill 路径。
- modern red 对齐目标是 HTML 结构与主要视觉风格尽量高度一致，而不是仅做颜色近似。

# x-to-wechat-agent 设计文档

## 1. 目标

构建一个完整、可本地运行、面向生产可用性的 AI Agent 仓库，项目名为 `x-to-wechat-agent`。

该仓库的目标是：

- 接收一个单独的 `X URL`
- 获取对应的单条 tweet 或单篇 X Article 正文
- 自动完成中文翻译、译文审校、公众号风格改写
- 生成适合微信公众号发布的 HTML
- 在本地 Web UI 中展示全过程状态与全部中间产物

第一版范围严格限定如下：

- 输入形态：仅支持单条 tweet URL 或单篇 X Article URL
- 运行形态：本地 Web UI
- 执行方式：全自动串行流水线，一次提交后自动跑完 5 个阶段
- 模型接入：支持可配置多模型架构，第一版默认优先支持 `Qwen`
- Prompt 语言：所有核心 Prompt 默认使用中文

不在第一版范围内的内容：

- tweet thread 聚合
- 批量 URL 处理
- 人工逐步审批式工作流
- 公众号直接发布
- 云端多用户部署

## 2. 核心原则

### 2.1 产品原则

- 用户只面对一个本地 Web 应用，不需要手动操作多段脚本
- 所有关键中间结果可见、可追踪、可导出
- 错误必须可定位，不能只显示“失败”
- 第一版只做单 URL、单任务主路径，不为了“完整”而扩大范围

### 2.2 工程原则

- `Python` 负责 Agent 编排、任务管理、内容流水线与模型网关
- `Node.js` 负责 Markdown 到微信公众号 HTML 的渲染能力
- `Node.js` 作为内部工具链，由 `Python` 子进程调用，不单独暴露复杂服务边界
- 所有阶段都使用统一的输入输出契约，方便未来扩展线程、批量、人工介入模式

### 2.3 Prompt 原则

- 第一版所有核心 Prompt 使用中文编写
- Prompt 不混杂中英说明，避免模型角色和输出约束漂移
- Prompt 与阶段绑定，按文件独立管理与版本化
- Prompt 输出约束优先保证 Markdown 干净、结构稳定、便于后处理

## 3. 方案选择与理由

在设计阶段考虑过三种方案：

### 方案 A：Python 单体后端 + Node 独立渲染服务

优点：职责清晰。

缺点：用户需要理解两个本地服务的运行关系，运维复杂度上升。

### 方案 B：Python 主控 + Node 内部工具链 + 本地 Web UI

优点：

- 用户只启动一个本地应用
- Python 更适合 Agent 编排、Prompt 管理、状态机与多模型适配
- Node 只承担渲染职责，边界清晰
- 后续扩展多模型、多模式、多输入类型时，整体结构更稳定

缺点：需要处理 Python 调 Node 子进程时的超时、错误码和输出契约。

### 方案 C：Node 为主工程，Python 为抓取或 AI worker

优点：Web 工程化顺手。

缺点：Agent 编排和 Prompt 管理不如 Python 自然，核心智能链路会分散。

### 结论

采用 **方案 B**：`Python 主控 + Node 内部渲染工具链 + 本地 Web UI`。

这是用户体验最简单、内部架构最稳定、最适合后续演进的方案。

## 4. 总体架构

### 4.1 顶层结构

系统由三层组成：

1. `Web UI`：本地浏览器访问的用户入口
2. `Python Agent Core`：任务编排、阶段执行、模型调用、日志和产物管理
3. `Node Renderer`：微信公众号 HTML 渲染器

### 4.2 数据流

用户在 Web UI 提交一个 `X URL` 后，后端创建一个 `job`，并按顺序执行以下阶段：

1. `x-fetch`
2. `translate`
3. `review`
4. `wechat-rewrite`
5. `render-html`

每个阶段都读取上一步产物，生成本阶段产物，并更新任务状态。

### 4.3 用户体验

Web UI 第一版负责：

- 输入 URL
- 启动任务
- 查看当前运行阶段
- 查看阶段日志
- 预览所有中间稿件
- 预览最终 HTML
- 导出全部产物

Web UI 不承担复杂编排逻辑，只展示后端暴露的任务状态和产物内容。

## 5. 运行流与产物模型

### 5.1 任务生命周期

一次处理对应一个 `job`，包含以下状态：

- `pending`
- `running`
- `succeeded`
- `failed`

在 `running` 状态下，还需要记录当前阶段：

- `x-fetch`
- `translate`
- `review`
- `wechat-rewrite`
- `render-html`

### 5.2 阶段产物

每次运行都创建一个独立 `run directory`。目录中固定保存以下产物：

- `01-source.md`
- `02-translation.md`
- `03-reviewed.md`
- `04-wechat.md`
- `05-wechat.html`
- `job.json`
- `logs/`

其中：

- `01-source.md` 为抓取并清洗后的原始 Markdown
- `02-translation.md` 为忠实中文翻译稿
- `03-reviewed.md` 为中文审校稿
- `04-wechat.md` 为公众号文章改写稿
- `05-wechat.html` 为最终渲染产物

### 5.3 结构化元数据

`job.json` 至少包含：

- 原始 URL
- 任务 ID
- 创建时间、开始时间、结束时间
- 当前状态与当前阶段
- 每阶段使用的 provider/model
- 每阶段的 Prompt 版本标识
- 各阶段耗时
- 各阶段错误信息

## 6. 模块边界与职责

### 6.1 `x-fetch`

该模块参考 `baoyu-danger-x-to-markdown` 的实现思路，但不会直接依赖该 skill。

职责：

- 接收单个 X URL
- 使用真实浏览器 + 用户本地登录态抓取内容
- 提取页面正文与必要元信息
- 输出标准化 Markdown

第一版设计要求：

- 优先依赖用户本地登录态，保证抓取成功率
- 支持本地 session/cookies 复用
- 将抓取逻辑封装为仓库内建能力，而不是外部调用链

不做：

- thread 聚合
- 时间线抓取
- 用户主页采集

### 6.2 `translate`

该模块参考 `technical-translate` 的能力边界。

职责：

- 将 `source.md` 翻译成忠实、自然、术语稳定的中文稿
- 不主动转公众号文风
- 输出干净 Markdown

设计要求：

- Prompt 使用中文
- 保持段落结构尽量稳定
- 保留必要专有名词

### 6.3 `review`

该模块采用用户提供的 `content-reviewer` 规则，Prompt 改写为中文表达。

职责：

- 修正错译和漏译
- 提升中文可读性
- 拆分过长句子
- 保持原始信息结构
- 不新增事实

输出为干净 Markdown。

### 6.4 `wechat-rewrite`

该模块采用用户提供的 `wechat-rewriter` 规则，Prompt 改写为中文表达。

职责：

- 生成适合公众号传播的标题
- 重组文章节奏为“引子—洞察—解释—结论”
- 将翻译稿转为更自然的中文内容表达
- 增加阅读节奏与重点强调
- 不编造事实

输出为干净 Markdown。

### 6.5 `renderer`

该模块参考 `baoyu-markdown-to-html` 的能力设计。

职责：

- 接收 `wechat.md`
- 渲染为适合微信公众号的 HTML
- 处理标题、段落、引用、列表、代码块、强调等常见 Markdown 结构

后续扩展方向：

- 主题样式
- 外链转底部引用
- 代码高亮样式
- 图片与注释块样式

### 6.6 `model gateway`

职责：

- 提供统一的 provider/model 抽象
- 屏蔽不同模型提供方参数差异
- 为阶段选择合适模型并注入统一调用参数

第一版要求：

- 默认支持 `Qwen`
- 架构兼容更多 `OpenAI-compatible` 接口
- 模型选择通过配置决定，而不是写死在流程代码中

### 6.7 `job manager`

职责：

- 创建任务
- 调度阶段执行
- 写入状态与日志
- 管理产物路径
- 暴露任务查询接口给 Web UI

这是第一版后端的核心骨架。

## 7. Prompt 设计要求

### 7.1 总则

- 所有阶段 Prompt 使用中文
- System Prompt、阶段说明、格式约束、禁止事项均使用中文
- Prompt 文件独立保存，避免硬编码在业务代码里
- Prompt 输出必须与阶段 schema 对齐

### 7.2 翻译阶段 Prompt 要求

- 目标是忠实翻译，不是改写
- 优先保证语义、术语与逻辑关系准确
- 输出 Markdown，不加解释性前后缀

### 7.3 审校阶段 Prompt 要求

- 明确要求检查语义错误、错译、漏译、表达僵硬
- 明确要求不新增事实
- 明确要求保留原始结构主线

### 7.4 公众号改写阶段 Prompt 要求

- 明确要求生成更像中文原生文章的表达
- 明确要求增强标题、开头钩子、节奏和重点
- 明确要求不可虚构事实或扩展未给出的信息

## 8. 配置设计

### 8.1 本地配置项

第一版至少支持以下配置：

- 模型 provider
- 模型名称
- 各阶段模型映射
- 输出目录
- 最大重试次数
- 阶段超时时间
- X 抓取浏览器配置
- 本地 session/cookies 存储位置

### 8.2 密钥与安全

- 所有模型密钥都通过本地环境变量或本地配置文件提供
- X 登录态仅保存在本机
- 不将 cookies、session、密钥写入可公开目录
- 日志中默认脱敏敏感字段

## 9. 错误处理

### 9.1 错误分类

`x-fetch` 错误至少区分：

- 登录态失效
- URL 不支持
- 页面结构变化
- 提取结果为空

`LLM` 阶段错误至少区分：

- 模型调用失败
- 返回为空
- 返回格式不合法
- 超时

`renderer` 错误至少区分：

- 输入 Markdown 不合法
- 子进程执行失败
- HTML 输出为空

### 9.2 错误暴露方式

每个阶段都输出结构化错误对象，至少包括：

- 错误类型
- 错误消息
- 所属阶段
- 是否可重试
- 建议处理方式

Web UI 要能显示“失败在哪一段、为什么失败、建议怎么处理”。

## 10. 测试策略

### 10.1 单元测试

覆盖以下重点：

- URL 解析与类型识别
- 阶段输入输出 schema 校验
- Prompt 组装
- 任务状态迁移
- 产物路径生成
- 配置解析

### 10.2 集成测试

至少覆盖一条固定样例链路：

- 从一个稳定样例 `source.md` 出发
- 跑通 `translate -> review -> wechat-rewrite -> render-html`
- 校验输出文件存在且内容结构满足约束

### 10.3 抓取测试

不要求在 CI 中直接依赖线上 X 页面。

可采用：

- 录制样例
- 可替换适配层
- 本地手工验收脚本

以保证核心业务不会因为外部页面波动而让测试失去稳定性。

## 11. production-ready 定义

本项目第一版中，“production-ready” 的含义不是功能无限扩张，而是本地可重复、可配置、可观察、可诊断。

必须满足：

- 本地可安装
- 本地可启动
- 配置路径清晰
- 失败可追踪
- 产物可验证
- 核心链路可测试

不要求第一版解决所有输入类型或所有编辑场景。

## 12. 建议的仓库结构

```text
x-to-wechat-agent/
  apps/
    web/
  agent/
    core/
    stages/
    prompts/
    models/
    jobs/
  packages/
    renderer/
    x_fetch/
  artifacts/
  tests/
  docs/
    superpowers/
      specs/
```

说明：

- `apps/web`：本地 Web UI
- `agent/core`：流程编排核心
- `agent/stages`：5 个阶段的实现
- `agent/prompts`：中文 Prompt 模板
- `agent/models`：provider/model 网关
- `agent/jobs`：任务与状态管理
- `packages/renderer`：Node 渲染工具链
- `packages/x_fetch`：X 内容获取能力
- `artifacts`：运行产物目录
- `tests`：自动化测试

## 13. 后续可演进方向

明确预留但不在第一版实现：

- thread 支持
- 多 URL 批处理
- 人工逐步审核模式
- 公众号直接发布
- 多主题 HTML 模板
- 图文混排增强
- 多租户或团队版部署

## 14. 实现边界总结

第一版必须交付的最小完整系统是：

- 一个本地 Web UI
- 一个 Python Agent Core
- 一个 Node HTML Renderer
- 一个内建的 X 抓取模块
- 三个中文 Prompt 驱动的文本阶段：翻译、审校、公众号改写
- 一套统一任务状态、日志、产物管理机制

这是一个范围收敛但结构完整的本地 AI Agent 仓库，可以在不推翻架构的前提下继续演进。

# Graph Report - /Users/bytedance/GolandProjects/x-weichat  (2026-05-04)

## Corpus Check
- 74 files · ~339,300 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 745 nodes · 1883 edges · 47 communities detected
- Extraction: 58% EXTRACTED · 42% INFERRED · 0% AMBIGUOUS · INFERRED: 793 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]

## God Nodes (most connected - your core abstractions)
1. `JobStore` - 136 edges
2. `Settings` - 64 edges
3. `ModelGateway` - 54 edges
4. `PipelineRunner` - 46 edges
5. `StageContext` - 39 edges
6. `test_translate_review_route_rewrite_final_output_render_html_chain_uses_fixed_sample_and_writes_artifacts()` - 19 edges
7. `run_x_fetch()` - 19 edges
8. `StageError` - 19 edges
9. `StageModelInfo` - 17 edges
10. `parse_x_html()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `test_stage_context_keeps_job_identity()` --calls--> `StageContext`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_pipeline.py → agent/stages/base.py
- `app_bundle()` --calls--> `PipelineRunner`  [INFERRED]
  tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/core/pipeline.py
- `app_bundle()` --calls--> `Settings`  [INFERRED]
  tests/test_api_jobs.py → agent/config.py
- `test_create_app_with_runner_fills_missing_gateway_and_settings()` --calls--> `PipelineRunner`  [INFERRED]
  tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/core/pipeline.py
- `test_create_app_with_runner_fills_missing_gateway_and_settings()` --calls--> `Settings`  [INFERRED]
  tests/test_api_jobs.py → agent/config.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.04
Nodes (103): ChunkPromptContext, 优先按段落切分 Markdown，尽量保持结构边界完整。, 跨 stage 传递的最小上下文。      只保留任务链路里稳定且通用的信息，避免某个阶段偷偷依赖过多隐式状态。, 跨 stage 传递的最小上下文。      只保留任务链路里稳定且通用的信息，避免某个阶段偷偷依赖过多隐式状态。, 优先按段落切分 Markdown，尽量保持结构边界完整。, 去掉模型把整段结果包成 ```markdown 的外层围栏。      多块拼接时如果直接保留这些围栏，最终产物会出现大量原始 ```，     对后续 sta, 描述当前分块在整篇文档中的位置。      某些 stage（例如公众号改写）在多块场景下需要根据位置调整提示词：     首块负责开篇，中间块只续写，末块再自, 读取 stage 输入产物，统一走 `JobStore`。 (+95 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (61): create_app(), StageProbeResult, JobStore, app_bundle(), test_create_app_with_complete_runner_skips_default_gateway_construction(), test_create_app_with_runner_fills_missing_gateway_and_settings(), test_create_job_accepts_x_article_url(), test_create_job_accepts_x_singular_i_article_url() (+53 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (49): buildCookieHeader(), buildTweetDetailFieldToggleMap(), extractArticleFromEntity(), extractArticleFromTweet(), extractTweetFromPayload(), fetchArticleEntityById(), fetchTweetDetail(), fetchTweetResult() (+41 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (32): PipelineRunner, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, 把底层异常归一成前端可展示的阶段错误。          `retryable` 在这里表示“值得再次尝试”，既包含网关层会自动重试的瞬时错误，, render_html() (+24 more)

### Community 4 - "Community 4"
Cohesion: 0.1
Nodes (41): read_cookie_file(), write_cookie_file(), buildInlineCookiesFromEnv(), buildXCookieMap(), filterXCookieMap(), findChromeExecutable(), hasRequiredXCookies(), launchChrome() (+33 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (40): fetch_x_markdown_with_skill(), fetch_x_page(), is_article_url(), _materialize_skill_media(), normalize_x_url(), 重写 skill 下载出的相对媒体路径。      需要同时覆盖：     - Markdown 图片/链接：`![](imgs/x.jpg)`、`[demo], 把 skill 产物里的 `requestedUrl` 改回用户原始输入。      skill 内部通常会使用 canonical article URL（`, 使用 Playwright 抓取页面 HTML。      这是 x-fetch 的“主路径”：     1. 先把 article URL 归一化     2 (+32 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (25): build_messages(), GatewayError, ModelGateway, 统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日, 对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。, 在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。, 按阶段探测当前配置的模型，便于启动前快速发现坏链路。, _uses_user_only_messages() (+17 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (21): HTMLParser, X content fetching package., _collect_article_blocks(), _descendant_nodes(), _descendant_text_chunks(), _direct_text_chunks(), _extract_meta(), _extract_tweet_author() (+13 more)

### Community 8 - "Community 8"
Cohesion: 0.12
Nodes (24): ApiError, createJob(), deleteJob(), fetchWithTimeout(), getArtifactText(), getJob(), getPromptText(), listJobs() (+16 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (22): BaseModel, conflict_detail(), CreateJobRequest, delete_job(), get_job(), is_supported_x_url(), retry_job(), RetryJobRequest (+14 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (17): escapeRegExp(), normalizeHeadingText(), removeFirstHeading(), wrapModernRedContent(), runCli(), decodeHtmlEntitiesForUrlCheck(), escapeHtml(), escapeHtmlAttribute() (+9 more)

### Community 11 - "Community 11"
Cohesion: 0.14
Nodes (16): fetchXCookiesViaCdp(), CdpConnection, discoverRunningChromeDebugPort(), fetchJson(), fetchWithTimeout(), findExistingChromeDebugPort(), getDefaultChromeUserDataDirs(), getFreePort() (+8 more)

### Community 12 - "Community 12"
Cohesion: 0.16
Nodes (22): buildEntityLookup(), buildMediaById(), buildMediaLinkMap(), buildTweetUrl(), coerceArticleEntity(), collectMediaAssets(), escapeMarkdownAlt(), extractReferencedTweetIds() (+14 more)

### Community 13 - "Community 13"
Cohesion: 0.24
Nodes (17): buildFileName(), collectMarkdownLinkCandidates(), isPlausibleMediaUrl(), localizeMarkdownMedia(), normalizeContentType(), normalizeExtension(), resolveExtensionFromUrl(), resolveFileStem() (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.3
Nodes (12): buildTweetUrl(), coerceThread(), escapeMarkdownAlt(), formatQuotedTweetMarkdown(), formatThreadMarkdown(), formatThreadTweetsMarkdown(), formatTweetMarkdown(), parsePhotos() (+4 more)

### Community 15 - "Community 15"
Cohesion: 0.2
Nodes (2): maybePromptResponse(), textResponse()

### Community 16 - "Community 16"
Cohesion: 0.4
Nodes (4): get_artifact(), get_prompt(), 返回任务产物。      Markdown 以纯文本返回，HTML 以 `text/html` 返回，     方便前端分别用于源码查看和 iframe 预览。, 暴露当前 Prompt 文本，便于在 UI 中直接查看每个阶段的提示词。

### Community 17 - "Community 17"
Cohesion: 0.5
Nodes (0): 

### Community 18 - "Community 18"
Cohesion: 0.67
Nodes (0): 

### Community 19 - "Community 19"
Cohesion: 1.0
Nodes (0): 

### Community 20 - "Community 20"
Cohesion: 1.0
Nodes (0): 

### Community 21 - "Community 21"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Community 22"
Cohesion: 1.0
Nodes (0): 

### Community 23 - "Community 23"
Cohesion: 1.0
Nodes (0): 

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): 统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): 对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): 在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): 按阶段探测当前配置的模型，便于启动前快速发现坏链路。

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): 返回任务产物。      Markdown 以纯文本返回，HTML 以 `text/html` 返回，     方便前端分别用于源码查看和 iframe 预览。

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): 暴露当前 Prompt 文本，便于在 UI 中直接查看每个阶段的提示词。

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): 统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): 对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): 在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): 按阶段探测当前配置的模型，便于启动前快速发现坏链路。

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): 统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): 对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): 调用 `baoyu-danger-x-to-markdown` 作为 article 抓取兜底。      我们自己的第一优先级仍然是 Playwright +

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (1): 把 skill 产物里的 `requestedUrl` 改回用户原始输入。      skill 内部通常会使用 canonical article URL（`

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (1): 使用 Playwright 抓取页面 HTML。      这是 x-fetch 的“主路径”：     1. 先把 article URL 归一化     2

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (1): 把多种 X article URL 形态归一成 `/i/article/<id>`。      背景：同一篇 X Article 可能同时存在     - `h

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (1): 判断一个 URL 在归一化后是否属于 X Article。

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (1): 调用 `baoyu-danger-x-to-markdown` 作为 article 抓取兜底。      我们自己的第一优先级仍然是 Playwright +

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): 把 skill 产物里的 `requestedUrl` 改回用户原始输入。      skill 内部通常会使用 canonical article URL（`

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (1): 使用 Playwright 抓取页面 HTML。      这是 x-fetch 的“主路径”：     1. 先把 article URL 归一化     2

## Knowledge Gaps
- **32 isolated node(s):** `统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日`, `对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。`, `在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。`, `按阶段探测当前配置的模型，便于启动前快速发现坏链路。`, `返回任务产物。      Markdown 以纯文本返回，HTML 以 `text/html` 返回，     方便前端分别用于源码查看和 iframe 预览。` (+27 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 19`** (2 nodes): `togglePrompt()`, `JobStatus.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (2 nodes): `JobForm()`, `JobForm.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 21`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (1 nodes): `styles.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `types.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `HtmlPreview.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `按阶段探测当前配置的模型，便于启动前快速发现坏链路。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `返回任务产物。      Markdown 以纯文本返回，HTML 以 `text/html` 返回，     方便前端分别用于源码查看和 iframe 预览。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `暴露当前 Prompt 文本，便于在 UI 中直接查看每个阶段的提示词。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `在真正运行阶段前做一次极小请求，提前暴露模型不可达/未开通等问题。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `按阶段探测当前配置的模型，便于启动前快速发现坏链路。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `统一封装 OpenAI-compatible 调用。      这里把超时、重试和响应校验放在一处，避免各 stage 自己处理网络抖动，     也让流水线日`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `对单个 Markdown 任务发起生成请求，并在可重试错误上自动重试。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `调用 `baoyu-danger-x-to-markdown` 作为 article 抓取兜底。      我们自己的第一优先级仍然是 Playwright +`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `把 skill 产物里的 `requestedUrl` 改回用户原始输入。      skill 内部通常会使用 canonical article URL（``
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `使用 Playwright 抓取页面 HTML。      这是 x-fetch 的“主路径”：     1. 先把 article URL 归一化     2`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `把多种 X article URL 形态归一成 `/i/article/<id>`。      背景：同一篇 X Article 可能同时存在     - `h`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `判断一个 URL 在归一化后是否属于 X Article。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `调用 `baoyu-danger-x-to-markdown` 作为 article 抓取兜底。      我们自己的第一优先级仍然是 Playwright +`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `把 skill 产物里的 `requestedUrl` 改回用户原始输入。      skill 内部通常会使用 canonical article URL（``
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `使用 Playwright 抓取页面 HTML。      这是 x-fetch 的“主路径”：     1. 先把 article URL 归一化     2`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JobStore` connect `Community 1` to `Community 0`, `Community 3`, `Community 5`?**
  _High betweenness centrality (0.238) - this node is a cross-community bridge._
- **Why does `fetchXCookiesViaCdp()` connect `Community 11` to `Community 4`?**
  _High betweenness centrality (0.235) - this node is a cross-community bridge._
- **Why does `run_x_fetch()` connect `Community 5` to `Community 0`, `Community 1`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Are the 105 inferred relationships involving `JobStore` (e.g. with `FakeGateway` and `PipelineRunner`) actually correct?**
  _`JobStore` has 105 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `Settings` (e.g. with `FakeGateway` and `PipelineRunner`) actually correct?**
  _`Settings` has 62 INFERRED edges - model-reasoned connections that need verification._
- **Are the 46 inferred relationships involving `ModelGateway` (e.g. with `FakeMessage` and `FakeChoice`) actually correct?**
  _`ModelGateway` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `PipelineRunner` (e.g. with `FakeGateway` and `Settings`) actually correct?**
  _`PipelineRunner` has 28 INFERRED edges - model-reasoned connections that need verification._
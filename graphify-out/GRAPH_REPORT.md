# Graph Report - /Users/bytedance/GolandProjects/x-weichat  (2026-05-03)

## Corpus Check
- 47 files · ~17,095 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 285 nodes · 626 edges · 21 communities detected
- Extraction: 55% EXTRACTED · 45% INFERRED · 0% AMBIGUOUS · INFERRED: 280 edges (avg confidence: 0.76)
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

## God Nodes (most connected - your core abstractions)
1. `JobStore` - 61 edges
2. `PipelineRunner` - 30 edges
3. `Settings` - 20 edges
4. `test_translate_review_wechat_rewrite_render_html_chain_uses_fixed_sample_and_writes_artifacts()` - 15 edges
5. `parse_x_html()` - 15 edges
6. `ModelGateway` - 14 edges
7. `FakeGateway` - 11 edges
8. `StageContext` - 11 edges
9. `StageModelInfo` - 11 edges
10. `_TreeHTMLParser` - 11 edges

## Surprising Connections (you probably didn't know these)
- `app_bundle()` --calls--> `JobStore`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/jobs/store.py
- `app_bundle()` --calls--> `PipelineRunner`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/core/pipeline.py
- `test_create_app_with_runner_fills_missing_gateway_and_settings()` --calls--> `JobStore`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/jobs/store.py
- `test_create_app_with_runner_fills_missing_gateway_and_settings()` --calls--> `PipelineRunner`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/core/pipeline.py
- `test_create_app_with_complete_runner_skips_default_gateway_construction()` --calls--> `JobStore`  [INFERRED]
  /Users/bytedance/GolandProjects/x-weichat/tests/test_api_jobs.py → /Users/bytedance/GolandProjects/x-weichat/agent/jobs/store.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (33): PipelineRunner, get_artifact(), StageError, StageModelInfo, JobStore, test_get_job_returns_status_for_ui(), test_claim_run_reclaim_race_surfaces_claim_conflict_not_missing_claim(), test_claim_run_reclaims_stale_claim() (+25 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (24): read_stage_markdown(), run_markdown_stage(), StageContext, load_prompt(), render_html(), renderer_cli_path(), run_render_html(), build_review_input() (+16 more)

### Community 2 - "Community 2"
Cohesion: 0.12
Nodes (20): HTMLParser, _collect_article_blocks(), _descendant_nodes(), _descendant_text_chunks(), _direct_text_chunks(), _extract_meta(), _extract_tweet_author(), _find_first_node() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.1
Nodes (20): BaseSettings, Settings, create_app(), app_bundle(), test_create_app_with_complete_runner_skips_default_gateway_construction(), test_create_app_with_runner_fills_missing_gateway_and_settings(), test_create_job_accepts_x_article_url(), test_create_job_returns_job_id() (+12 more)

### Community 4 - "Community 4"
Cohesion: 0.13
Nodes (22): fetch_x_page(), XFetchError, _is_article_shape(), _is_tweet_shape(), parse_x_html(), RuntimeError, FakeContext, test_fetch_x_page_normalizes_path_storage_state_for_new_context() (+14 more)

### Community 5 - "Community 5"
Cohesion: 0.22
Nodes (12): build_messages(), GatewayError, ModelGateway, FakeChoice, FakeClient, FakeCompletions, FakeMessage, FakeResponse (+4 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (15): BaseModel, CreateJobRequest, get_job(), is_supported_x_url(), run_job(), validate_supported_x_url(), JobRecord, StageResult (+7 more)

### Community 7 - "Community 7"
Cohesion: 0.24
Nodes (5): runCli(), decodeHtmlEntitiesForUrlCheck(), hasUnsafeUrlScheme(), renderWechatHtml(), wechatTemplate()

### Community 8 - "Community 8"
Cohesion: 0.25
Nodes (1): X content fetching package.

### Community 9 - "Community 9"
Cohesion: 0.38
Nodes (3): createJob(), getJob(), parseJson()

### Community 10 - "Community 10"
Cohesion: 0.33
Nodes (0): 

### Community 11 - "Community 11"
Cohesion: 0.5
Nodes (0): 

### Community 12 - "Community 12"
Cohesion: 1.0
Nodes (0): 

### Community 13 - "Community 13"
Cohesion: 1.0
Nodes (0): 

### Community 14 - "Community 14"
Cohesion: 1.0
Nodes (0): 

### Community 15 - "Community 15"
Cohesion: 1.0
Nodes (0): 

### Community 16 - "Community 16"
Cohesion: 1.0
Nodes (0): 

### Community 17 - "Community 17"
Cohesion: 1.0
Nodes (0): 

### Community 18 - "Community 18"
Cohesion: 1.0
Nodes (0): 

### Community 19 - "Community 19"
Cohesion: 1.0
Nodes (0): 

### Community 20 - "Community 20"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **Thin community `Community 12`** (2 nodes): `App()`, `App.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 13`** (2 nodes): `HtmlPreview()`, `HtmlPreview.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 14`** (2 nodes): `JobForm()`, `JobForm.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 15`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 16`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 17`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 18`** (1 nodes): `types.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 19`** (1 nodes): `JobStatus.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (1 nodes): `ArtifactTabs.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JobStore` connect `Community 0` to `Community 1`, `Community 3`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.239) - this node is a cross-community bridge._
- **Why does `run_x_fetch()` connect `Community 4` to `Community 0`, `Community 1`?**
  _High betweenness centrality (0.235) - this node is a cross-community bridge._
- **Why does `parse_x_html()` connect `Community 4` to `Community 2`?**
  _High betweenness centrality (0.228) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `JobStore` (e.g. with `FakeContext` and `FakeGateway`) actually correct?**
  _`JobStore` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `PipelineRunner` (e.g. with `FakeGateway` and `Settings`) actually correct?**
  _`PipelineRunner` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `Settings` (e.g. with `FakeGateway` and `PipelineRunner`) actually correct?**
  _`Settings` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `test_translate_review_wechat_rewrite_render_html_chain_uses_fixed_sample_and_writes_artifacts()` (e.g. with `JobStore` and `.create_job()`) actually correct?**
  _`test_translate_review_wechat_rewrite_render_html_chain_uses_fixed_sample_and_writes_artifacts()` has 13 INFERRED edges - model-reasoned connections that need verification._
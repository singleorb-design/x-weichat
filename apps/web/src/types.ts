export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'published'
export type StageName =
  | 'x-fetch'
  | 'translate'
  | 'review'
  | 'route'
  | 'light-polish'
  | 'final-check'
  | 'targeted-fix'
  | 'final-output'
  | 'render-html'
export type RetryMode = 'failed-stage' | 'from-stage'

export interface StageModelInfo {
  provider: string
  model: string
}

export interface StageError {
  error_type: string
  message: string
  retryable: boolean
  suggestion: string
}

export interface StageProbeResult {
  status: 'passed' | 'failed'
  message: string
  checked_at: string
}

export interface JobRecord {
  job_id: string
  url: string
  source_title?: string | null
  created_at: string
  status: JobStatus
  current_stage: StageName | null
  started_at: string | null
  finished_at: string | null
  stage_models: Record<string, StageModelInfo>
  prompt_versions: Record<string, string>
  stage_durations: Record<string, number>
  stage_errors: Record<string, StageError>
  stage_probes: Record<string, StageProbeResult>
}

export interface RetryJobRequest {
  stage: StageName
  mode: RetryMode
}

export interface RetryJobResponse {
  job_id: string
  status: string
  stage: StageName
  mode: RetryMode
}

export interface UpdateFinalMarkdownResponse {
  job_id: string
  status: string
  relative_path: string
}

export interface ApiErrorDetail {
  code?: string
  message?: string
  suggestion?: string
  can_change_stage?: boolean
}

export interface CreateJobResponse {
  job_id: string
  status: string
}

export interface BatchCreateJobsRequest {
  urls_text: string
  run?: boolean
}

export interface BatchCreateJobsItem {
  line: number
  input: string
  url: string | null
  ok: boolean
  job_id: string | null
  status: string | null
  error: string | null
}

export interface BatchCreateJobsResponse {
  items: BatchCreateJobsItem[]
  stats: {
    created: number
    scheduled: number
    invalid: number
  }
}

export interface ArtifactIndexResponse {
  job_id: string
  files: string[]
}

export interface StageHtmlPreviewRequest {
  stage: StageName
  force?: boolean
}

export interface StageHtmlPreviewResponse {
  job_id: string
  stage: StageName
  source_artifact: string
  artifact_path: string
  status: 'cached' | 'generated' | 'ready'
}

export type DiscoverySourceKind = 'account' | 'keyword' | 'recommendation'

export interface DiscoverySource {
  kind: DiscoverySourceKind
  value: string
}

export interface DiscoveryPreviewRequest {
  sources: DiscoverySource[]
  max_candidates?: number
  max_scrolls?: number
  search_mode?: 'top' | 'latest'
  min_likes?: number
  required_keywords?: string[]
}

export interface DiscoveryPreviewItem {
  canonical_url: string
  original_url: string
  likes: number
  source_kind: DiscoverySourceKind
  source_value: string
  reason: string
  score: number
  already_seen: boolean
  already_enqueued: boolean
  job_id: string | null
}

export interface DiscoveryPreviewAcceptedResponse {
  run_id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled'
}

export type DiscoveryRunPhase = 'preparing' | 'searching' | 'filtering' | 'completed'

export interface DiscoveryRunProgress {
  source_total?: number
  source_index?: number
  current_source_kind?: DiscoverySourceKind | null
  current_source_value?: string | null
  current_query?: string | null
  current_scroll?: number
  max_scrolls?: number
  raw_hits?: number
  after_likes_filter?: number
  after_keywords_filter?: number
  after_article_entity?: number
  after_article_url_extract?: number
  after_language_length_filter?: number
  duplicate_filtered?: number
  deduped_hits?: number
  suspected_reason?: string | null
  suspected_detail?: string | null
  sample?: Array<Record<string, unknown>>
  stopped_by_user?: boolean
}

export interface DiscoveryRunStatusResponse {
  run_id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled'
  current_phase: DiscoveryRunPhase | null
  progress_message: string | null
  progress_json: DiscoveryRunProgress
  stats: Record<string, number>
  error_message: string | null
  completed: boolean
}

export interface DiscoveryItemsResponse {
  run_id: string
  items: DiscoveryPreviewItem[]
}

export interface DiscoveryArtifactIndexResponse {
  run_id: string
  files: string[]
}

export type XLoginRunStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type XLoginRunPhase = 'starting_browser' | 'awaiting_login' | 'saving_state' | 'completed'

export interface XLoginRunProgress {
  login_url?: string | null
  storage_state_path?: string | null
  current_url?: string | null
}

export interface XLoginRunAcceptedResponse {
  run_id: string
  status: XLoginRunStatus
}

export interface XLoginRunStatusResponse {
  run_id: string
  status: XLoginRunStatus
  current_phase: XLoginRunPhase | null
  progress_message: string | null
  progress_json: XLoginRunProgress
  error_message: string | null
  completed: boolean
}

export type WeChatPublishRunStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type WeChatPublishRunPhase = 'starting_browser' | 'awaiting_login' | 'opening_editor' | 'filling_content' | 'saving_draft' | 'completed'

export interface StartWeChatPublishRequest {
  job_id: string
  title?: string | null
  html_artifact?: string
}

export interface WeChatPublishAcceptedResponse {
  run_id: string
  status: WeChatPublishRunStatus
}

export interface WeChatPublishRunStatusResponse {
  run_id: string
  status: WeChatPublishRunStatus
  current_phase: WeChatPublishRunPhase | null
  progress_message: string | null
  progress_json: Record<string, unknown>
  error_message: string | null
  completed: boolean
}

export interface DiscoveryEnqueueRequest {
  run_id: string
  selected_urls: string[]
  max_enqueue?: number
  auto_run?: boolean
  auto_run_limit?: number
}

export interface DiscoveryEnqueueResponse {
  run_id: string
  enqueued: Array<{ canonical_url: string; job_id: string; status: string; action: string }>
  skipped: Array<{ canonical_url: string; reason: string; job_id?: string }>
  auto_run: { requested: boolean; started: number; skipped_due_to_limit: number }
}

export interface ArtifactUrls {
  source: string
  translation: string
  reviewed: string
  polished: string
  final: string
  html: string
}

export type ArtifactKey = keyof ArtifactUrls

export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type StageName =
  | 'x-fetch'
  | 'translate'
  | 'review'
  | 'route'
  | 'light-polish'
  | 'wechat-rewrite'
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

export interface ArtifactUrls {
  source: string
  translation: string
  reviewed: string
  polished: string
  rewritten: string
  final: string
  html: string
}

export type ArtifactKey = keyof ArtifactUrls

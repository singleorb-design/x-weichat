export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface JobRecord {
  job_id: string
  url: string
  created_at: string
  status: JobStatus
  current_stage: string | null
  started_at: string | null
  finished_at: string | null
  stage_models: Record<string, Record<string, string | null>>
  prompt_versions: Record<string, string>
  stage_durations: Record<string, number>
  stage_errors: Record<string, string>
}

export interface CreateJobResponse {
  job_id: string
  status: string
}

export interface ArtifactUrls {
  source: string
  translation: string
  reviewed: string
  wechat: string
  html: string
}

export type ArtifactKey = keyof ArtifactUrls

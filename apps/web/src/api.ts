import type { ApiErrorDetail, ArtifactUrls, CreateJobResponse, JobRecord, RetryJobRequest, RetryJobResponse } from './types'

export class ApiError extends Error {
  status: number
  detail: ApiErrorDetail | null

  constructor(message: string, status: number, detail: ApiErrorDetail | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const REQUEST_TIMEOUT_MS = 10_000

async function fetchWithTimeout(input: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort()
  }, REQUEST_TIMEOUT_MS)

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('请求超时，请确认后端服务已启动')
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeoutId)
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败：${response.status}`
    let detail: ApiErrorDetail | null = null

    try {
      const payload = (await response.json()) as { detail?: string | ApiErrorDetail }
      if (typeof payload.detail === 'string') {
        message = payload.detail
      } else if (payload.detail && typeof payload.detail === 'object') {
        detail = payload.detail
        message = payload.detail.message ?? message
      }
    } catch {
      // ignore json parse error and use fallback message
    }

    throw new ApiError(message, response.status, detail)
  }

  return (await response.json()) as T
}

export function buildArtifactUrls(jobId: string): ArtifactUrls {
  return {
    source: `/api/jobs/${jobId}/artifacts/01-source.md`,
    translation: `/api/jobs/${jobId}/artifacts/02-translation.md`,
    reviewed: `/api/jobs/${jobId}/artifacts/03-reviewed.md`,
    polished: `/api/jobs/${jobId}/artifacts/05-polished.md`,
    rewritten: `/api/jobs/${jobId}/artifacts/06-rewritten.md`,
    final: `/api/jobs/${jobId}/artifacts/10-final.md`,
    html: `/api/jobs/${jobId}/artifacts/11-wechat.html`,
  }
}

export async function createJob(url: string): Promise<CreateJobResponse> {
  const response = await fetchWithTimeout('/api/jobs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ url }),
  })

  return parseJson<CreateJobResponse>(response)
}

export async function listJobs(): Promise<JobRecord[]> {
  const response = await fetchWithTimeout('/api/jobs')
  return parseJson<JobRecord[]>(response)
}

export async function runJob(jobId: string): Promise<void> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/run`, {
    method: 'POST',
  })

  await parseJson<{ job_id: string; status: string }>(response)
}

export async function retryJob(jobId: string, payload: RetryJobRequest): Promise<RetryJobResponse> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/retry`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  return parseJson<RetryJobResponse>(response)
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}`)
  return parseJson<JobRecord>(response)
}

export async function deleteJob(jobId: string): Promise<void> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    await parseJson<{ detail?: string }>(response)
  }
}

export async function getArtifactText(url: string): Promise<string | null> {
  const response = await fetchWithTimeout(url)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`产物读取失败：${response.status}`)
  }

  return response.text()
}

export async function getPromptText(filename: string): Promise<string> {
  const response = await fetchWithTimeout(`/api/prompts/${filename}`)

  if (!response.ok) {
    throw new Error(`Prompt 读取失败：${response.status}`)
  }

  return response.text()
}

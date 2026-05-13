import type {
  ApiErrorDetail,
  ArtifactIndexResponse,
  ArtifactUrls,
  BatchCreateJobsRequest,
  BatchCreateJobsResponse,
  CreateJobResponse,
  DiscoveryArtifactIndexResponse,
  DiscoveryEnqueueRequest,
  DiscoveryEnqueueResponse,
  DiscoveryItemsResponse,
  DiscoveryPreviewAcceptedResponse,
  DiscoveryPreviewRequest,
  DiscoveryRunStatusResponse,
  JobRecord,
  RetryJobRequest,
  RetryJobResponse,
  StageHtmlPreviewRequest,
  StageHtmlPreviewResponse,
  UpdateFinalMarkdownResponse,
  StartWeChatPublishRequest,
  WeChatPublishAcceptedResponse,
  WeChatPublishRunStatusResponse,
  XLoginRunAcceptedResponse,
  XLoginRunStatusResponse,
} from './types'

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
const DISCOVERY_PREVIEW_TIMEOUT_MS = 90_000

interface FetchWithTimeoutOptions extends RequestInit {
  timeoutMs?: number
  timeoutMessage?: string
}

async function fetchWithTimeout(input: string, init?: FetchWithTimeoutOptions): Promise<Response> {
  const { timeoutMs = REQUEST_TIMEOUT_MS, timeoutMessage = '请求超时，请确认后端服务已启动', ...requestInit } = init ?? {}
  const controller = new AbortController()
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort()
  }, timeoutMs)

  try {
    return await fetch(input, {
      ...requestInit,
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(timeoutMessage)
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

export async function createJobsBatch(payload: BatchCreateJobsRequest): Promise<BatchCreateJobsResponse> {
  const response = await fetchWithTimeout('/api/jobs/batch', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    timeoutMs: 30_000,
    timeoutMessage: '批量提交超时：请确认后端服务已启动。',
  })

  return parseJson<BatchCreateJobsResponse>(response)
}

export async function listJobs(): Promise<JobRecord[]> {
  const response = await fetchWithTimeout('/api/jobs')
  return parseJson<JobRecord[]>(response)
}

export async function listTrashedJobs(): Promise<JobRecord[]> {
  const response = await fetchWithTimeout('/api/jobs/trash')
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

export async function restoreJob(jobId: string): Promise<JobRecord> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/restore`, {
    method: 'POST',
  })

  return parseJson<JobRecord>(response)
}

export async function stopJob(jobId: string): Promise<JobRecord> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/stop`, {
    method: 'POST',
  })

  return parseJson<JobRecord>(response)
}

export async function setJobPublished(jobId: string, published: boolean): Promise<JobRecord> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/published`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ published }),
  })

  return parseJson<JobRecord>(response)
}

export async function updateFinalMarkdown(jobId: string, content: string): Promise<UpdateFinalMarkdownResponse> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/final-markdown`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
  })

  return parseJson<UpdateFinalMarkdownResponse>(response)
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

export async function getArtifactIndex(jobId: string): Promise<ArtifactIndexResponse> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/artifacts-index`)
  return parseJson<ArtifactIndexResponse>(response)
}

export async function generateStageHtmlPreview(jobId: string, payload: StageHtmlPreviewRequest): Promise<StageHtmlPreviewResponse> {
  const response = await fetchWithTimeout(`/api/jobs/${jobId}/html-preview`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    timeoutMs: 90_000,
    timeoutMessage: '生成 HTML 预览超时：可能是 renderer 未构建或 Node 执行较慢。',
  })

  return parseJson<StageHtmlPreviewResponse>(response)
}

export async function previewDiscovery(payload: DiscoveryPreviewRequest): Promise<DiscoveryPreviewAcceptedResponse> {
  const response = await fetchWithTimeout('/api/x/discovery/preview', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    timeoutMs: DISCOVERY_PREVIEW_TIMEOUT_MS,
    timeoutMessage: '预览候选超时：X 搜索通常较慢，请稍候重试，或减少账号/关键词与滚动次数。',
  })
  return parseJson<DiscoveryPreviewAcceptedResponse>(response)
}

export async function getDiscoveryRun(runId: string): Promise<DiscoveryRunStatusResponse> {
  const response = await fetchWithTimeout(`/api/x/discovery/runs/${runId}`)
  return parseJson<DiscoveryRunStatusResponse>(response)
}

export async function stopDiscoveryRun(runId: string): Promise<DiscoveryRunStatusResponse> {
  const response = await fetchWithTimeout(`/api/x/discovery/runs/${runId}/stop`, {
    method: 'POST',
  })
  return parseJson<DiscoveryRunStatusResponse>(response)
}

export async function getDiscoveryItems(runId: string): Promise<DiscoveryItemsResponse> {
  const response = await fetchWithTimeout(`/api/x/discovery/runs/${runId}/items`)
  return parseJson<DiscoveryItemsResponse>(response)
}

export async function getDiscoveryArtifactIndex(runId: string): Promise<DiscoveryArtifactIndexResponse> {
  const response = await fetchWithTimeout(`/api/x/discovery/runs/${runId}/artifacts`)
  return parseJson<DiscoveryArtifactIndexResponse>(response)
}

export async function getDiscoveryArtifactText(runId: string, file: string): Promise<string | null> {
  const response = await fetchWithTimeout(`/api/x/discovery/runs/${runId}/artifacts/${file}`)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`调试产物读取失败：${response.status}`)
  }

  return response.text()
}

export async function startDiscoveryLogin(): Promise<XLoginRunAcceptedResponse> {
  const response = await fetchWithTimeout('/api/x/discovery/login/start', {
    method: 'POST',
  })
  return parseJson<XLoginRunAcceptedResponse>(response)
}

export async function getDiscoveryLoginRun(runId: string): Promise<XLoginRunStatusResponse> {
  const response = await fetchWithTimeout(`/api/x/discovery/login/runs/${runId}`)
  return parseJson<XLoginRunStatusResponse>(response)
}

export async function enqueueDiscovery(payload: DiscoveryEnqueueRequest): Promise<DiscoveryEnqueueResponse> {
  const response = await fetchWithTimeout('/api/x/discovery/enqueue', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  return parseJson<DiscoveryEnqueueResponse>(response)
}

export async function startWeChatPublish(payload: StartWeChatPublishRequest): Promise<WeChatPublishAcceptedResponse> {
  const response = await fetchWithTimeout('/api/wechat/publish/start', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    timeoutMs: 10_000,
    timeoutMessage: '启动发布超时：请确认后端服务已启动。',
  })
  return parseJson<WeChatPublishAcceptedResponse>(response)
}

export async function getWeChatPublishRun(runId: string): Promise<WeChatPublishRunStatusResponse> {
  const response = await fetchWithTimeout(`/api/wechat/publish/runs/${runId}`)
  return parseJson<WeChatPublishRunStatusResponse>(response)
}

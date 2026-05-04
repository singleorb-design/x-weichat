import type { ArtifactUrls, CreateJobResponse, JobRecord } from './types'

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败：${response.status}`

    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        message = payload.detail
      }
    } catch {
      // ignore json parse error and use fallback message
    }

    throw new Error(message)
  }

  return (await response.json()) as T
}

export function buildArtifactUrls(jobId: string): ArtifactUrls {
  return {
    source: `/api/jobs/${jobId}/artifacts/01-source.md`,
    translation: `/api/jobs/${jobId}/artifacts/02-translation.md`,
    reviewed: `/api/jobs/${jobId}/artifacts/03-reviewed.md`,
    wechat: `/api/jobs/${jobId}/artifacts/04-wechat.md`,
    html: `/api/jobs/${jobId}/artifacts/05-wechat.html`,
  }
}

export async function createJob(url: string): Promise<CreateJobResponse> {
  const response = await fetch('/api/jobs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ url }),
  })

  return parseJson<CreateJobResponse>(response)
}

export async function runJob(jobId: string): Promise<void> {
  const response = await fetch(`/api/jobs/${jobId}/run`, {
    method: 'POST',
  })

  await parseJson<{ job_id: string; status: string }>(response)
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const response = await fetch(`/api/jobs/${jobId}`)
  return parseJson<JobRecord>(response)
}

export async function getArtifactText(url: string): Promise<string | null> {
  const response = await fetch(url)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`产物读取失败：${response.status}`)
  }

  return response.text()
}

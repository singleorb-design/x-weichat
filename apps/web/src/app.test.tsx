// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { buildArtifactUrls } from './api'

const setNativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void

  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })

  return { promise, resolve, reject }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

function textResponse(body: string | null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new Error('not json')
    },
    text: async () => body ?? '',
  } as unknown as Response
}

async function flushMicrotasks() {
  await Promise.resolve()
  await Promise.resolve()
}

function updateInputValue(input: HTMLInputElement, value: string) {
  setNativeValue?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

describe('buildArtifactUrls', () => {
  it('builds canonical artifact urls', () => {
    expect(buildArtifactUrls('job-1')).toEqual({
      source: '/api/jobs/job-1/artifacts/01-source.md',
      translation: '/api/jobs/job-1/artifacts/02-translation.md',
      reviewed: '/api/jobs/job-1/artifacts/03-reviewed.md',
      wechat: '/api/jobs/job-1/artifacts/04-wechat.md',
      html: '/api/jobs/job-1/artifacts/05-wechat.html',
    })
  })
})

describe('App', () => {
  let container: HTMLDivElement
  let root: Root
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(async () => {
    await act(async () => {
      root.unmount()
      await flushMicrotasks()
    })
    container.remove()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders the local job ui shell', async () => {
    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.innerHTML).toContain('x-to-wechat-agent')
    expect(container.innerHTML).toContain('name="url"')
    expect(container.textContent).toContain('开始生成')
    expect(container.textContent).toContain('任务状态')
    expect(container.textContent).toContain('HTML 预览')
  })

  it('submits jobs, polls to terminal status, and resets stale ui for a new submission', async () => {
    const secondCreate = deferred<Response>()
    const jobPollCount = new Map<string, number>()
    const artifactPollCount = new Map<string, number>()
    let createCount = 0

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'

      if (url === '/api/jobs' && method === 'POST') {
        createCount += 1

        if (createCount === 1) {
          return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'pending' }))
        }

        return secondCreate.promise
      }

      if (url === '/api/jobs/job-1/run' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'running' }))
      }

      if (url === '/api/jobs/job-2/run' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-2', status: 'running' }))
      }

      if (url === '/api/jobs/job-1') {
        const count = (jobPollCount.get('job-1') ?? 0) + 1
        jobPollCount.set('job-1', count)
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-1',
            url: 'https://x.com/first/status/1',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'done',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:02Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-2') {
        const count = (jobPollCount.get('job-2') ?? 0) + 1
        jobPollCount.set('job-2', count)

        return Promise.resolve(
          jsonResponse({
            job_id: 'job-2',
            url: 'https://x.com/second/status/2',
            created_at: '2026-05-03T00:01:00Z',
            status: count === 1 ? 'running' : 'succeeded',
            current_stage: count === 1 ? 'translate' : 'done',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: count === 1 ? null : '2026-05-03T00:01:06Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-1/artifacts/01-source.md') {
        artifactPollCount.set('job-1', (artifactPollCount.get('job-1') ?? 0) + 1)
        return Promise.resolve(textResponse('old source artifact'))
      }

      if (url === '/api/jobs/job-2/artifacts/01-source.md') {
        const count = (artifactPollCount.get('job-2') ?? 0) + 1
        artifactPollCount.set('job-2', count)
        return Promise.resolve(count === 1 ? textResponse(null, 404) : textResponse('fresh source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const input = container.querySelector('#url') as HTMLInputElement | null
    const form = container.querySelector('form') as HTMLFormElement | null

    expect(input).not.toBeNull()
    expect(form).not.toBeNull()

    await act(async () => {
      updateInputValue(input!, 'https://x.com/first/status/1')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/jobs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ url: 'https://x.com/first/status/1' }),
      }),
    )
    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-1/run', expect.objectContaining({ method: 'POST' }))
    expect(container.textContent).toContain('job-1')
    expect(container.textContent).toContain('succeeded')
    expect(container.textContent).toContain('old source artifact')

    act(() => {
      updateInputValue(input!, 'https://x.com/second/status/2')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })

    expect(container.textContent).not.toContain('job-1')
    expect(container.textContent).not.toContain('old source artifact')
    expect(container.textContent).toContain('提交 URL 后将在这里显示任务进度。')
    expect(container.textContent).toContain('任务运行后可在此查看各阶段产物。')

    await act(async () => {
      secondCreate.resolve(jsonResponse({ job_id: 'job-2', status: 'pending' }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-2/run', expect.objectContaining({ method: 'POST' }))
    expect(container.textContent).toContain('job-2')
    expect(container.textContent).toContain('running')
    expect(container.textContent).toContain('该产物尚未生成。')

    await act(async () => {
      vi.advanceTimersByTime(2000)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('succeeded')
    expect(container.textContent).toContain('fresh source artifact')
    expect(jobPollCount.get('job-2')).toBe(2)
    expect(artifactPollCount.get('job-2')).toBe(2)
  })
})

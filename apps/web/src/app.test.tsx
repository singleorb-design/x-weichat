// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { buildArtifactUrls } from './api'

const setNativeInputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
const setNativeSelectValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set
const setNativeTextareaValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
const promptResponses: Record<string, string> = {
  '/api/prompts/translate_zh.txt': '你是一名专业技术翻译。',
  '/api/prompts/review_zh.txt': '你是一名资深中文编辑。',
  '/api/prompts/review_custom.txt': '你是一名会保留术语一致性的实验版审校助手。',
  '/api/prompts/route_zh.txt': '你是一名路由判断助手。',
  '/api/prompts/light_polish_zh.txt': '你是一名轻编辑助手。',
  '/api/prompts/final_check_zh.txt': '你是一名终检助手。',
  '/api/prompts/targeted_fix_zh.txt': '你是一名定点修复助手。',
}

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
  setNativeInputValue?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

function updateTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  setNativeTextareaValue?.call(textarea, value)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  textarea.dispatchEvent(new Event('change', { bubbles: true }))
}

function updateSelectValue(select: HTMLSelectElement, value: string) {
  setNativeSelectValue?.call(select, value)
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

async function toggleArtifactPreview(container: HTMLDivElement) {
  const toggle = container.querySelector('button[data-artifact-preview-toggle="true"]') as HTMLButtonElement | null
  expect(toggle).not.toBeNull()
  await act(async () => {
    toggle!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
}

async function toggleHtmlPreview(container: HTMLDivElement) {
  const toggle = container.querySelector('button[data-html-preview-toggle="true"]') as HTMLButtonElement | null
  expect(toggle).not.toBeNull()
  await act(async () => {
    toggle!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
}

async function selectJobListSegment(container: HTMLDivElement, labelPrefix: string) {
  const tabs = Array.from(container.querySelectorAll('button.tab')) as HTMLButtonElement[]
  const tab = tabs.find((button) => (button.textContent ?? '').startsWith(labelPrefix))
  expect(tab).not.toBeUndefined()
  await act(async () => {
    tab!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
}

async function submitJobForm(container: HTMLDivElement, value: string) {
  const input = container.querySelector('input[name="url"]') as HTMLInputElement | null
  const submitButton = container.querySelector('button[type="submit"]') as HTMLButtonElement | null
  expect(input).not.toBeNull()
  expect(submitButton).not.toBeNull()

  await act(async () => {
    updateInputValue(input!, value)
    await flushMicrotasks()
  })

  await act(async () => {
    submitButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
}

async function submitBatchJobForm(container: HTMLDivElement, value: string) {
  const textarea = container.querySelector('textarea[name="urls_text"]') as HTMLTextAreaElement | null
  const buttons = Array.from(container.querySelectorAll('button')) as HTMLButtonElement[]
  const submitButton = buttons.find((button) => (button.textContent ?? '').includes('批量开始生成')) ?? null
  expect(textarea).not.toBeNull()
  expect(submitButton).not.toBeNull()

  await act(async () => {
    updateTextareaValue(textarea!, value)
    await flushMicrotasks()
  })

  await act(async () => {
    submitButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushMicrotasks()
  })
}

function maybePromptResponse(url: string): Response | null {
  if (url === '/api/jobs/trash') {
    return jsonResponse([])
  }
  if (url in promptResponses) {
    return textResponse(promptResponses[url])
  }

  return null
}

describe('buildArtifactUrls', () => {
  it('builds canonical artifact urls', () => {
    expect(buildArtifactUrls('job-1')).toEqual({
      source: '/api/jobs/job-1/artifacts/01-source.md',
      translation: '/api/jobs/job-1/artifacts/02-translation.md',
      reviewed: '/api/jobs/job-1/artifacts/03-reviewed.md',
      polished: '/api/jobs/job-1/artifacts/05-polished.md',
      final: '/api/jobs/job-1/artifacts/10-final.md',
      html: '/api/jobs/job-1/artifacts/11-wechat.html',
    })
  })
})

describe('App', () => {
  let container: HTMLDivElement
  let root: Root
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-03T00:00:10Z'))
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
    fetchMock.mockImplementation((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs') {
        return Promise.resolve(jsonResponse([]))
      }

      throw new Error(`unexpected request: GET ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.innerHTML).toContain('x-to-wechat-agent')
    expect(container.innerHTML).toContain('name="url"')
    expect(container.textContent).toContain('开始生成')
    expect(container.textContent).toContain('任务列表')
    expect(container.textContent).toContain('任务状态')
    expect(container.textContent).toContain('HTML 预览')
    expect(container.textContent).not.toContain('发布到公众号草稿')
  })

  it('opens artifact preview by default after selecting a job while keeping html preview collapsed', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-preview-collapse',
              url: 'https://x.com/alice/status/1a',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
              stage_probes: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-preview-collapse' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-preview-collapse',
            url: 'https://x.com/alice/status/1a',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
            stage_probes: {},
          }),
        )
      }

      if (url === '/api/jobs/job-preview-collapse/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      if (url === '/api/jobs/job-preview-collapse/html-preview' && method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-preview-collapse',
            stage: 'final-output',
            source_artifact: '10-final.md',
            artifact_path: 'preview.assets/final-output.html',
            status: 'generated',
          }),
        )
      }

      if (url === '/api/jobs/job-preview-collapse/artifacts/preview.assets/final-output.html' && method === 'GET') {
        return Promise.resolve(textResponse('<html>preview</html>'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-preview-collapse'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).not.toContain('默认折叠，展开后可查看各阶段产物。')
    expect(container.textContent).toContain('选择阶段后点击“生成预览”，HTML 会显示在这里。')
    expect(container.textContent).toContain('source artifact')
    expect(container.querySelector('iframe[title="HTML 预览"]')).toBeNull()

    await toggleArtifactPreview(container)
    expect(container.textContent).not.toContain('source artifact')

    await toggleHtmlPreview(container)
    expect(container.querySelector('iframe[title="HTML 预览"]')).toBeNull()

    await act(async () => {
      const button = container.querySelector('button.preview-generate') as HTMLButtonElement | null
      expect(button).not.toBeNull()
      button!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })
    expect(container.querySelector('iframe[title="HTML 预览"]')).not.toBeNull()
  })

  it('submits batch urls and schedules multiple jobs', async () => {
    const batchCalls: Array<{ url: string; method: string; body: string | null }> = []
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/jobs/batch' && method === 'POST') {
        batchCalls.push({ url, method, body: (init?.body as string | null) ?? null })
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                line: 1,
                input: 'https://x.com/alice/status/1?s=12',
                url: 'https://x.com/alice/status/1?s=12',
                ok: true,
                job_id: 'job-batch-1',
                status: 'accepted',
                error: null,
              },
              {
                line: 2,
                input: 'https://x.com/bob/status/2?s=12',
                url: 'https://x.com/bob/status/2?s=12',
                ok: true,
                job_id: 'job-batch-2',
                status: 'accepted',
                error: null,
              },
            ],
            stats: { created: 2, scheduled: 2, invalid: 0 },
          })
        )
      }

      // After batch submit, App may poll job status.
      if (url.startsWith('/api/jobs/job-batch-') && method === 'GET') {
        const jobId = url.split('/api/jobs/')[1]
        return Promise.resolve(
          jsonResponse({
            job_id: jobId,
            url: jobId === 'job-batch-1' ? 'https://x.com/alice/status/1?s=12' : 'https://x.com/bob/status/2?s=12',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'x-fetch',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
            stage_probes: {},
          })
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await submitBatchJobForm(
      container,
      'https://x.com/alice/status/1?s=12\nhttps://x.com/bob/status/2?s=12',
    )

    expect(batchCalls.length).toBe(1)
    expect(batchCalls[0].url).toBe('/api/jobs/batch')
    expect(batchCalls[0].method).toBe('POST')
    expect(batchCalls[0].body ?? '').toContain('urls_text')
    expect(container.textContent).toContain('已创建并开始运行 2 个任务')
  })

  it('recovers from a stuck submit request instead of staying busy forever', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/jobs' && method === 'POST') {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'))
          })
        })
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await submitJobForm(container, 'https://x.com/alice/status/1')
    expect(container.textContent).toContain('提交中…')

    await act(async () => {
      vi.advanceTimersByTime(10_000)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('开始生成')
    expect(container.textContent).toContain('请求超时，请确认后端服务已启动')
  })

  it('renders recent jobs list for visibility', async () => {
    fetchMock.mockImplementation((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-running',
              url: 'https://x.com/hooeem/article/2050332284675362853',
              created_at: '2026-05-03T00:00:00Z',
              status: 'running',
              current_stage: 'x-fetch',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: null,
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-done',
              url: 'https://x.com/alice/status/1',
              created_at: '2026-05-02T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-02T00:00:01Z',
              finished_at: '2026-05-02T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      throw new Error(`unexpected request: GET ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('任务列表')
    expect(container.textContent).toContain('job-running')
    expect(container.textContent).toContain('当前阶段：原文抓取')
    expect(container.textContent).toContain('正在抓取原文，完成后会自动进入翻译。')

    await selectJobListSegment(container, '全部')
    expect(container.textContent).toContain('job-done')
    expect(container.textContent).toContain('succeeded')
  })

  it('shows published jobs in a dedicated tab separate from succeeded jobs', async () => {
    fetchMock.mockImplementation((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-published',
              url: 'https://x.com/alice/status/100',
              created_at: '2026-05-03T00:00:00Z',
              status: 'published',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-succeeded',
              url: 'https://x.com/bob/status/200',
              created_at: '2026-05-02T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-02T00:00:01Z',
              finished_at: '2026-05-02T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      throw new Error(`unexpected request: GET ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('已发布（1）')

    await selectJobListSegment(container, '成功')
    let jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    expect(jobItems.some((item) => item.textContent?.includes('job-succeeded'))).toBe(true)
    expect(jobItems.some((item) => item.textContent?.includes('job-published'))).toBe(false)

    await selectJobListSegment(container, '已发布')
    jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    expect(jobItems.some((item) => item.textContent?.includes('job-published'))).toBe(true)
    expect(jobItems.some((item) => item.textContent?.includes('job-succeeded'))).toBe(false)
  })

  it('filters the job list by multiple search terms and can clear the query', async () => {
    fetchMock.mockImplementation((input: string | URL | Request) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-alice',
              url: 'https://x.com/alice/status/1',
              source_title: 'Alice Agent Notes',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-bob',
              url: 'https://x.com/bob/status/2',
              source_title: 'Bob Pipeline Notes',
              created_at: '2026-05-02T00:00:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-02T00:00:01Z',
              finished_at: '2026-05-02T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      throw new Error(`unexpected request: GET ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const searchInput = container.querySelector('input[name="job_list_search"]') as HTMLInputElement | null
    expect(searchInput).not.toBeNull()
    const searchRow = container.querySelector('.job-list-search-row')
    const sortSelect = container.querySelector('.job-list-search-row select') as HTMLSelectElement | null
    expect(searchRow).not.toBeNull()
    expect(sortSelect).not.toBeNull()
    expect(searchInput!.classList.contains('job-list-control-field')).toBe(true)
    expect(sortSelect!.classList.contains('job-list-control-field')).toBe(true)

    await act(async () => {
      updateInputValue(searchInput!, 'alice succeeded')
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('显示 1 / 2 个任务')
    expect(container.textContent).toContain('job-alice')
    expect(container.textContent).not.toContain('job-bob')

    const clearButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '清空搜索')
    expect(clearButton).toBeDefined()
    await act(async () => {
      clearButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(searchInput!.value).toBe('')
    expect(container.textContent).toContain('显示 2 / 2 个任务')
    expect(container.textContent).toContain('job-alice')
    expect(container.textContent).toContain('job-bob')
  })

  it('polls discovery progress, renders candidates, and auto-runs selected jobs after enqueue', async () => {
    let listJobsCallCount = 0
    let discoveryStatusCallCount = 0
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        listJobsCallCount += 1
        return Promise.resolve(
          jsonResponse(
            listJobsCallCount === 1
              ? []
              : [
                  {
                    job_id: 'job-discovery-1',
                    url: 'https://x.com/i/article/987654321',
                    created_at: '2026-05-03T00:00:00Z',
                    status: 'running',
                    current_stage: 'x-fetch',
                    started_at: '2026-05-03T00:00:01Z',
                    finished_at: null,
                    stage_models: {},
                    prompt_versions: {},
                    stage_durations: {},
                    stage_errors: {},
                    stage_probes: {},
                  },
                ],
          ),
        )
      }

      if (url === '/api/x/discovery/preview' && method === 'POST') {
        return Promise.resolve(
          jsonResponse(
            {
            run_id: 'run-discovery-1',
              status: 'pending',
            },
            202,
          ),
        )
      }

      if (url === '/api/x/discovery/runs/run-discovery-1' && method === 'GET') {
        discoveryStatusCallCount += 1
        return Promise.resolve(
          jsonResponse(
            discoveryStatusCallCount === 1
              ? {
                  run_id: 'run-discovery-1',
                  status: 'running',
                  current_phase: 'searching',
                  progress_message: '正在搜索第 1 / 1 个来源（滚动 2 / 4）',
                  progress_json: {
                    source_total: 1,
                    source_index: 1,
                    current_source_kind: 'keyword',
                    current_source_value: 'ai',
                    current_query: 'ai',
                    current_scroll: 2,
                    max_scrolls: 4,
                    raw_hits: 3,
                    after_likes_filter: 2,
                    after_keywords_filter: 1,
                    deduped_hits: 1,
                    suspected_reason: null,
                  },
                  stats: {},
                  error_message: null,
                  completed: false,
                }
              : {
                  run_id: 'run-discovery-1',
                  status: 'succeeded',
                  current_phase: 'completed',
                  progress_message: '本次发现 1 条候选',
                  progress_json: {
                    source_total: 1,
                    source_index: 1,
                    current_source_kind: 'keyword',
                    current_source_value: 'ai',
                    current_query: 'ai',
                    current_scroll: 4,
                    max_scrolls: 4,
                    raw_hits: 3,
                    after_likes_filter: 2,
                    after_keywords_filter: 1,
                    deduped_hits: 1,
                    suspected_reason: null,
                  },
                  stats: { found: 1, returned: 1, already_seen: 0, already_enqueued: 0 },
                  error_message: null,
                  completed: true,
                },
          ),
        )
      }

      if (url === '/api/x/discovery/runs/run-discovery-1/items' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-discovery-1',
            items: [
              {
                canonical_url: 'https://x.com/i/article/987654321',
                original_url: 'https://x.com/i/article/987654321',
                likes: 1234,
                source_kind: 'keyword',
                source_value: 'ai',
                reason: '高赞 AI 文章',
                score: 1234,
                already_seen: false,
                already_enqueued: false,
                job_id: null,
              },
            ],
          }),
        )
      }

      if (url === '/api/x/discovery/enqueue' && method === 'POST') {
        const payload = JSON.parse(String(init?.body ?? '{}'))
        expect(payload.auto_run).toBe(true)
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-discovery-1',
            enqueued: [
              {
                canonical_url: 'https://x.com/i/article/987654321',
                job_id: 'job-discovery-1',
                status: 'pending',
                action: 'created',
              },
            ],
            skipped: [],
            auto_run: { requested: true, started: 1, skipped_due_to_limit: 0 },
          }),
        )
      }

      if (url === '/api/jobs/job-discovery-1' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-discovery-1',
            url: 'https://x.com/i/article/987654321',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'x-fetch',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
            stage_probes: {},
          }),
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.textContent).not.toContain('正在抓取原文，完成后会自动进入翻译。')

    const previewButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('预览候选'))
    const enqueueButton = () => Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('入队所选'))

    expect(previewButton).not.toBeUndefined()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('状态：搜索候选')
    expect(container.textContent).toContain('搜索中：来源 1 / 1 · 滚动 2 / 4')

    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('https://x.com/i/article/987654321')
    expect(container.textContent).toContain('本次发现：新文章=1 / 5')

    await act(async () => {
      enqueueButton()!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('正在抓取原文，完成后会自动进入翻译。')
  })

  it('shows suspected reason and loads discovery debug artifacts for empty runs', async () => {
    let discoveryStatusCallCount = 0
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/x/discovery/preview' && method === 'POST') {
        return Promise.resolve(jsonResponse({ run_id: 'run-empty-discovery', status: 'pending' }, 202))
      }

      if (url === '/api/x/discovery/runs/run-empty-discovery' && method === 'GET') {
        discoveryStatusCallCount += 1
        return Promise.resolve(
          jsonResponse(
            discoveryStatusCallCount === 1
              ? {
                  run_id: 'run-empty-discovery',
                  status: 'running',
                  current_phase: 'searching',
                  progress_message: '正在搜索第 1 / 1 个来源',
                  progress_json: {
                    source_total: 1,
                    source_index: 1,
                    current_source_kind: 'account',
                    current_source_value: 'regent0x_',
                    current_query: 'from:regent0x_',
                    current_scroll: 0,
                    max_scrolls: 4,
                    raw_hits: 0,
                    after_likes_filter: 0,
                    after_keywords_filter: 0,
                    deduped_hits: 0,
                    suspected_reason: 'login_required',
                  },
                  stats: {},
                  error_message: null,
                  completed: false,
                }
              : {
                  run_id: 'run-empty-discovery',
                  status: 'failed',
                  current_phase: 'searching',
                  progress_message: '搜索失败',
                  progress_json: {
                    source_total: 1,
                    source_index: 1,
                    current_source_kind: 'account',
                    current_source_value: 'regent0x_',
                    current_query: 'from:regent0x_',
                    current_scroll: 0,
                    max_scrolls: 4,
                    raw_hits: 0,
                    after_likes_filter: 0,
                    after_keywords_filter: 0,
                    deduped_hits: 0,
                    suspected_reason: 'login_required',
                  },
                  stats: { found: 0, returned: 0, already_seen: 0, already_enqueued: 0 },
                  error_message: 'X 搜索页疑似要求重新登录',
                  completed: true,
                },
          ),
        )
      }

      if (url === '/api/x/discovery/runs/run-empty-discovery/items' && method === 'GET') {
        return Promise.resolve(jsonResponse({ run_id: 'run-empty-discovery', items: [] }))
      }

      if (url === '/api/x/discovery/runs/run-empty-discovery/artifacts' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-empty-discovery',
            files: ['debug.log', 'request.json', 'response-summary.json'],
          }),
        )
      }

      if (url === '/api/x/discovery/runs/run-empty-discovery/artifacts/debug.log' && method === 'GET') {
        return Promise.resolve(textResponse('[searching] suspected_reason=login_required\n'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const previewButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('预览候选'))
    expect(previewButton).not.toBeUndefined()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('疑似原因')
    expect(container.textContent).toContain('login_required')

    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('X 搜索页疑似要求重新登录')
    expect(container.textContent).toContain('本次发现：新文章=0 / 5')

    const debugToggle = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('查看调试详情'))
    expect(debugToggle).not.toBeUndefined()
    await act(async () => {
      debugToggle!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const debugLogTab = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('debug.log'))
    expect(debugLogTab).not.toBeUndefined()

    await act(async () => {
      debugLogTab!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('suspected_reason=login_required')
  })

  it('lets users type custom discovery keywords, add preset keywords, and includes the feed source by default', async () => {
    const discoveryBodies: Array<Record<string, unknown>> = []
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/x/discovery/preview' && method === 'POST') {
        discoveryBodies.push(JSON.parse(String(init?.body ?? '{}')))
        return Promise.resolve(jsonResponse({ run_id: 'run-presets', status: 'pending' }, 202))
      }

      if (url === '/api/x/discovery/runs/run-presets' && method === 'GET') {
        return Promise.resolve(jsonResponse({
          run_id: 'run-presets',
          status: 'canceled',
          current_phase: 'searching',
          progress_message: '预览已停止，可调整关键词后重新预览',
          progress_json: {
            source_total: 3,
            source_index: 3,
            current_source_kind: 'recommendation',
            current_source_value: 'for_you',
            current_query: 'home:for_you',
            current_scroll: 0,
            max_scrolls: 4,
            raw_hits: 0,
            after_likes_filter: 0,
            after_keywords_filter: 0,
            deduped_hits: 0,
            suspected_reason: null,
            stopped_by_user: true,
          },
          stats: { found: 0, returned: 0, already_seen: 0, already_enqueued: 0 },
          error_message: null,
          completed: true,
        }))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const includeFeed = container.querySelector('input[name="discovery-include-recommendations"]') as HTMLInputElement | null
    expect(includeFeed).not.toBeNull()
    expect(includeFeed?.checked).toBe(true)

    const keywordLabel = Array.from(container.querySelectorAll('label')).find((label) => label.textContent?.includes('关键词（逗号分隔'))
    const keywordInput = keywordLabel?.querySelector('input') as HTMLInputElement | null
    expect(keywordInput).not.toBeNull()

    await act(async () => {
      updateInputValue(keywordInput!, 'custom trend')
      await flushMicrotasks()
    })

    const claudePresetButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'claude')
    expect(claudePresetButton).not.toBeUndefined()

    await act(async () => {
      claudePresetButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const previewButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('预览候选'))
    expect(previewButton).not.toBeUndefined()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(discoveryBodies).toHaveLength(1)
    expect(discoveryBodies[0]).toEqual({
      sources: [
        { kind: 'keyword', value: 'custom trend' },
        { kind: 'keyword', value: 'claude' },
        { kind: 'recommendation', value: 'for_you' },
      ],
      max_candidates: 5,
      max_scrolls: 4,
      search_mode: 'top',
      min_likes: 100,
      required_keywords: ['AI', 'agent', 'LLM', 'RAG', 'Prompt'],
    })
  })

  it('lets the user confirm login and retry discovery preview from the discovery card', async () => {
    let discoveryStatusCallCount = 0
    let loginStatusCallCount = 0
    let previewCallCount = 0
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/x/discovery/preview' && method === 'POST') {
        previewCallCount += 1
        return Promise.resolve(jsonResponse({ run_id: previewCallCount === 1 ? 'run-login-needed' : 'run-after-login', status: 'pending' }, 202))
      }

      if (url === '/api/x/discovery/runs/run-login-needed' && method === 'GET') {
        discoveryStatusCallCount += 1
        return Promise.resolve(
          jsonResponse(
            discoveryStatusCallCount === 1
              ? {
                  run_id: 'run-login-needed',
                  status: 'running',
                  current_phase: 'searching',
                  progress_message: '正在搜索第 1 / 1 个来源',
                  progress_json: {
                    source_total: 1,
                    source_index: 1,
                    current_source_kind: 'account',
                    current_source_value: 'regent0x_',
                    current_query: 'from:regent0x_',
                    current_scroll: 0,
                    max_scrolls: 4,
                    raw_hits: 0,
                    after_likes_filter: 0,
                    after_keywords_filter: 0,
                    deduped_hits: 0,
                    suspected_reason: 'login_required',
                  },
                  stats: {},
                  error_message: null,
                  completed: false,
                }
              : {
                  run_id: 'run-login-needed',
                  status: 'failed',
                  current_phase: 'searching',
                  progress_message: '搜索失败',
                  progress_json: {
                    suspected_reason: 'login_required',
                  },
                  stats: { found: 0, returned: 0, already_seen: 0, already_enqueued: 0 },
                  error_message: 'X 搜索页疑似要求重新登录',
                  completed: true,
                },
          ),
        )
      }

      if (url === '/api/x/discovery/runs/run-after-login' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-after-login',
            status: 'succeeded',
            current_phase: 'completed',
            progress_message: '本次发现 1 条候选',
            progress_json: {
              source_total: 1,
              source_index: 1,
              current_source_kind: 'account',
              current_source_value: 'regent0x_',
              current_query: 'from:regent0x_',
              current_scroll: 1,
              max_scrolls: 4,
              raw_hits: 1,
              after_likes_filter: 1,
              after_keywords_filter: 1,
              deduped_hits: 1,
              suspected_reason: null,
            },
            stats: { found: 1, returned: 1, already_seen: 0, already_enqueued: 0 },
            error_message: null,
            completed: true,
          }),
        )
      }

      if (url === '/api/x/discovery/runs/run-login-needed/items' && method === 'GET') {
        return Promise.resolve(jsonResponse({ run_id: 'run-login-needed', items: [] }))
      }

      if (url === '/api/x/discovery/runs/run-after-login/items' && method === 'GET') {
        return Promise.resolve(jsonResponse({
          run_id: 'run-after-login',
          items: [{
            canonical_url: 'https://x.com/i/article/123',
            original_url: 'https://x.com/i/article/123',
            likes: 999,
            source_kind: 'account',
            source_value: 'regent0x_',
            reason: 'search_like_threshold',
            score: 999,
            already_seen: false,
            already_enqueued: false,
            job_id: null,
          }],
        }))
      }

      if (url === '/api/x/discovery/login/start' && method === 'POST') {
        return Promise.resolve(jsonResponse({ run_id: 'login-run-1', status: 'pending' }, 202))
      }

      if (url === '/api/x/discovery/login/runs/login-run-1' && method === 'GET') {
        loginStatusCallCount += 1
        return Promise.resolve(
          jsonResponse(
            loginStatusCallCount === 1
              ? {
                  run_id: 'login-run-1',
                  status: 'running',
                  current_phase: 'awaiting_login',
                  progress_message: '已打开 X 登录页，请在浏览器中完成登录',
                  progress_json: {
                    login_url: 'https://x.com/i/flow/login',
                    storage_state_path: '/tmp/x-state.json',
                  },
                  error_message: null,
                  completed: false,
                }
              : {
                  run_id: 'login-run-1',
                  status: 'succeeded',
                  current_phase: 'completed',
                  progress_message: '登录态已保存，可重新预览候选',
                  progress_json: {
                    login_url: 'https://x.com/i/flow/login',
                    storage_state_path: '/tmp/x-state.json',
                  },
                  error_message: null,
                  completed: true,
                },
          ),
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const previewButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('预览候选'))
    expect(previewButton).not.toBeUndefined()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await flushMicrotasks()
    })

    const loginButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('打开登录页'))
    expect(loginButton).not.toBeUndefined()

    await act(async () => {
      loginButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('已打开 X 登录页，请在浏览器中完成登录')

    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('登录态已保存，可重新预览候选')

    const refreshButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('我已登录，重新预览'))
    expect(refreshButton).not.toBeUndefined()

    await act(async () => {
      refreshButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await flushMicrotasks()
    })

    expect(previewCallCount).toBe(2)
    expect(container.textContent).toContain('本次发现 1 条候选')
    expect(container.textContent).not.toContain('X 搜索页疑似要求重新登录')
  })

  it('includes recommendation source and 100-like default when previewing discovery', async () => {
    let previewPayload: Record<string, unknown> | null = null
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/x/discovery/preview' && method === 'POST') {
        previewPayload = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
        return Promise.resolve(jsonResponse({ run_id: 'run-recommendation', status: 'pending' }, 202))
      }

      if (url === '/api/x/discovery/runs/run-recommendation' && method === 'GET') {
        return Promise.resolve(jsonResponse({
          run_id: 'run-recommendation',
          status: 'succeeded',
          current_phase: 'completed',
          progress_message: '本次发现 0 条候选',
          progress_json: {},
          stats: { found: 0, returned: 0, already_seen: 0, already_enqueued: 0 },
          error_message: null,
          completed: true,
        }))
      }

      if (url === '/api/x/discovery/runs/run-recommendation/items' && method === 'GET') {
        return Promise.resolve(jsonResponse({ run_id: 'run-recommendation', items: [] }))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('正文长度 ≥ 1000 字')

    const recommendationToggle = container.querySelector('input[name="discovery-include-recommendations"]') as HTMLInputElement | null
    expect(recommendationToggle).not.toBeNull()
    expect(recommendationToggle?.checked).toBe(true)

    const previewButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('预览候选'))
    expect(previewButton).not.toBeUndefined()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(previewPayload).toMatchObject({
      min_likes: 100,
      sources: [
        { kind: 'keyword', value: 'ai' },
        { kind: 'recommendation', value: 'for_you' },
      ],
    })
  })

  it('shows stage progress details for the selected job and allows deleting completed jobs', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-review',
              url: 'https://x.com/hooeem/article/2050332284675362853',
              created_at: '2026-05-03T00:00:00Z',
              status: 'running',
              current_stage: 'review',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: null,
              stage_models: {
                review: {
                  provider: 'qwen',
                  model: 'qwen-mt-plus',
                },
              },
              prompt_versions: {
                review: 'review_custom.txt',
              },
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-done',
              url: 'https://x.com/alice/status/1',
              created_at: '2026-05-02T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-02T00:00:01Z',
              finished_at: '2026-05-02T00:01:00Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-review' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-review',
            url: 'https://x.com/hooeem/article/2050332284675362853',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'review',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {
              review: {
                provider: 'qwen',
                model: 'qwen-mt-plus',
              },
            },
            prompt_versions: {
              review: 'review_custom.txt',
            },
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-review/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      if (url === '/api/jobs/job-done' && method === 'DELETE') {
        return Promise.resolve(textResponse('', 204))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const reviewItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-review'),
    )
    expect(reviewItem).not.toBeUndefined()

    await act(async () => {
      reviewItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('翻译已完成，正在审阅。')
    expect(container.textContent).toContain('原文抓取已完成')
    expect(container.textContent).toContain('翻译已完成')
    expect(container.textContent).toContain('审阅已运行 9.0秒')
    expect(container.textContent).toContain('进行中')
    expect(container.textContent).toContain('阶段 Prompt')
    expect(container.textContent).toContain('review_custom.txt · qwen-mt-plus')

    const reviewPromptToggle = container.querySelector('button[data-prompt-stage="review"]') as HTMLButtonElement | null
    expect(reviewPromptToggle).not.toBeNull()

    await act(async () => {
      reviewPromptToggle!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('你是一名会保留术语一致性的实验版审校助手。')

    await selectJobListSegment(container, '全部')

    const doneItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-done'),
    )
    const deleteButton = Array.from(doneItem?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent === '删除',
    )
    expect(deleteButton).not.toBeUndefined()

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-done', expect.objectContaining({ method: 'DELETE' }))
    expect(container.textContent).not.toContain('job-done')
  })

  it('marks the failed stage as failed instead of in progress', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-failed',
              url: 'https://x.com/alice/status/1',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'review exploded',
                  retryable: false,
                  suggestion: 'retry later',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-failed' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-failed',
            url: 'https://x.com/alice/status/1',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:10Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'review exploded',
                retryable: false,
                suggestion: 'retry later',
              },
            },
          }),
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const failedItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(failedItem).not.toBeNull()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('任务在审阅阶段失败，请检查审阅提示词或输入内容。')
    expect(container.textContent).toContain('审阅失败')
    expect(container.textContent).not.toContain('审阅进行中')
  })

  it('shows retry guidance for failed stages in the status panel', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-failed-retryable',
              url: 'https://x.com/alice/status/2',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                translate: {
                  error_type: 'APIConnectionError',
                  message: 'Server disconnected without sending a response',
                  retryable: true,
                  suggestion: '检查网络连通性后重试',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-failed-retryable' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-failed-retryable',
            url: 'https://x.com/alice/status/2',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:10Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              translate: {
                error_type: 'APIConnectionError',
                message: 'Server disconnected without sending a response',
                retryable: true,
                suggestion: '检查网络连通性后重试',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-failed-retryable/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const failedItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(failedItem).not.toBeNull()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('建议：检查网络连通性后重试')
    expect(container.textContent).toContain('可重试：是')
  })

  it('shows the failing stage model alongside review connection errors', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-review-failed',
              url: 'https://x.com/alice/status/3',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {
                review: {
                  provider: 'openai-compatible',
                  model: 'qwen-mt-plus',
                },
              },
              prompt_versions: {},
              stage_durations: {},
              stage_probes: {
                translate: {
                  status: 'passed',
                  message: 'OK',
                  checked_at: '2026-05-03T00:00:02Z',
                },
                review: {
                  status: 'failed',
                  message: 'Probe failed before generation.',
                  checked_at: '2026-05-03T00:00:03Z',
                },
              },
              stage_errors: {
                review: {
                  error_type: 'APIConnectionError',
                  message: 'Connection error. (caused by RemoteProtocolError: Server disconnected without sending a response.)',
                  retryable: true,
                  suggestion: '审校阶段当前使用模型 qwen-mt-plus。请优先检查该模型的可用性、API Base、代理配置后重试。',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-review-failed' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-review-failed',
            url: 'https://x.com/alice/status/3',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:10Z',
            stage_models: {
              review: {
                provider: 'openai-compatible',
                model: 'qwen-mt-plus',
              },
            },
            prompt_versions: {},
            stage_durations: {},
            stage_probes: {
              translate: {
                status: 'passed',
                message: 'OK',
                checked_at: '2026-05-03T00:00:02Z',
              },
              review: {
                status: 'failed',
                message: 'Probe failed before generation.',
                checked_at: '2026-05-03T00:00:03Z',
              },
            },
            stage_errors: {
              review: {
                error_type: 'APIConnectionError',
                message: 'Connection error. (caused by RemoteProtocolError: Server disconnected without sending a response.)',
                retryable: true,
                suggestion: '审校阶段当前使用模型 qwen-mt-plus。请优先检查该模型的可用性、API Base、代理配置后重试。',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-review-failed/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const failedItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(failedItem).not.toBeNull()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('任务在审阅阶段失败，请检查审阅提示词或输入内容。')
    expect(container.textContent).toContain('建议：审校阶段当前使用模型 qwen-mt-plus。请优先检查该模型的可用性、API Base、代理配置后重试。')
    expect(container.textContent).toContain('当前模型：qwen-mt-plus')
    expect(container.textContent).toContain('运行前模型探测结果')
    expect(container.textContent).toContain('审阅探测失败')
    expect(container.textContent).toContain('探测信息：Probe failed before generation.')
  })

  it('hides preflight probe results when all probes passed', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-probe-passed',
              url: 'https://x.com/alice/status/3c',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:20Z',
              stage_models: {
                translate: { provider: 'qwen', model: 'qwen-mt-plus' },
                review: { provider: 'qwen', model: 'qwen-mt-plus' },
              },
              prompt_versions: {},
              stage_durations: {},
              stage_probes: {
                translate: {
                  status: 'passed',
                  message: 'OK',
                  checked_at: '2026-05-03T00:00:02Z',
                },
                review: {
                  status: 'passed',
                  message: 'OK',
                  checked_at: '2026-05-03T00:00:03Z',
                },
              },
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-probe-passed' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-probe-passed',
            url: 'https://x.com/alice/status/3c',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:20Z',
            stage_models: {
              translate: { provider: 'qwen', model: 'qwen-mt-plus' },
              review: { provider: 'qwen', model: 'qwen-mt-plus' },
            },
            prompt_versions: {},
            stage_durations: {},
            stage_probes: {
              translate: {
                status: 'passed',
                message: 'OK',
                checked_at: '2026-05-03T00:00:02Z',
              },
              review: {
                status: 'passed',
                message: 'OK',
                checked_at: '2026-05-03T00:00:03Z',
              },
            },
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-probe-passed/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-probe-passed'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).not.toContain('运行前模型探测结果')
    expect(container.textContent).not.toContain('探测通过')
  })

  it('marks very long active stages as likely stuck instead of only showing a raw timer', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-stale-running',
              url: 'https://x.com/alice/status/3b',
              created_at: '2026-05-03T00:00:00Z',
              status: 'running',
              current_stage: 'render-html',
              started_at: '2026-05-02T23:00:00Z',
              finished_at: null,
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                'x-fetch': 10,
                translate: 20,
                review: 30,
                'render-html': 10,
              },
              stage_errors: {},
              stage_probes: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-stale-running' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-stale-running',
            url: 'https://x.com/alice/status/3b',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'render-html',
            started_at: '2026-05-02T23:00:00Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              'x-fetch': 10,
              translate: 20,
              review: 30,
              'render-html': 10,
            },
            stage_errors: {},
            stage_probes: {},
          }),
        )
      }

      if (url === '/api/jobs/job-stale-running/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-stale-running'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('HTML 渲染已运行较久（')
    expect(container.textContent).toContain('），可能卡住')
    expect(container.textContent).not.toContain('HTML 渲染已运行 57分25秒')
  })

  it('shows the default failed-stage retry action even without structured stage errors', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-failed-no-stage-errors',
              url: 'https://x.com/alice/status/2b',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-failed-no-stage-errors' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-failed-no-stage-errors',
            url: 'https://x.com/alice/status/2b',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:10Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-failed-no-stage-errors/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const failedItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(failedItem).not.toBeNull()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('任务在翻译阶段失败，请检查模型输出或配置。')
    expect(container.textContent).toContain('将从当前失败阶段重新开始，并继续执行后续阶段。')
    expect(container.textContent).toContain('重试此阶段')
  })

  it('retries the failed stage from the error card, clears stale detail, and keeps the current job selected', async () => {
    let jobDetailState: 'failed' | 'running' = 'failed'

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-failed',
              url: 'https://x.com/alice/status/3',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-failed' && method === 'GET') {
        return Promise.resolve(
          jsonResponse(
            jobDetailState === 'failed'
              ? {
                  job_id: 'job-failed',
                  url: 'https://x.com/alice/status/3',
                  created_at: '2026-05-03T00:00:00Z',
                  status: 'failed',
                  current_stage: 'review',
                  started_at: '2026-05-03T00:00:01Z',
                  finished_at: '2026-05-03T00:00:10Z',
                  stage_models: {},
                  prompt_versions: {},
                  stage_durations: {
                    review: 9,
                  },
                  stage_errors: {
                    review: {
                      error_type: 'RuntimeError',
                      message: 'boom',
                      retryable: true,
                      suggestion: 'retry',
                    },
                  },
                }
              : {
                  job_id: 'job-failed',
                  url: 'https://x.com/alice/status/3',
                  created_at: '2026-05-03T00:00:00Z',
                  status: 'running',
                  current_stage: 'review',
                  started_at: '2026-05-03T00:00:11Z',
                  finished_at: null,
                  stage_models: {},
                  prompt_versions: {},
                  stage_durations: {},
                  stage_errors: {},
                },
          ),
        )
      }

      if (url === '/api/jobs/job-failed/retry' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'review', mode: 'failed-stage' })
        jobDetailState = 'running'
        return Promise.resolve(
          jsonResponse({ job_id: 'job-failed', status: 'accepted', stage: 'review', mode: 'failed-stage' }, 202),
        )
      }

      if (url === '/api/jobs/job-failed/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse(jobDetailState === 'failed' ? 'stale source artifact' : null, jobDetailState === 'failed' ? 200 : 404))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const failedItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(failedItem).not.toBeNull()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('stale source artifact')
    expect(container.textContent).toContain('错误信息：boom')

    const retryButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-failed/retry', expect.objectContaining({ method: 'POST' }))
    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-failed')
    expect(container.textContent).not.toContain('stale source artifact')
    expect(container.textContent).not.toContain('错误信息：boom')
    expect(container.textContent).toContain('翻译已完成，正在审阅。')
    expect(container.textContent).toContain('进行中')
  })

  it('does not show the failed-stage retry button for non-failed jobs', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-running',
              url: 'https://x.com/alice/status/4',
              created_at: '2026-05-03T00:00:00Z',
              status: 'running',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: null,
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-running' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-running',
            url: 'https://x.com/alice/status/4',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-running/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const runningItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(runningItem).not.toBeNull()

    await act(async () => {
      runningItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).not.toContain('重试此阶段')
  })

  it('retries from a selected earlier stage for succeeded jobs and clears stale artifact content', async () => {
    let jobDetailState: 'succeeded' | 'running' = 'succeeded'

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-succeeded',
              url: 'https://x.com/alice/status/5',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:20Z',
              stage_models: {
                translate: { provider: 'openai', model: 'gpt-4.1' },
                review: { provider: 'openai', model: 'gpt-4.1' },
              },
              prompt_versions: {
                translate: 'translate_zh.txt',
                review: 'review_custom.txt',
              },
              stage_durations: {
                'x-fetch': 1,
                translate: 2,
                review: 3,
                'render-html': 5,
              },
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-succeeded' && method === 'GET') {
        return Promise.resolve(
          jsonResponse(
            jobDetailState === 'succeeded'
              ? {
                  job_id: 'job-succeeded',
                  url: 'https://x.com/alice/status/5',
                  created_at: '2026-05-03T00:00:00Z',
                  status: 'succeeded',
                  current_stage: 'render-html',
                  started_at: '2026-05-03T00:00:01Z',
                  finished_at: '2026-05-03T00:00:20Z',
                  stage_models: {
                    translate: { provider: 'openai', model: 'gpt-4.1' },
                    review: { provider: 'openai', model: 'gpt-4.1' },
                  },
                  prompt_versions: {
                    translate: 'translate_zh.txt',
                    review: 'review_custom.txt',
                  },
                  stage_durations: {
                    'x-fetch': 1,
                    translate: 2,
                    review: 3,
                    'render-html': 5,
                  },
                  stage_errors: {},
                }
              : {
                  job_id: 'job-succeeded',
                  url: 'https://x.com/alice/status/5',
                  created_at: '2026-05-03T00:00:00Z',
                  status: 'running',
                  current_stage: 'translate',
                  started_at: '2026-05-03T00:01:00Z',
                  finished_at: null,
                  stage_models: {},
                  prompt_versions: {},
                  stage_durations: {
                    'x-fetch': 1,
                  },
                  stage_errors: {},
                },
          ),
        )
      }

      if (url === '/api/jobs/job-succeeded/retry' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'translate', mode: 'from-stage' })
        jobDetailState = 'running'
        return Promise.resolve(
          jsonResponse({ job_id: 'job-succeeded', status: 'accepted', stage: 'translate', mode: 'from-stage' }, 202),
        )
      }

      if (url === '/api/jobs/job-succeeded/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse(jobDetailState === 'succeeded' ? 'stale source artifact' : null, jobDetailState === 'succeeded' ? 200 : 404))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const succeededItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-succeeded'),
    ) as HTMLElement | undefined
    expect(succeededItem).not.toBeUndefined()

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('stale source artifact')

    const stageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(stageSelect).not.toBeNull()

    await act(async () => {
      updateSelectValue(stageSelect!, 'translate')
      await flushMicrotasks()
    })

    const retryFromStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '从该阶段重跑',
    )
    expect(retryFromStageButton).not.toBeUndefined()

    await act(async () => {
      retryFromStageButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-succeeded/retry', expect.objectContaining({ method: 'POST' }))
    expect(container.textContent).not.toContain('stale source artifact')
    expect(container.textContent).toContain('原文已生成，正在翻译。')
    expect(container.textContent).toContain('进行中')
  })

  it('limits advanced retry stages for failed jobs and clamps a stale future-stage selection on job switch', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-succeeded',
              url: 'https://x.com/alice/status/5a',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-failed',
              url: 'https://x.com/alice/status/5b',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:10Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                translate: {
                  error_type: 'RuntimeError',
                  message: 'boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-succeeded' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-succeeded',
            url: 'https://x.com/alice/status/5a',
            created_at: '2026-05-03T00:01:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-failed' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-failed',
            url: 'https://x.com/alice/status/5b',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:10Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              translate: {
                error_type: 'RuntimeError',
                message: 'boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-succeeded/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('succeeded source'))
      }

      if (url === '/api/jobs/job-failed/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('failed source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-succeeded'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-failed'))
    expect(succeededItem).not.toBeUndefined()
    expect(failedItem).not.toBeUndefined()

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const stageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(stageSelect).not.toBeNull()

    await act(async () => {
      updateSelectValue(stageSelect!, 'render-html')
      await flushMicrotasks()
    })

    expect(stageSelect!.value).toBe('render-html')

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const failedStageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(failedStageSelect).not.toBeNull()
    expect(failedStageSelect!.value).toBe('translate')
    expect(Array.from(failedStageSelect!.options).map((option) => option.value)).toEqual(['x-fetch', 'translate'])
    expect(Array.from(failedStageSelect!.options).map((option) => option.textContent)).toEqual(['原文抓取', '翻译'])
  })

  it('does not restore a failed-stage retry snapshot after switching to another job before the request rejects', async () => {
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5c',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'job-a boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5d',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5c',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              review: 9,
            },
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'job-a boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-b' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-b',
            url: 'https://x.com/alice/status/5d',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:30Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      if (url === '/api/jobs/job-b/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-b source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-a'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-b'))
    expect(failedItem).not.toBeUndefined()
    expect(succeededItem).not.toBeUndefined()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).not.toContain('错误信息：job-a boom')
    const jobBRetryFromStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '从该阶段重跑',
    )
    expect(jobBRetryFromStageButton).not.toBeUndefined()
    expect(jobBRetryFromStageButton?.disabled).toBe(false)
    expect(container.textContent).not.toContain('重跑中…')

    await act(async () => {
      retryRequest.reject(new Error('阶段重试失败'))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).not.toContain('错误信息：job-a boom')
    expect(container.textContent).not.toContain('阶段重试失败')
  })

  it('lets the user edit final markdown and regenerate html', async () => {
    let savedFinalMarkdown = '# 最终稿\n\n第一版'
    let htmlVersion = '<html><body>old html</body></html>'

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-edit-final',
              url: 'https://x.com/alice/status/6',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:20Z',
              stage_models: {
                translate: { provider: 'openai', model: 'gpt-4.1' },
                review: { provider: 'openai', model: 'gpt-4.1' },
              },
              prompt_versions: {
                translate: 'translate_zh.txt',
                review: 'review_zh.txt',
              },
              stage_durations: { 'x-fetch': 1, translate: 2, review: 3, 'render-html': 5 },
              stage_errors: {},
              stage_probes: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-edit-final' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-edit-final',
            url: 'https://x.com/alice/status/6',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:20Z',
            stage_models: {
              translate: { provider: 'openai', model: 'gpt-4.1' },
              review: { provider: 'openai', model: 'gpt-4.1' },
            },
            prompt_versions: {
              translate: 'translate_zh.txt',
              review: 'review_zh.txt',
            },
            stage_durations: { 'x-fetch': 1, translate: 2, review: 3, 'render-html': 5 },
            stage_errors: {},
            stage_probes: {},
          }),
        )
      }

      if (url === '/api/jobs/job-edit-final/artifacts/10-final.md' && method === 'GET') {
        return Promise.resolve(textResponse(savedFinalMarkdown))
      }

      if (url === '/api/jobs/job-edit-final/final-markdown' && method === 'PUT') {
        const payload = JSON.parse(String(init?.body))
        savedFinalMarkdown = payload.content
        return Promise.resolve(jsonResponse({ job_id: 'job-edit-final', status: 'saved', relative_path: '10-final.md' }))
      }

      if (url === '/api/jobs/job-edit-final/retry' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'render-html', mode: 'from-stage' })
        htmlVersion = `<html><body>${savedFinalMarkdown}</body></html>`
        return Promise.resolve(
          jsonResponse({ job_id: 'job-edit-final', status: 'accepted', stage: 'render-html', mode: 'from-stage' }, 202),
        )
      }

      if (url === '/api/jobs/job-edit-final/artifacts/11-wechat.html' && method === 'GET') {
        return Promise.resolve(textResponse(htmlVersion))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(jobItem).not.toBeNull()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const finalTab = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('最终稿'))
    expect(finalTab).not.toBeUndefined()

    await act(async () => {
      finalTab!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const finalEditor = container.querySelector('textarea[data-final-markdown-editor="true"]') as HTMLTextAreaElement | null
    expect(finalEditor).not.toBeNull()
    expect(finalEditor?.getAttribute('rows')).toBe('20')
    expect(container.querySelector('.artifact-markdown')).toBeNull()

    await act(async () => {
      finalEditor!.value = '# 新最终稿\n\n第二版'
      finalEditor!.dispatchEvent(new Event('input', { bubbles: true }))
      await flushMicrotasks()
    })

    const regenerateButton = container.querySelector('button[data-regenerate-html="true"]') as HTMLButtonElement | null
    expect(regenerateButton).not.toBeNull()

    await act(async () => {
      regenerateButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(savedFinalMarkdown).toBe('# 新最终稿\n\n第二版')
    expect(container.textContent).toContain('已保存最终稿，并已触发 HTML 重新生成。')
  })

  it('generates updated final html preview in a new tab after editing', async () => {
    let savedFinalMarkdown = '# 最终稿\n\n初始版本'
    const openSpy = vi.fn()
    vi.stubGlobal('open', openSpy)

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-preview-final-tab',
              url: 'https://x.com/alice/status/7',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
              stage_probes: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-preview-final-tab' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-preview-final-tab',
            url: 'https://x.com/alice/status/7',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
            stage_probes: {},
          }),
        )
      }

      if (url === '/api/jobs/job-preview-final-tab/artifacts/10-final.md' && method === 'GET') {
        return Promise.resolve(textResponse(savedFinalMarkdown))
      }

      if (url === '/api/jobs/job-preview-final-tab/final-markdown' && method === 'PUT') {
        const payload = JSON.parse(String(init?.body))
        savedFinalMarkdown = payload.content
        return Promise.resolve(jsonResponse({ job_id: 'job-preview-final-tab', status: 'saved', relative_path: '10-final.md' }))
      }

      if (url === '/api/jobs/job-preview-final-tab/html-preview' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'final-output', force: true })
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-preview-final-tab',
            stage: 'final-output',
            source_artifact: '10-final.md',
            artifact_path: 'preview.assets/final-output.html',
            status: 'generated',
          }),
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(jobItem).not.toBeNull()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const finalTab = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('最终稿'))
    expect(finalTab).not.toBeUndefined()

    await act(async () => {
      finalTab!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const finalEditor = container.querySelector('textarea[data-final-markdown-editor="true"]') as HTMLTextAreaElement | null
    expect(finalEditor).not.toBeNull()

    await act(async () => {
      updateTextareaValue(finalEditor!, '# 新最终稿\n\n预览版')
      await flushMicrotasks()
    })

    const previewButton = container.querySelector('button[data-open-html-preview="true"]') as HTMLButtonElement | null
    expect(previewButton).not.toBeNull()

    await act(async () => {
      previewButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(savedFinalMarkdown).toBe('# 新最终稿\n\n预览版')
    expect(openSpy).toHaveBeenCalledWith(
      '/api/jobs/job-preview-final-tab/artifacts/preview.assets/final-output.html',
      '_blank',
      'noopener,noreferrer',
    )
    expect(container.textContent).toContain('已保存最终稿，并已生成 HTML 预览。')
  })

  it('updates the retried job list item to running after retry is accepted even if another job is selected', async () => {
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5ca',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'job-a boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5cb',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5ca',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              review: 9,
            },
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'job-a boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-b' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-b',
            url: 'https://x.com/alice/status/5cb',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:30Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      if (url === '/api/jobs/job-b/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-b source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-a'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-b'))
    expect(failedItem).not.toBeUndefined()
    expect(succeededItem).not.toBeUndefined()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      retryRequest.resolve(jsonResponse({ job_id: 'job-a', status: 'accepted', stage: 'review', mode: 'failed-stage' }, 202))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    const updatedJobAItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-a'),
    )
    expect(updatedJobAItem?.textContent).toContain('running')
    expect(updatedJobAItem?.textContent).toContain('翻译已完成，正在审阅。')
  })

  it('restores an earlier job list item when it fails after another job starts retrying', async () => {
    const retryJobARequest = deferred<Response>()
    const retryJobBRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5cc',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'job-a boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5cd',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5cc',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              review: 9,
            },
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'job-a boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-b' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-b',
            url: 'https://x.com/alice/status/5cd',
            created_at: '2026-05-03T00:00:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:30Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        return retryJobARequest.promise
      }

      if (url === '/api/jobs/job-b/retry' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'translate', mode: 'from-stage' })
        return retryJobBRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      if (url === '/api/jobs/job-b/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-b source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-a'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-b'))
    expect(failedItem).not.toBeUndefined()
    expect(succeededItem).not.toBeUndefined()

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryFailedStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    expect(retryFailedStageButton).not.toBeUndefined()

    await act(async () => {
      retryFailedStageButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const stageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(stageSelect).not.toBeNull()

    await act(async () => {
      updateSelectValue(stageSelect!, 'translate')
      await flushMicrotasks()
    })

    const retryFromStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '从该阶段重跑',
    )
    expect(retryFromStageButton).not.toBeUndefined()

    await act(async () => {
      retryFromStageButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      retryJobARequest.reject(new Error('阶段重试失败'))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('Job IDjob-b')
    expect(container.textContent).not.toContain('job-a boom')
    const restoredJobAItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-a'),
    )
    expect(restoredJobAItem?.textContent).toContain('failed')
    expect(restoredJobAItem?.textContent).toContain('任务在审阅阶段失败，请检查审阅提示词或输入内容。')

    await act(async () => {
      retryJobBRequest.reject(new Error('从指定阶段重跑失败'))
      await flushMicrotasks()
    })
  })

  it('disables deleting a job while its retry request is still pending', async () => {
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5ce',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'job-a boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5ce',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              review: 9,
            },
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'job-a boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-a'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    const deleteButton = Array.from(jobItem!.querySelectorAll('button')).find(
      (button) => button.textContent === '删除',
    )
    expect(retryButton).not.toBeUndefined()
    expect(deleteButton).not.toBeUndefined()
    expect(deleteButton?.disabled).toBe(false)

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const pendingDeleteButton = Array.from(container.querySelectorAll('.job-list-item button')).find(
      (button) => button.textContent === '删除',
    ) as HTMLButtonElement | undefined
    expect(pendingDeleteButton?.disabled).toBe(true)

    await act(async () => {
      retryRequest.reject(new Error('阶段重试失败'))
      await flushMicrotasks()
    })

    const restoredDeleteButton = Array.from(container.querySelectorAll('.job-list-item button')).find(
      (button) => button.textContent === '删除',
    ) as HTMLButtonElement | undefined
    expect(restoredDeleteButton?.disabled).toBe(false)
  })

  it('disables retry controls while the selected job is being deleted', async () => {
    const deleteRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5cf',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                review: 9,
              },
              stage_errors: {
                review: {
                  error_type: 'RuntimeError',
                  message: 'job-a boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5cf',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              review: 9,
            },
            stage_errors: {
              review: {
                error_type: 'RuntimeError',
                message: 'job-a boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'DELETE') {
        return deleteRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-a'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const deleteButton = Array.from(jobItem!.querySelectorAll('button')).find(
      (button) => button.textContent === '删除',
    )
    expect(deleteButton).not.toBeUndefined()

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryFailedStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    ) as HTMLButtonElement | undefined
    const retryFromStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '从该阶段重跑',
    ) as HTMLButtonElement | undefined
    const retryStageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null

    expect(retryFailedStageButton?.disabled).toBe(true)
    expect(retryFromStageButton?.disabled).toBe(true)
    expect(retryStageSelect?.disabled).toBe(true)

    await act(async () => {
      deleteRequest.resolve(new Response(null, { status: 204 }))
      await flushMicrotasks()
    })
  })

  it('tracks multiple deleting jobs independently in the job list', async () => {
    const deleteJobARequest = deferred<Response>()
    const deleteJobBRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5cg',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5ch',
              created_at: '2026-05-03T00:00:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'DELETE') {
        return deleteJobARequest.promise
      }

      if (url === '/api/jobs/job-b' && method === 'DELETE') {
        return deleteJobBRequest.promise
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const jobAItem = jobItems.find((item) => item.textContent?.includes('job-a')) as HTMLElement | undefined
    const jobBItem = jobItems.find((item) => item.textContent?.includes('job-b')) as HTMLElement | undefined
    expect(jobAItem).not.toBeUndefined()
    expect(jobBItem).not.toBeUndefined()

    const jobADeleteButton = Array.from(jobAItem!.querySelectorAll('button')).find(
      (button) => button.textContent === '删除',
    )
    const jobBDeleteButton = Array.from(jobBItem!.querySelectorAll('button')).find(
      (button) => button.textContent === '删除',
    )
    expect(jobADeleteButton).not.toBeUndefined()
    expect(jobBDeleteButton).not.toBeUndefined()

    await act(async () => {
      jobADeleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      jobBDeleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const deletingButtons = Array.from(container.querySelectorAll('.job-list-item button')).filter(
      (button) => button.textContent === '删除中…',
    )
    expect(deletingButtons).toHaveLength(2)

    await act(async () => {
      deleteJobARequest.resolve(new Response(null, { status: 204 }))
      await flushMicrotasks()
    })

    expect(Array.from(container.querySelectorAll('.job-list-item')).some((item) => item.textContent?.includes('job-a'))).toBe(false)
    expect(Array.from(container.querySelectorAll('.job-list-item button')).filter((button) => button.textContent === '删除中…')).toHaveLength(1)

    await act(async () => {
      deleteJobBRequest.resolve(new Response(null, { status: 204 }))
      await flushMicrotasks()
    })

    expect(container.querySelectorAll('.job-list-item')).toHaveLength(0)
  })

  it('does not replace a newly submitted job with a late initial job list response', async () => {
    const listJobsRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return listJobsRequest.promise
      }

      if (url === '/api/jobs' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-new', status: 'pending' }))
      }

      if (url === '/api/jobs/job-new/run' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-new', status: 'running' }))
      }

      if (url === '/api/jobs/job-new' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-new',
            url: 'https://x.com/alice/status/new',
            created_at: '2026-05-03T00:02:00Z',
            status: 'running',
            current_stage: 'x-fetch',
            started_at: '2026-05-03T00:02:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-new/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse(null, 404))
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
      updateInputValue(input!, 'https://x.com/alice/status/new')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('job-new')

    await act(async () => {
      listJobsRequest.resolve(jsonResponse([]))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('job-new')
  })

  it('does not show a stale initial job-list error after a newer local submit succeeds', async () => {
    const listJobsRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return listJobsRequest.promise
      }

      if (url === '/api/jobs' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-new', status: 'pending' }))
      }

      if (url === '/api/jobs/job-new/run' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-new', status: 'running' }))
      }

      if (url === '/api/jobs/job-new' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-new',
            url: 'https://x.com/alice/status/newer',
            created_at: '2026-05-03T00:03:00Z',
            status: 'running',
            current_stage: 'x-fetch',
            started_at: '2026-05-03T00:03:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-new/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse(null, 404))
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
      updateInputValue(input!, 'https://x.com/alice/status/newer')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      listJobsRequest.reject(new Error('boom'))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('job-new')
    expect(container.textContent).not.toContain('任务列表读取失败')
  })

  it('sends only one failed-stage retry request on rapid double click', async () => {
    let retryCalls = 0
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5ci',
              created_at: '2026-05-03T00:01:00Z',
              status: 'failed',
              current_stage: 'review',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                review: { error_type: 'RuntimeError', message: 'boom', retryable: true, suggestion: 'retry' },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5ci',
            created_at: '2026-05-03T00:01:00Z',
            status: 'failed',
            current_stage: 'review',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              review: { error_type: 'RuntimeError', message: 'boom', retryable: true, suggestion: 'retry' },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        retryCalls += 1
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '重试此阶段')
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(retryCalls).toBe(1)

    await act(async () => {
      retryRequest.reject(new Error('阶段重试失败'))
      await flushMicrotasks()
    })
  })

  it('ignores a late polling response after deleting the selected job', async () => {
    const jobDetailRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5cla',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return jobDetailRequest.promise
      }

      if (url === '/api/jobs/job-a' && method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-a'),
    ) as HTMLElement | undefined
    expect(jobItem).not.toBeUndefined()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const deleteButton = Array.from(jobItem!.querySelectorAll('button')).find((button) => button.textContent === '删除')
    expect(deleteButton).not.toBeUndefined()

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      jobDetailRequest.resolve(
        jsonResponse({
          job_id: 'job-a',
          url: 'https://x.com/alice/status/5cla',
          created_at: '2026-05-03T00:01:00Z',
          status: 'succeeded',
          current_stage: 'render-html',
          started_at: '2026-05-03T00:01:01Z',
          finished_at: '2026-05-03T00:01:20Z',
          stage_models: {},
          prompt_versions: {},
          stage_durations: {},
          stage_errors: {},
        }),
      )
      await flushMicrotasks()
    })

    expect(container.querySelectorAll('.job-list-item')).toHaveLength(0)
    expect(container.textContent).toContain('提交 URL 后将在这里显示任务进度。')
    expect(container.textContent).not.toContain('job-a')
  })

  it('sends only one advanced retry request on rapid double click', async () => {
    let retryCalls = 0
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5cj',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5cj',
            created_at: '2026-05-03T00:01:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        retryCalls += 1
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const stageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(stageSelect).not.toBeNull()

    await act(async () => {
      updateSelectValue(stageSelect!, 'translate')
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '从该阶段重跑')
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(retryCalls).toBe(1)

    await act(async () => {
      retryRequest.reject(new Error('从指定阶段重跑失败'))
      await flushMicrotasks()
    })
  })

  it('sends only one delete request on rapid double click', async () => {
    let deleteCalls = 0
    const deleteRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5ck',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'DELETE') {
        deleteCalls += 1
        return deleteRequest.promise
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    const deleteButton = Array.from(jobItem!.querySelectorAll('button')).find((button) => button.textContent === '删除')
    expect(deleteButton).not.toBeUndefined()

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(deleteCalls).toBe(1)

    await act(async () => {
      deleteRequest.resolve(new Response(null, { status: 204 }))
      await flushMicrotasks()
    })
  })

  it('does not restore an advanced retry snapshot after switching to another job before the request rejects', async () => {
    const retryRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5e',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {
                'render-html': 5,
              },
              stage_errors: {},
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5f',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                translate: {
                  error_type: 'RuntimeError',
                  message: 'job-b boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5e',
            created_at: '2026-05-03T00:01:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {
              'render-html': 5,
            },
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-b' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-b',
            url: 'https://x.com/alice/status/5f',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:30Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              translate: {
                error_type: 'RuntimeError',
                message: 'job-b boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-a/retry' && method === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ stage: 'translate', mode: 'from-stage' })
        return retryRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      if (url === '/api/jobs/job-b/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-b source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-a'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-b'))
    expect(succeededItem).not.toBeUndefined()
    expect(failedItem).not.toBeUndefined()

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const stageSelect = container.querySelector('select[name="retry-stage"]') as HTMLSelectElement | null
    expect(stageSelect).not.toBeNull()

    await act(async () => {
      updateSelectValue(stageSelect!, 'translate')
      await flushMicrotasks()
    })

    const retryButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '从该阶段重跑',
    )
    expect(retryButton).not.toBeUndefined()

    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).toContain('错误信息：job-b boom')
    const jobBRetryFailedStageButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '重试此阶段',
    )
    expect(jobBRetryFailedStageButton).not.toBeUndefined()
    expect(jobBRetryFailedStageButton?.disabled).toBe(false)
    expect(container.textContent).not.toContain('重试中…')

    await act(async () => {
      retryRequest.reject(new Error('从指定阶段重跑失败'))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).toContain('错误信息：job-b boom')
    expect(container.textContent).not.toContain('从指定阶段重跑失败')
  })

  it('keeps a newly selected job visible when deleting the previously selected job finishes later', async () => {
    const deleteRequest = deferred<Response>()

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-a',
              url: 'https://x.com/alice/status/5ga',
              created_at: '2026-05-03T00:01:00Z',
              status: 'succeeded',
              current_stage: 'render-html',
              started_at: '2026-05-03T00:01:01Z',
              finished_at: '2026-05-03T00:01:20Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
            {
              job_id: 'job-b',
              url: 'https://x.com/alice/status/5gb',
              created_at: '2026-05-03T00:00:00Z',
              status: 'failed',
              current_stage: 'translate',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: '2026-05-03T00:00:30Z',
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {
                translate: {
                  error_type: 'RuntimeError',
                  message: 'job-b boom',
                  retryable: true,
                  suggestion: 'retry',
                },
              },
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-a',
            url: 'https://x.com/alice/status/5ga',
            created_at: '2026-05-03T00:01:00Z',
            status: 'succeeded',
            current_stage: 'render-html',
            started_at: '2026-05-03T00:01:01Z',
            finished_at: '2026-05-03T00:01:20Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-b' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-b',
            url: 'https://x.com/alice/status/5gb',
            created_at: '2026-05-03T00:00:00Z',
            status: 'failed',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: '2026-05-03T00:00:30Z',
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {
              translate: {
                error_type: 'RuntimeError',
                message: 'job-b boom',
                retryable: true,
                suggestion: 'retry',
              },
            },
          }),
        )
      }

      if (url === '/api/jobs/job-a' && method === 'DELETE') {
        return deleteRequest.promise
      }

      if (url === '/api/jobs/job-a/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-a source'))
      }

      if (url === '/api/jobs/job-b/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('job-b source'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const jobItems = Array.from(container.querySelectorAll('.job-list-item'))
    const succeededItem = jobItems.find((item) => item.textContent?.includes('job-a'))
    const failedItem = jobItems.find((item) => item.textContent?.includes('job-b'))
    expect(succeededItem).not.toBeUndefined()
    expect(failedItem).not.toBeUndefined()

    await act(async () => {
      succeededItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    const deleteButton = Array.from(succeededItem!.querySelectorAll('button')).find(
      (button) => button.textContent === '删除',
    )
    expect(deleteButton).not.toBeUndefined()

    await act(async () => {
      deleteButton!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    await act(async () => {
      failedItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).toContain('错误信息：job-b boom')

    await act(async () => {
      deleteRequest.resolve(new Response(null, { status: 204 }))
      await flushMicrotasks()
    })

    expect(container.querySelector('.job-list-item.active')?.textContent).toContain('job-b')
    expect(container.textContent).toContain('job-b source')
    expect(container.textContent).toContain('错误信息：job-b boom')
    expect(Array.from(container.querySelectorAll('.job-list-item')).some((item) => item.textContent?.includes('job-a'))).toBe(false)
  })

  it('hides advanced retry controls for pending jobs', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-pending',
              url: 'https://x.com/alice/status/6',
              created_at: '2026-05-03T00:00:00Z',
              status: 'pending',
              current_stage: null,
              started_at: null,
              finished_at: null,
              stage_models: {},
              prompt_versions: {},
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-pending' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-pending',
            url: 'https://x.com/alice/status/6',
            created_at: '2026-05-03T00:00:00Z',
            status: 'pending',
            current_stage: null,
            started_at: null,
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    await selectJobListSegment(container, '全部')

    const pendingItem = Array.from(container.querySelectorAll('.job-list-item')).find((item) =>
      item.textContent?.includes('job-pending'),
    ) as HTMLElement | undefined
    expect(pendingItem).not.toBeUndefined()

    await act(async () => {
      pendingItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.querySelector('select[name="retry-stage"]')).toBeNull()
    expect(container.textContent).not.toContain('从该阶段重跑')
  })

  it('does not request future-stage artifacts before they should exist', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

      if (url === '/api/jobs' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'pending' }))
      }

      if (url === '/api/jobs/job-1/run' && method === 'POST') {
        return Promise.resolve(jsonResponse({ job_id: 'job-1', status: 'running' }))
      }

      if (url === '/api/jobs/job-1' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-1',
            url: 'https://x.com/example/status/1',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'translate',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-1/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      if (url === '/api/jobs/job-1/artifacts/02-translation.md' && method === 'GET') {
        throw new Error('translation artifact should not be requested before translate stage completes')
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
      updateInputValue(input!, 'https://x.com/example/status/1')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flushMicrotasks()
    })

    await toggleArtifactPreview(container)

    expect(container.textContent).toContain('source artifact')

    const translationTab = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '翻译稿',
    )
    expect(translationTab).not.toBeUndefined()

    await act(async () => {
      translationTab!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).toContain('该产物尚未生成。')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/jobs/job-1/artifacts/02-translation.md')
  })

  it('keeps prompt bodies collapsed until the user expands them', async () => {
    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: 'job-prompt-collapse',
              url: 'https://x.com/alice/status/6',
              created_at: '2026-05-03T00:00:00Z',
              status: 'running',
              current_stage: 'review',
              started_at: '2026-05-03T00:00:01Z',
              finished_at: null,
              stage_models: {
                review: { provider: 'qwen', model: 'qwen-mt-plus' },
              },
              prompt_versions: {
                review: 'review_custom.txt',
              },
              stage_durations: {},
              stage_errors: {},
            },
          ]),
        )
      }

      if (url === '/api/jobs/job-prompt-collapse' && method === 'GET') {
        return Promise.resolve(
          jsonResponse({
            job_id: 'job-prompt-collapse',
            url: 'https://x.com/alice/status/6',
            created_at: '2026-05-03T00:00:00Z',
            status: 'running',
            current_stage: 'review',
            started_at: '2026-05-03T00:00:01Z',
            finished_at: null,
            stage_models: {
              review: { provider: 'qwen', model: 'qwen-mt-plus' },
            },
            prompt_versions: {
              review: 'review_custom.txt',
            },
            stage_durations: {},
            stage_errors: {},
          }),
        )
      }

      if (url === '/api/jobs/job-prompt-collapse/artifacts/01-source.md' && method === 'GET') {
        return Promise.resolve(textResponse('source artifact'))
      }

      throw new Error(`unexpected request: ${method} ${url}`)
    })

    await act(async () => {
      root.render(<App />)
      await flushMicrotasks()
    })

    const jobItem = container.querySelector('.job-list-item') as HTMLElement | null
    expect(jobItem).not.toBeNull()

    await act(async () => {
      jobItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(container.textContent).not.toContain('你是一名会保留术语一致性的实验版审校助手。')

    const reviewPromptToggle = container.querySelector('button[data-prompt-stage="review"]') as HTMLButtonElement | null
    expect(reviewPromptToggle).not.toBeNull()
    expect(reviewPromptToggle?.getAttribute('aria-expanded')).toBe('false')

    await act(async () => {
      reviewPromptToggle!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushMicrotasks()
    })

    expect(reviewPromptToggle?.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('你是一名会保留术语一致性的实验版审校助手。')
  })

  it('submits jobs, polls to terminal status, and resets stale ui for a new submission', async () => {
    const secondCreate = deferred<Response>()
    const jobPollCount = new Map<string, number>()
    const artifactPollCount = new Map<string, number>()
    let createCount = 0

    fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const method = init?.method ?? 'GET'
      const promptResponse = maybePromptResponse(url)
      if (promptResponse) {
        return Promise.resolve(promptResponse)
      }

      if (url === '/api/jobs' && method === 'GET') {
        return Promise.resolve(jsonResponse([]))
      }

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
            current_stage: 'render-html',
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
            current_stage: count === 1 ? 'translate' : 'render-html',
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
    await toggleArtifactPreview(container)

    expect(container.textContent).toContain('old source artifact')

    act(() => {
      updateInputValue(input!, 'https://x.com/second/status/2')
      form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })

    expect(container.textContent).not.toContain('old source artifact')
    expect(container.textContent).toContain('提交 URL 后将在这里显示任务进度。')
    expect(container.textContent).toContain('任务运行后可在此查看各阶段产物。')

    await act(async () => {
      secondCreate.resolve(jsonResponse({ job_id: 'job-2', status: 'pending' }))
      await flushMicrotasks()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-2/run', expect.objectContaining({ method: 'POST' }))

    await selectJobListSegment(container, '全部')

    expect(container.textContent).toContain('job-2')
    expect(container.textContent).toContain('job-1')
    expect(container.textContent).toContain('running')
    await toggleArtifactPreview(container)

    expect(container.textContent).toContain('该产物尚未生成。')
    expect(container.textContent).toContain('原文已生成，正在翻译。')

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

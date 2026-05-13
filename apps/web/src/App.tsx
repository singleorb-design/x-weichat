import { useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiError,
  buildArtifactUrls,
  createJob,
  createJobsBatch,
  deleteJob,
  enqueueDiscovery,
  generateStageHtmlPreview,
  getArtifactIndex,
  getArtifactText,
  getDiscoveryArtifactIndex,
  getDiscoveryArtifactText,
  getDiscoveryLoginRun,
  getDiscoveryItems,
  getDiscoveryRun,
  getJob,
  getPromptText,
  getWeChatPublishRun,
  listJobs,
  listTrashedJobs,
  previewDiscovery,
  retryJob,
  restoreJob,
  runJob,
  setJobPublished,
  startWeChatPublish,
  startDiscoveryLogin,
  stopDiscoveryRun,
  stopJob,
  updateFinalMarkdown,
} from './api'
import { ArtifactTabs } from './components/ArtifactTabs'
import { HtmlPreview } from './components/HtmlPreview'
import { JobForm } from './components/JobForm'
import { JobPrompts, JobStatus } from './components/JobStatus'
import type { ArtifactKey, DiscoveryPreviewItem, DiscoveryRunStatusResponse, JobRecord, StageName, XLoginRunStatusResponse } from './types'

type PreviewArtifactKey = Exclude<ArtifactKey, 'html'>
type ProgressStepStatus = 'pending' | 'active' | 'completed' | 'failed'
type JobListSegment = 'needs_action' | 'all' | 'succeeded' | 'canceled' | 'trash'
type JobListSort = 'newest' | 'oldest'

interface ProgressStep {
  key: string
  label: string
  status: ProgressStepStatus
  detail: string | null
}

interface PromptDoc {
  stage: PromptStage
  label: string
  filename: string
  model: string | null
  content: string
}

type PromptStage = 'translate' | 'review' | 'route' | 'light-polish' | 'final-check' | 'targeted-fix'

const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'canceled', 'published'])
const STAGE_ORDER: StageName[] = [
  'x-fetch',
  'translate',
  'review',
  'route',
  'light-polish',
  'final-check',
  'targeted-fix',
  'final-output',
  'render-html',
]
const STAGE_LABELS: Record<StageName, string> = {
  'x-fetch': '原文抓取',
  translate: '翻译',
  review: '审阅',
  route: '路由判断',
  'light-polish': '轻编辑',
  'final-check': '终检',
  'targeted-fix': '定点修复',
  'final-output': '最终定稿',
  'render-html': 'HTML 渲染',
}
const PROMPT_STAGE_ORDER: PromptStage[] = ['translate', 'review', 'route', 'light-polish', 'final-check', 'targeted-fix']
const STAGE_PROMPT_FILENAMES: Record<PromptStage, string> = {
  translate: 'translate_zh.txt',
  review: 'review_zh.txt',
  route: 'route_zh.txt',
  'light-polish': 'light_polish_zh.txt',
  'final-check': 'final_check_zh.txt',
  'targeted-fix': 'targeted_fix_zh.txt',
}
const DISCOVERY_KEYWORD_PRESETS = ['ai', 'agent', 'codex', 'skill', 'claude'] as const
const ARTIFACT_STAGE_INDEX: Record<PreviewArtifactKey, number> = {
  source: 0,
  translation: 1,
  reviewed: 2,
  polished: 4,
  final: 7,
}
const ACTIVE_STAGE_STALE_AFTER_SECONDS = 30 * 60

type FinalDiffChoice = 'final' | 'polished'

type FinalDiffBlock =
  | { kind: 'context'; lines: string[] }
  | { kind: 'replace'; id: string; oldLines: string[]; newLines: string[]; choice: FinalDiffChoice }
  | { kind: 'insert'; id: string; lines: string[]; accepted: boolean }
  | { kind: 'delete'; id: string; lines: string[]; accepted: boolean }

type FinalDiffHunk = { header: string; oldStart: number; blocks: FinalDiffBlock[] }

function parseUnifiedDiffToFinalView(patchText: string): FinalDiffHunk[] {
  const lines = patchText.split('\n')
  const hunks: FinalDiffHunk[] = []

  let current: { header: string; oldStart: number; raw: Array<{ tag: string; text: string }> } | null = null

  const flush = () => {
    if (!current) {
      return
    }

    const blocks: FinalDiffBlock[] = []
    let blockIndex = 0
    let index = 0

    while (index < current.raw.length) {
      const item = current.raw[index]
      if (item.tag === ' ') {
        const context: string[] = []
        while (index < current.raw.length && current.raw[index].tag === ' ') {
          context.push(current.raw[index].text)
          index += 1
        }
        blocks.push({ kind: 'context', lines: context })
        continue
      }

      if (item.tag === '-' || item.tag === '+') {
        const oldLines: string[] = []
        const newLines: string[] = []
        while (index < current.raw.length && (current.raw[index].tag === '-' || current.raw[index].tag === '+')) {
          const currentLine = current.raw[index]
          if (currentLine.tag === '-') {
            oldLines.push(currentLine.text)
          } else {
            newLines.push(currentLine.text)
          }
          index += 1
        }

        const id = `hunk-${hunks.length}-block-${blockIndex}`
        blockIndex += 1
        if (oldLines.length > 0 && newLines.length > 0) {
          blocks.push({ kind: 'replace', id, oldLines, newLines, choice: 'final' })
        } else if (newLines.length > 0) {
          blocks.push({ kind: 'insert', id, lines: newLines, accepted: true })
        } else {
          blocks.push({ kind: 'delete', id, lines: oldLines, accepted: true })
        }
        continue
      }

      // Ignore markers like "\\ No newline at end of file".
      index += 1
    }

    hunks.push({ header: current.header, oldStart: current.oldStart, blocks })
    current = null
  }

  for (const line of lines) {
    if (line.startsWith('@@ ')) {
      flush()
      const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/)
      const oldStart = match ? Number(match[1]) : 1
      current = { header: line, oldStart, raw: [] }
      continue
    }

    if (!current) {
      continue
    }

    const tag = line.slice(0, 1)
    if (tag === ' ' || tag === '-' || tag === '+') {
      current.raw.push({ tag, text: line.slice(1) })
      continue
    }

    if (tag === '\\') {
      continue
    }
  }

  flush()
  return hunks
}

function splitLinesPreserveNewline(text: string): { lines: string[]; endsWithNewline: boolean } {
  const endsWithNewline = text.endsWith('\n')
  const normalized = endsWithNewline ? text.slice(0, -1) : text
  const lines = normalized.length === 0 ? [] : normalized.split('\n')
  return { lines, endsWithNewline }
}

function applyFinalDiffSelection(base: string, hunks: FinalDiffHunk[]): { content: string; error: string | null } {
  const { lines: baseLines, endsWithNewline } = splitLinesPreserveNewline(base)
  const output: string[] = []
  let cursor = 0

  const expectLine = (expected: string, errorMessage: string): { ok: boolean; error: string | null } => {
    const actual = baseLines[cursor]
    if (actual !== expected) {
      return { ok: false, error: errorMessage }
    }
    return { ok: true, error: null }
  }

  for (const hunk of hunks) {
    const targetIndex = Math.max(0, hunk.oldStart - 1)
    while (cursor < targetIndex && cursor < baseLines.length) {
      output.push(baseLines[cursor])
      cursor += 1
    }

    for (const block of hunk.blocks) {
      if (block.kind === 'context') {
        for (const line of block.lines) {
          const check = expectLine(
            line,
            '无法应用 diff：轻编辑稿内容已变化（上下文不匹配）。请重新读取轻编辑稿/重跑任务后再试。',
          )
          if (!check.ok) {
            return { content: base, error: check.error }
          }
          output.push(baseLines[cursor])
          cursor += 1
        }
        continue
      }

      if (block.kind === 'replace') {
        const keptOld: string[] = []
        for (const line of block.oldLines) {
          const check = expectLine(
            line,
            '无法应用 diff：轻编辑稿内容已变化（替换块不匹配）。请重新读取轻编辑稿/重跑任务后再试。',
          )
          if (!check.ok) {
            return { content: base, error: check.error }
          }
          keptOld.push(baseLines[cursor])
          cursor += 1
        }
        if (block.choice === 'polished') {
          output.push(...keptOld)
        } else {
          output.push(...block.newLines)
        }
        continue
      }

      if (block.kind === 'delete') {
        const keptOld: string[] = []
        for (const line of block.lines) {
          const check = expectLine(
            line,
            '无法应用 diff：轻编辑稿内容已变化（删除块不匹配）。请重新读取轻编辑稿/重跑任务后再试。',
          )
          if (!check.ok) {
            return { content: base, error: check.error }
          }
          keptOld.push(baseLines[cursor])
          cursor += 1
        }
        if (!block.accepted) {
          output.push(...keptOld)
        }
        continue
      }

      if (block.kind === 'insert' && block.accepted) {
        output.push(...block.lines)
      }
    }
  }

  while (cursor < baseLines.length) {
    output.push(baseLines[cursor])
    cursor += 1
  }

  const content = output.join('\n') + (endsWithNewline ? '\n' : '')
  return { content, error: null }
}

function formatRetryError(error: unknown, requestedStage: StageName): string {
  const stageLabel = STAGE_LABELS[requestedStage]
  if (error instanceof ApiError && error.detail) {
    const message = error.detail.message ?? error.message
    const suggestion = error.detail.suggestion ? `建议：${error.detail.suggestion}` : null
    const stageChangeHint = error.detail.can_change_stage ? '等当前执行结束后，可以直接换一个起始阶段再试。' : null
    if (error.detail.code === 'job_retry_claim_conflict') {
      return [`本次从“${stageLabel}”开始的重跑没有提交成功。`, message, suggestion, stageChangeHint].filter(Boolean).join(' ')
    }
    return [message, suggestion, stageChangeHint].filter(Boolean).join(' ')
  }

  return error instanceof Error ? error.message : `从“${stageLabel}”开始重跑失败`
}

function clearTailStageData(stage: StageName, currentJob: JobRecord): JobRecord {
  const currentStageIndex = STAGE_ORDER.indexOf(stage)
  const stagesToClear = STAGE_ORDER.slice(Math.max(0, currentStageIndex))

  return {
    ...currentJob,
    status: 'pending',
    started_at: null,
    finished_at: null,
    stage_durations: Object.fromEntries(
      Object.entries(currentJob.stage_durations ?? {}).filter(([key]) => !stagesToClear.includes(key as StageName)),
    ),
    stage_errors: Object.fromEntries(
      Object.entries(currentJob.stage_errors ?? {}).filter(([key]) => !stagesToClear.includes(key as StageName)),
    ),
    stage_probes: Object.fromEntries(
      Object.entries(currentJob.stage_probes ?? {}).filter(([key]) => !stagesToClear.includes(key as StageName)),
    ),
    stage_models: Object.fromEntries(
      Object.entries(currentJob.stage_models ?? {}).filter(([key]) => !stagesToClear.includes(key as StageName)),
    ),
    prompt_versions: Object.fromEntries(
      Object.entries(currentJob.prompt_versions ?? {}).filter(([key]) => !stagesToClear.includes(key as StageName)),
    ),
  }
}

function markRetryAccepted(stage: StageName, currentJob: JobRecord): JobRecord {
  return {
    ...clearTailStageData(stage, currentJob),
    status: 'running',
    current_stage: stage,
    started_at: new Date().toISOString(),
  }
}

function buildJobListTitle(job: JobRecord): string {
  const title = (job.source_title ?? '').trim()
  if (title) {
    return title
  }

  // Fallback: derive a readable label from URL, so list is still scannable.
  try {
    const url = new URL(job.url)
    const host = url.hostname.replace(/^www\./, '')
    const path = url.pathname
    const matchArticle = path.match(/\/(?:i\/articles?|[^/]+\/article)\/(\d+)/)
    if (host === 'x.com' && matchArticle?.[1]) {
      return `X 文章 · ${matchArticle[1]}`
    }
    const matchTweet = path.match(/\/status\/(\d+)/)
    if (host === 'x.com' && matchTweet?.[1]) {
      return `X 推文 · ${matchTweet[1]}`
    }
    const shortPath = path.length > 42 ? `${path.slice(0, 42)}…` : path
    return `${host}${shortPath || ''}`
  } catch {
    return job.url
  }
}

function isArtifactReady(job: JobRecord | null, artifactKey: PreviewArtifactKey): boolean {
  if (!job || job.status === 'pending') {
    return false
  }

  if (job.status === 'succeeded' || job.status === 'published') {
    return true
  }

  const currentStageIndex = STAGE_ORDER.indexOf(job.current_stage as (typeof STAGE_ORDER)[number])
  if (currentStageIndex === -1) {
    return true
  }

  return ARTIFACT_STAGE_INDEX[artifactKey] < currentStageIndex
}

function buildRetryStageOptions(job: JobRecord | null): Array<{ value: StageName; label: string }> {
  if (job?.status === 'failed') {
    const currentStageIndex = STAGE_ORDER.indexOf(job.current_stage as (typeof STAGE_ORDER)[number])
    const allowedStages = currentStageIndex >= 0 ? STAGE_ORDER.slice(0, currentStageIndex + 1) : STAGE_ORDER

    return allowedStages.map((stage) => ({ value: stage, label: STAGE_LABELS[stage] }))
  }

  return STAGE_ORDER.map((stage) => ({ value: stage, label: STAGE_LABELS[stage] }))
}

function defaultRetryStageForJob(job: JobRecord | null): StageName {
  if ((job?.status === 'succeeded' || job?.status === 'failed') && job.current_stage) {
    return job.current_stage
  }

  return 'render-html'
}

function sanitizeRetryStage(
  currentRetryStage: StageName,
  retryStageOptions: Array<{ value: StageName; label: string }>,
  fallbackStage: StageName,
): StageName {
  if (retryStageOptions.some((option) => option.value === currentRetryStage)) {
    return currentRetryStage
  }

  if (retryStageOptions.some((option) => option.value === fallbackStage)) {
    return fallbackStage
  }

  return retryStageOptions[0]?.value ?? 'render-html'
}

export default function App() {
  const [url, setUrl] = useState('')
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [trashJobs, setTrashJobs] = useState<JobRecord[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobRecord | null>(null)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [trashError, setTrashError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [traceExpanded, setTraceExpanded] = useState(false)
  const [traceFiles, setTraceFiles] = useState<string[]>([])
  const [traceError, setTraceError] = useState<string | null>(null)
  const [activeTraceFile, setActiveTraceFile] = useState<string | null>(null)
  const [traceContent, setTraceContent] = useState<string | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [batchUrlsText, setBatchUrlsText] = useState('')
  const [batchSubmitMessage, setBatchSubmitMessage] = useState<string | null>(null)
  const [batchSubmitError, setBatchSubmitError] = useState<string | null>(null)
  const [deletingJobIds, setDeletingJobIds] = useState<string[]>([])
  const [restoringJobIds, setRestoringJobIds] = useState<string[]>([])
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [activeArtifact, setActiveArtifact] = useState<PreviewArtifactKey>('source')
  const [artifactPreviewExpanded, setArtifactPreviewExpanded] = useState(false)
  const [htmlPreviewExpanded, setHtmlPreviewExpanded] = useState(false)
  const [htmlPreviewStage, setHtmlPreviewStage] = useState<StageName>('final-output')
  const [htmlPreviewUrl, setHtmlPreviewUrl] = useState<string | null>(null)
  const [htmlPreviewBusy, setHtmlPreviewBusy] = useState(false)
  const [htmlPreviewError, setHtmlPreviewError] = useState<string | null>(null)

  const [wechatPublishRunId, setWeChatPublishRunId] = useState<string | null>(null)
  const [wechatPublishBusy, setWeChatPublishBusy] = useState(false)
  const [wechatPublishMessage, setWeChatPublishMessage] = useState<string | null>(null)
  const [wechatPublishError, setWeChatPublishError] = useState<string | null>(null)
  const [finalHtmlModalJob, setFinalHtmlModalJob] = useState<JobRecord | null>(null)
  const [copiedJobId, setCopiedJobId] = useState<string | null>(null)
  const [finalMarkdownDraft, setFinalMarkdownDraft] = useState('')
  const [finalMarkdownDirty, setFinalMarkdownDirty] = useState(false)
  const [finalMarkdownLoadedJobId, setFinalMarkdownLoadedJobId] = useState<string | null>(null)
  const [finalMarkdownBusy, setFinalMarkdownBusy] = useState(false)
  const [finalMarkdownMessage, setFinalMarkdownMessage] = useState<string | null>(null)
  const [finalMarkdownError, setFinalMarkdownError] = useState<string | null>(null)
  const [finalDiffOpen, setFinalDiffOpen] = useState(false)
  const [finalDiffBusy, setFinalDiffBusy] = useState(false)
  const [finalDiffError, setFinalDiffError] = useState<string | null>(null)
  const [finalDiffSummary, setFinalDiffSummary] = useState<string | null>(null)
  const [finalDiffHunks, setFinalDiffHunks] = useState<FinalDiffHunk[] | null>(null)
  const [finalDiffPolishedBase, setFinalDiffPolishedBase] = useState<string | null>(null)
  const [pollTick, setPollTick] = useState(0)
  const [jobSyncVersion, setJobSyncVersion] = useState(0)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [promptTexts, setPromptTexts] = useState<Record<string, string>>({})
  const [promptError, setPromptError] = useState<string | null>(null)
  const [retryingJobIds, setRetryingJobIds] = useState<string[]>([])
  const [retryError, setRetryError] = useState<string | null>(null)
  const [retryStage, setRetryStage] = useState<StageName>('render-html')

  const [jobListQuery, setJobListQuery] = useState('')
  const [jobListSegment, setJobListSegment] = useState<JobListSegment>('all')
  const [jobListSort, setJobListSort] = useState<JobListSort>('newest')

  const [stoppingJobId, setStoppingJobId] = useState<string | null>(null)
  const [stopError, setStopError] = useState<string | null>(null)

  const [discoveryAccounts, setDiscoveryAccounts] = useState('')
  const [discoveryKeywords, setDiscoveryKeywords] = useState('ai')
  const [discoveryRequiredKeywords, setDiscoveryRequiredKeywords] = useState('AI, agent, LLM, RAG, Prompt')
  const [discoveryIncludeRecommendations, setDiscoveryIncludeRecommendations] = useState(true)
  const [discoveryMinLikes, setDiscoveryMinLikes] = useState(100)
  const [discoveryMaxCandidates, setDiscoveryMaxCandidates] = useState(5)
  const [discoveryMaxScrolls, setDiscoveryMaxScrolls] = useState(4)
  const [discoveryAdvanced, setDiscoveryAdvanced] = useState(false)
  const [discoveryLoading, setDiscoveryLoading] = useState(false)
  const [discoveryError, setDiscoveryError] = useState<string | null>(null)
  const [discoveryRunId, setDiscoveryRunId] = useState<string | null>(null)
  const [discoveryStatus, setDiscoveryStatus] = useState<DiscoveryRunStatusResponse | null>(null)
  const [discoveryStats, setDiscoveryStats] = useState<Record<string, number> | null>(null)
  const [discoveryItems, setDiscoveryItems] = useState<DiscoveryPreviewItem[]>([])
  const [discoverySelected, setDiscoverySelected] = useState<Record<string, boolean>>({})
  const [discoveryEnqueueLoading, setDiscoveryEnqueueLoading] = useState(false)
  const [discoveryStopping, setDiscoveryStopping] = useState(false)
  const [discoveryDebugExpanded, setDiscoveryDebugExpanded] = useState(false)
  const [discoveryDebugFiles, setDiscoveryDebugFiles] = useState<string[]>([])
  const [discoveryDebugActiveFile, setDiscoveryDebugActiveFile] = useState<string | null>(null)
  const [discoveryDebugContent, setDiscoveryDebugContent] = useState<string | null>(null)
  const [discoveryDebugLoading, setDiscoveryDebugLoading] = useState(false)
  const [discoveryDebugError, setDiscoveryDebugError] = useState<string | null>(null)
  const [discoveryLoginRunId, setDiscoveryLoginRunId] = useState<string | null>(null)
  const [discoveryLoginStatus, setDiscoveryLoginStatus] = useState<XLoginRunStatusResponse | null>(null)
  const [discoveryLoginLoading, setDiscoveryLoginLoading] = useState(false)
  // 轮询和产物读取都可能在用户快速切换任务/标签时“晚到”；
  // 用递增请求号拦住过期响应，避免旧数据覆盖当前选中的任务状态。
  const pollSessionRef = useRef(0)
  const discoveryPollSessionRef = useRef(0)
  const discoveryLoginPollSessionRef = useRef(0)
  const discoveryDebugRequestRef = useRef(0)
  const artifactRequestRef = useRef(0)
  const traceRequestRef = useRef(0)
  const retryRequestRef = useRef(0)
  const retryRequestByJobRef = useRef<Record<string, number>>({})
  const jobsMutationRef = useRef(0)
  const retryingJobIdsRef = useRef(new Set<string>())
  const deletingJobIdsRef = useRef(new Set<string>())
  const restoringJobIdsRef = useRef(new Set<string>())
  const selectedJobIdRef = useRef<string | null>(null)
  const finalHtmlModalRef = useRef<HTMLDivElement | null>(null)
  const finalHtmlModalCloseRef = useRef<HTMLButtonElement | null>(null)
  const finalHtmlModalRestoreFocusRef = useRef<HTMLElement | null>(null)
  const copiedJobTimerRef = useRef<number | null>(null)

  const artifactUrls = useMemo(
    () => (jobId ? buildArtifactUrls(jobId) : null),
    [jobId],
  )
  const jobsById = useMemo(
    () => Object.fromEntries(jobs.map((item) => [item.job_id, item] as const)),
    [jobs],
  )

  const finalHtmlModalUrl = useMemo(() => {
    if (!finalHtmlModalJob) {
      return null
    }
    return `/api/jobs/${finalHtmlModalJob.job_id}/artifacts/11-wechat.html`
  }, [finalHtmlModalJob])

  useEffect(() => {
    if (!finalHtmlModalJob) {
      return
    }

    finalHtmlModalRestoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    const focusFirst = () => {
      const preferred = finalHtmlModalCloseRef.current
      if (preferred) {
        preferred.focus()
        return
      }
      const container = finalHtmlModalRef.current
      if (!container) {
        return
      }
      container.focus()
    }

    const getFocusableElements = (container: HTMLElement) => {
      const nodes = Array.from(
        container.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((node) => {
        if (node.getAttribute('aria-hidden') === 'true') {
          return false
        }
        const style = window.getComputedStyle(node)
        return style.display !== 'none' && style.visibility !== 'hidden'
      })
      return nodes
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setFinalHtmlModalJob(null)
        return
      }

      if (event.key !== 'Tab') {
        return
      }
      const container = finalHtmlModalRef.current
      if (!container) {
        return
      }
      const focusables = getFocusableElements(container)
      if (focusables.length === 0) {
        event.preventDefault()
        container.focus()
        return
      }

      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || !container.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else {
        if (active === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // 让 modal DOM 先挂载，再聚焦
    window.setTimeout(() => focusFirst(), 0)

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      finalHtmlModalRestoreFocusRef.current?.focus()
      finalHtmlModalRestoreFocusRef.current = null
    }
  }, [finalHtmlModalJob])

  useEffect(() => {
    return () => {
      if (copiedJobTimerRef.current !== null) {
        window.clearTimeout(copiedJobTimerRef.current)
        copiedJobTimerRef.current = null
      }
    }
  }, [])

  const jobListStats = useMemo(() => {
    const counts = {
      needs_action: 0,
      all: jobs.length,
      succeeded: 0,
      canceled: 0,
      trash: trashJobs.length,
    }
    for (const item of jobs) {
      if (item.status === 'running' || item.status === 'failed') {
        counts.needs_action += 1
      }
      if (item.status === 'succeeded') {
        counts.succeeded += 1
      }
      if (item.status === 'canceled') {
        counts.canceled += 1
      }
    }
    return counts
  }, [jobs, trashJobs])

  const hasAnyJobs = jobs.length > 0 || trashJobs.length > 0
  const activeListError = jobListSegment === 'trash' ? trashError : jobsError

  const visibleJobs = useMemo(() => {
    const normalizedQuery = jobListQuery.trim().toLowerCase()

    const source = jobListSegment === 'trash' ? trashJobs : jobs

    const matchesQuery = (job: JobRecord) => {
      if (!normalizedQuery) {
        return true
      }
      const haystack = [job.source_title ?? '', job.url ?? '', job.job_id ?? '', job.current_stage ?? '']
        .join(' ')
        .toLowerCase()
      return haystack.includes(normalizedQuery)
    }

    const matchesSegment = (job: JobRecord) => {
      if (jobListSegment === 'trash') {
        return true
      }
      if (jobListSegment === 'all') {
        return true
      }
      if (jobListSegment === 'needs_action') {
        return job.status === 'running' || job.status === 'failed'
      }
      if (jobListSegment === 'succeeded') {
        return job.status === 'succeeded' || job.status === 'published'
      }
      return job.status === 'canceled'
    }

    const result = source.filter((item) => matchesSegment(item) && matchesQuery(item))
    result.sort((a, b) => {
      const left = a.created_at
      const right = b.created_at

      if (jobListSegment === 'all') {
        const weight = (status: JobRecord['status']) => {
          if (status === 'published') return 0
          if (status === 'succeeded') return 1
          if (status === 'failed') return 2
          if (status === 'canceled') return 3
          if (status === 'running') return 4
          return 5
        }
        const byStatus = weight(a.status) - weight(b.status)
        if (byStatus !== 0) {
          return byStatus
        }
      }

      return jobListSort === 'newest' ? right.localeCompare(left) : left.localeCompare(right)
    })

    return result
  }, [jobId, jobListQuery, jobListSegment, jobListSort, jobs, trashJobs])
  const discoveryProgress = discoveryStatus?.progress_json ?? {}
  const discoveryLoginProgress = discoveryLoginStatus?.progress_json ?? {}
  const discoveryReasonText = formatDiscoverySuspectedReason(discoveryProgress.suspected_reason, discoveryProgress)
  const discoveryNeedsLogin = discoveryProgress.suspected_reason === 'login_required'
    || (discoveryProgress.current_source_kind === 'recommendation' && discoveryProgress.suspected_reason === 'page_structure_unmatched')
    || Boolean(discoveryError && discoveryError.includes('重新登录'))

  // UI-only derived stats (real-time): keep the backend contract minimal and avoid stale counters
  // by computing totals directly from `discoveryItems`.
  const discoveryCandidateStats = useMemo(() => {
    const total = discoveryItems.length
    const alreadyEnqueued = discoveryItems.reduce((acc, item) => acc + (item.already_enqueued ? 1 : 0), 0)
    const canEnqueue = Math.max(0, total - alreadyEnqueued)
    return { total, canEnqueue, alreadyEnqueued }
  }, [discoveryItems])

  // Human-friendly source label shown in the Discovery status chips.
  const discoverySourceValueLabel = useMemo(() => {
    const kind = discoveryProgress.current_source_kind
    const value = discoveryProgress.current_source_value
    if (!value) {
      return null
    }
    if (kind === 'recommendation' && value === 'for_you') {
      return 'For You'
    }
    return value
  }, [discoveryProgress.current_source_kind, discoveryProgress.current_source_value])

  const mergeJobIntoList = (nextJob: JobRecord) => {
    jobsMutationRef.current += 1
    setJobs((current) => {
      const remainingJobs = current.filter((item) => item.job_id !== nextJob.job_id)
      return [nextJob, ...remainingJobs].sort(
        (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
      )
    })
  }

  const handleStopJob = async () => {
    if (!jobId) {
      return
    }
    if (stoppingJobId === jobId) {
      return
    }

    setStopError(null)
    setStoppingJobId(jobId)
    try {
      const updated = await stopJob(jobId)
      mergeJobIntoList(updated)
      if (selectedJobIdRef.current === jobId) {
        setJob(updated)
        setStatusError(null)
      }
    } catch (error) {
      setStopError(error instanceof Error ? error.message : '停止任务失败')
    } finally {
      setStoppingJobId((current) => (current === jobId ? null : current))
    }
  }

  const handleMarkPublished = async (target: JobRecord) => {
    if (target.status !== 'succeeded') {
      return
    }
    try {
      const updated = await setJobPublished(target.job_id, true)
      mergeJobIntoList(updated)
      if (selectedJobIdRef.current === target.job_id) {
        setJob(updated)
      }
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '标记已发布失败')
    }
  }

  const removeJobFromList = (targetJobId: string) => {
    jobsMutationRef.current += 1
    setJobs((current) => current.filter((item) => item.job_id !== targetJobId))
  }

  const handleSelectJob = (nextJob: JobRecord) => {
    selectedJobIdRef.current = nextJob.job_id
    setJobId(nextJob.job_id)
    setJob(nextJob)
    setNowMs(Date.now())
    setStatusError(null)
    setRetryError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setActiveArtifact('source')
    setArtifactPreviewExpanded(true)
    setHtmlPreviewExpanded(false)
    setHtmlPreviewStage('final-output')
    setHtmlPreviewUrl(null)
    setHtmlPreviewBusy(false)
    setHtmlPreviewError(null)
    setFinalMarkdownDraft('')
    setFinalMarkdownDirty(false)
    setFinalMarkdownLoadedJobId(null)
    setFinalMarkdownBusy(false)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    setFinalDiffOpen(false)
    setFinalDiffBusy(false)
    setFinalDiffError(null)
    setFinalDiffSummary(null)
    setFinalDiffHunks(null)
    setFinalDiffPolishedBase(null)
    setTraceExpanded(false)
    setTraceFiles([])
    setTraceError(null)
    setActiveTraceFile(null)
    setTraceContent(null)
    setTraceLoading(false)
    setPollTick(0)
  }

  useEffect(() => {
    setFinalMarkdownDraft('')
    setFinalMarkdownDirty(false)
    setFinalMarkdownLoadedJobId(null)
    setFinalMarkdownBusy(false)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    setFinalDiffOpen(false)
    setFinalDiffBusy(false)
    setFinalDiffError(null)
    setFinalDiffSummary(null)
    setFinalDiffHunks(null)
    setFinalDiffPolishedBase(null)

    setHtmlPreviewStage('final-output')
    setHtmlPreviewUrl(null)
    setHtmlPreviewBusy(false)
    setHtmlPreviewError(null)

    setWeChatPublishRunId(null)
    setWeChatPublishBusy(false)
    setWeChatPublishMessage(null)
    setWeChatPublishError(null)
  }, [jobId])

  useEffect(() => {
    if (!wechatPublishRunId) {
      return
    }

    let cancelled = false
    const timer = window.setInterval(() => {
      void getWeChatPublishRun(wechatPublishRunId)
        .then((status) => {
          if (cancelled) {
            return
          }
          setWeChatPublishMessage(status.progress_message ?? null)
          setWeChatPublishError(status.error_message ?? null)
          if (status.completed) {
            window.clearInterval(timer)
            setWeChatPublishBusy(false)
          }
        })
        .catch((error) => {
          if (cancelled) {
            return
          }
          setWeChatPublishError(error instanceof Error ? error.message : '公众号发布状态读取失败')
        })
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [wechatPublishRunId])

  const handleDeleteJob = async (targetJob: JobRecord) => {
    if (deletingJobIdsRef.current.has(targetJob.job_id)) {
      return
    }

    deletingJobIdsRef.current.add(targetJob.job_id)
    setDeletingJobIds((current) => (current.includes(targetJob.job_id) ? current : [...current, targetJob.job_id]))
    try {
      await deleteJob(targetJob.job_id)
      delete retryRequestByJobRef.current[targetJob.job_id]
      retryingJobIdsRef.current.delete(targetJob.job_id)
      setRetryingJobIds((current) => current.filter((item) => item !== targetJob.job_id))
      removeJobFromList(targetJob.job_id)
      void listTrashedJobs()
        .then((items) => {
          setTrashJobs(items)
          setTrashError(null)
        })
        .catch((error) => {
          setTrashError(error instanceof Error ? error.message : '回收站读取失败')
        })
      setJobsError(null)

      if (selectedJobIdRef.current === targetJob.job_id) {
        pollSessionRef.current += 1
        selectedJobIdRef.current = null
        setJobId(null)
        setJob(null)
        setNowMs(Date.now())
        setStatusError(null)
        setRetryError(null)
        setArtifactError(null)
        setArtifactContent(null)
        setActiveArtifact('source')
        setArtifactPreviewExpanded(false)
        setHtmlPreviewExpanded(false)
        setTraceExpanded(false)
        setTraceFiles([])
        setTraceError(null)
        setActiveTraceFile(null)
        setTraceContent(null)
        setTraceLoading(false)
        setPollTick(0)
      }
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '任务删除失败')
    } finally {
      deletingJobIdsRef.current.delete(targetJob.job_id)
      setDeletingJobIds((current) => current.filter((item) => item !== targetJob.job_id))
    }
  }

  const handleRestoreJob = async (targetJob: JobRecord) => {
    if (restoringJobIdsRef.current.has(targetJob.job_id)) {
      return
    }

    restoringJobIdsRef.current.add(targetJob.job_id)
    setRestoringJobIds((current) => (current.includes(targetJob.job_id) ? current : [...current, targetJob.job_id]))
    try {
      const restored = await restoreJob(targetJob.job_id)
      setTrashJobs((current) => current.filter((item) => item.job_id !== targetJob.job_id))
      mergeJobIntoList(restored)
      setTrashError(null)
      setJobsError(null)
    } catch (error) {
      setTrashError(error instanceof Error ? error.message : '任务恢复失败')
    } finally {
      restoringJobIdsRef.current.delete(targetJob.job_id)
      setRestoringJobIds((current) => current.filter((item) => item !== targetJob.job_id))
    }
  }

  const progressSteps = useMemo(() => buildProgressSteps(job, nowMs), [job, nowMs])
  const progressMessage = useMemo(() => buildProgressMessage(job), [job])
  const elapsedSummary = useMemo(() => buildElapsedSummary(job, nowMs), [job, nowMs])
  const stopEnabled = useMemo(() => {
    if (!job || job.status !== 'running' || !job.started_at) {
      return false
    }
    const startedMs = Date.parse(job.started_at)
    if (Number.isNaN(startedMs)) {
      return false
    }
    return nowMs - startedMs >= 10 * 60 * 1000
  }, [job, nowMs])
  const promptDocs = useMemo(() => buildPromptDocs(job, promptTexts), [job, promptTexts])
  const promptFilenames = useMemo(
    () => PROMPT_STAGE_ORDER.map((stage) => promptFilenameForStage(job, stage)),
    [job],
  )
  const promptFilenameSignature = useMemo(() => promptFilenames.join('|'), [promptFilenames])
  const retryStageOptions = useMemo(() => buildRetryStageOptions(job), [job])

  useEffect(() => {
    selectedJobIdRef.current = jobId
  }, [jobId])

  useEffect(() => {
    setRetryStage(defaultRetryStageForJob(job))
  }, [job?.current_stage, job?.job_id, job?.status])

  useEffect(() => {
    const fallbackRetryStage = defaultRetryStageForJob(job)
    setRetryStage((current) => sanitizeRetryStage(current, retryStageOptions, fallbackRetryStage))
  }, [job, retryStageOptions])

  useEffect(() => {
    let cancelled = false

    // Prompt 文本默认来自仓库里的静态文件，但任务元数据里也会记录“本次实际使用的文件名”。
    // 这里优先按任务记录去取，避免 UI 展示的文件名和正文内容不一致。
    void Promise.all(
      PROMPT_STAGE_ORDER.map(async (stage, index) => ({
        stage,
        filename: promptFilenames[index],
        content: await getPromptText(promptFilenames[index]),
      })),
    )
      .then((items) => {
        if (cancelled) {
          return
        }

        setPromptTexts(
          items.reduce<Record<string, string>>((next, item) => {
            next[item.filename] = item.content
            return next
          }, {}),
        )
        setPromptError(null)
      })
      .catch((error) => {
        if (!cancelled) {
          setPromptError(error instanceof Error ? error.message : 'Prompt 读取失败')
        }
      })

    return () => {
      cancelled = true
    }
  }, [promptFilenameSignature])

  useEffect(() => {
    let cancelled = false
    const jobsMutationVersion = jobsMutationRef.current

    void Promise.allSettled([listJobs(), listTrashedJobs()]).then((results) => {
      if (cancelled || jobsMutationRef.current !== jobsMutationVersion) {
        return
      }
      const [jobsResult, trashResult] = results
      if (jobsResult.status === 'fulfilled') {
        setJobs(jobsResult.value)
        setJobsError(null)
      } else {
        setJobsError('任务列表读取失败')
      }
      if (trashResult.status === 'fulfilled') {
        setTrashJobs(trashResult.value)
        setTrashError(null)
      } else {
        setTrashError('回收站读取失败')
      }
    })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (jobListSegment !== 'trash') {
      return
    }
    let cancelled = false
    void listTrashedJobs()
      .then((items) => {
        if (!cancelled) {
          setTrashJobs(items)
          setTrashError(null)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTrashError(error instanceof Error ? error.message : '回收站读取失败')
        }
      })
    return () => {
      cancelled = true
    }
  }, [jobListSegment])

  useEffect(() => {
    if (!discoveryRunId) {
      return
    }

    discoveryPollSessionRef.current += 1
    const pollSession = discoveryPollSessionRef.current
    let cancelled = false
    let timerId: number | undefined

    const scheduleNextPoll = () => {
      timerId = window.setTimeout(() => {
        void syncDiscoveryRun()
      }, 1000)
    }

    const syncDiscoveryRun = async () => {
      try {
        const nextStatus = await getDiscoveryRun(discoveryRunId)
        if (cancelled || pollSession !== discoveryPollSessionRef.current) {
          return
        }

        setDiscoveryStatus(nextStatus)
        setDiscoveryStats(nextStatus.completed || Object.keys(nextStatus.stats ?? {}).length > 0 ? nextStatus.stats : null)
        if (nextStatus.error_message) {
          setDiscoveryError(nextStatus.error_message)
        } else {
          setDiscoveryError(null)
        }

        if (!nextStatus.completed) {
          scheduleNextPoll()
          return
        }

        setDiscoveryLoading(false)
        if (nextStatus.status !== 'succeeded') {
          setDiscoveryItems([])
          setDiscoverySelected({})
          return
        }

        const itemsResponse = await getDiscoveryItems(discoveryRunId)
        if (cancelled || pollSession !== discoveryPollSessionRef.current) {
          return
        }

        setDiscoveryItems(itemsResponse.items)
        setDiscoverySelected(Object.fromEntries(itemsResponse.items.map((item) => [item.canonical_url, !item.already_enqueued])))
      } catch (error) {
        if (!cancelled && pollSession === discoveryPollSessionRef.current) {
          setDiscoveryError(error instanceof Error ? error.message : '状态读取失败')
          scheduleNextPoll()
        }
      }
    }

    void syncDiscoveryRun()

    return () => {
      cancelled = true
      if (timerId !== undefined) {
        window.clearTimeout(timerId)
      }
    }
  }, [discoveryRunId])

  useEffect(() => {
    if (!discoveryLoginRunId) {
      return
    }

    discoveryLoginPollSessionRef.current += 1
    const pollSession = discoveryLoginPollSessionRef.current
    let cancelled = false
    let timerId: number | undefined

    const scheduleNextPoll = () => {
      timerId = window.setTimeout(() => {
        void syncDiscoveryLoginRun()
      }, 1000)
    }

    const syncDiscoveryLoginRun = async () => {
      try {
        const nextStatus = await getDiscoveryLoginRun(discoveryLoginRunId)
        if (cancelled || pollSession !== discoveryLoginPollSessionRef.current) {
          return
        }

        setDiscoveryLoginStatus(nextStatus)
        setDiscoveryLoginLoading(false)
        if (nextStatus.status === 'succeeded') {
          setDiscoveryError(null)
        }
        if (!nextStatus.completed) {
          scheduleNextPoll()
        }
      } catch (error) {
        if (!cancelled && pollSession === discoveryLoginPollSessionRef.current) {
          setDiscoveryLoginLoading(false)
          setDiscoveryError(error instanceof Error ? error.message : '登录状态读取失败')
          scheduleNextPoll()
        }
      }
    }

    void syncDiscoveryLoginRun()

    return () => {
      cancelled = true
      if (timerId !== undefined) {
        window.clearTimeout(timerId)
      }
    }
  }, [discoveryLoginRunId])

  useEffect(() => {
    if (!discoveryDebugExpanded || !discoveryRunId) {
      return
    }

    discoveryDebugRequestRef.current += 1
    const requestId = discoveryDebugRequestRef.current
    let cancelled = false
    setDiscoveryDebugLoading(true)

    void getDiscoveryArtifactIndex(discoveryRunId)
      .then((result) => {
        if (cancelled || requestId !== discoveryDebugRequestRef.current) {
          return
        }
        setDiscoveryDebugFiles(result.files)
        setDiscoveryDebugActiveFile((current) => (current && result.files.includes(current) ? current : result.files[0] ?? null))
        setDiscoveryDebugError(null)
      })
      .catch((error) => {
        if (!cancelled && requestId === discoveryDebugRequestRef.current) {
          setDiscoveryDebugError(error instanceof Error ? error.message : '调试文件列表读取失败')
        }
      })
      .finally(() => {
        if (!cancelled && requestId === discoveryDebugRequestRef.current) {
          setDiscoveryDebugLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [discoveryDebugExpanded, discoveryRunId])

  useEffect(() => {
    if (!discoveryDebugExpanded || !discoveryRunId || !discoveryDebugActiveFile) {
      setDiscoveryDebugContent(null)
      return
    }

    discoveryDebugRequestRef.current += 1
    const requestId = discoveryDebugRequestRef.current
    let cancelled = false
    setDiscoveryDebugLoading(true)

    void getDiscoveryArtifactText(discoveryRunId, discoveryDebugActiveFile)
      .then((content) => {
        if (cancelled || requestId !== discoveryDebugRequestRef.current) {
          return
        }
        setDiscoveryDebugContent(content)
        setDiscoveryDebugError(null)
      })
      .catch((error) => {
        if (!cancelled && requestId === discoveryDebugRequestRef.current) {
          setDiscoveryDebugError(error instanceof Error ? error.message : '调试详情读取失败')
        }
      })
      .finally(() => {
        if (!cancelled && requestId === discoveryDebugRequestRef.current) {
          setDiscoveryDebugLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [discoveryDebugActiveFile, discoveryDebugExpanded, discoveryRunId])

  useEffect(() => {
    if (!jobId) {
      return
    }

    // 每次切换任务都开启一个新的 polling session；
    // 旧 session 即使网络请求稍后返回，也不会再回写当前页面状态。
    pollSessionRef.current += 1
    const pollSession = pollSessionRef.current
    let cancelled = false
    let timerId: number | undefined

    const scheduleNextPoll = () => {
      timerId = window.setTimeout(() => {
        void syncJob()
      }, 2000)
    }

    const syncJob = async () => {
      try {
        const nextJob = await getJob(jobId)
        if (cancelled || pollSession !== pollSessionRef.current) {
          return
        }
        if (selectedJobIdRef.current !== jobId || deletingJobIdsRef.current.has(jobId)) {
          return
        }

        setJob(nextJob)
        mergeJobIntoList(nextJob)
        setStatusError(null)
        setPollTick((current) => current + 1)

        if (!TERMINAL_STATUSES.has(nextJob.status)) {
          scheduleNextPoll()
        }
      } catch (error) {
        if (!cancelled && pollSession === pollSessionRef.current) {
          setStatusError(error instanceof Error ? error.message : '任务状态读取失败')
          scheduleNextPoll()
        }
      }
    }

    void syncJob()

    return () => {
      cancelled = true
      if (timerId !== undefined) {
        window.clearTimeout(timerId)
      }
    }
  }, [jobId, jobSyncVersion])

  useEffect(() => {
    if (job?.status !== 'running') {
      return
    }

    // Job 状态接口只会在轮询时更新；额外跑一个 1 秒定时器，
    // 让“已运行多久”这类信息在不刷新的情况下也持续跳动。
    const timerId = window.setInterval(() => {
      setNowMs(Date.now())
    }, 1000)

    return () => {
      window.clearInterval(timerId)
    }
  }, [job?.status])

  useEffect(() => {
    if (!artifactUrls) {
      setArtifactContent(null)
      setArtifactError(null)
      setArtifactLoading(false)
      return
    }

    if (!job || job.status === 'pending') {
      setArtifactContent(null)
      setArtifactError(null)
      setArtifactLoading(false)
      return
    }

    if (!isArtifactReady(job, activeArtifact)) {
      setArtifactContent(null)
      setArtifactError(null)
      setArtifactLoading(false)
      return
    }

    artifactRequestRef.current += 1
    const artifactRequestId = artifactRequestRef.current
    let cancelled = false
    setArtifactLoading(true)

    void getArtifactText(artifactUrls[activeArtifact])
      .then((content) => {
        if (cancelled || artifactRequestId !== artifactRequestRef.current) {
          return
        }

        setArtifactContent(content)
        setArtifactError(null)
      })
      .catch((error) => {
        if (!cancelled && artifactRequestId === artifactRequestRef.current) {
          setArtifactError(error instanceof Error ? error.message : '产物读取失败')
        }
      })
      .finally(() => {
        if (!cancelled && artifactRequestId === artifactRequestRef.current) {
          setArtifactLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [activeArtifact, artifactUrls, job, pollTick])

  useEffect(() => {
    if (!jobId || activeArtifact !== 'final') {
      return
    }
    if (artifactContent === null) {
      return
    }
    if (finalMarkdownLoadedJobId !== jobId || !finalMarkdownDirty) {
      setFinalMarkdownDraft(artifactContent)
      setFinalMarkdownDirty(false)
      setFinalMarkdownLoadedJobId(jobId)
    }
  }, [activeArtifact, artifactContent, finalMarkdownDirty, finalMarkdownLoadedJobId, jobId])

  useEffect(() => {
    if (!jobId) {
      setTraceFiles([])
      setTraceError(null)
      setActiveTraceFile(null)
      setTraceContent(null)
      setTraceLoading(false)
      return
    }

    if (!traceExpanded && !activeTraceFile) {
      return
    }

    let cancelled = false
    void getArtifactIndex(jobId)
      .then((payload) => {
        if (cancelled) {
          return
        }

        const files = payload.files.filter((path) => path.includes('.assets/'))
        setTraceFiles(files)
        setTraceError(null)
        setActiveTraceFile((current) => (current && files.includes(current) ? current : null))
      })
      .catch((error) => {
        if (!cancelled) {
          setTraceError(error instanceof Error ? error.message : '运行细节读取失败')
        }
      })

    return () => {
      cancelled = true
    }
  }, [activeTraceFile, jobId, pollTick, traceExpanded])

  useEffect(() => {
    if (!jobId || !activeTraceFile) {
      setTraceContent(null)
      setTraceError(null)
      setTraceLoading(false)
      return
    }

    traceRequestRef.current += 1
    const requestId = traceRequestRef.current
    let cancelled = false
    setTraceLoading(true)
    void getArtifactText(`/api/jobs/${jobId}/artifacts/${activeTraceFile}`)
      .then((content) => {
        if (cancelled || requestId !== traceRequestRef.current) {
          return
        }
        setTraceContent(content)
        setTraceError(null)
      })
      .catch((error) => {
        if (!cancelled && requestId === traceRequestRef.current) {
          setTraceError(error instanceof Error ? error.message : '运行细节读取失败')
        }
      })
      .finally(() => {
        if (!cancelled && requestId === traceRequestRef.current) {
          setTraceLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [activeTraceFile, jobId])

  const htmlPreviewReady = Boolean(jobId)

  const htmlPreviewStageOptions = useMemo(
    () => STAGE_ORDER.map((stage) => ({ value: stage, label: STAGE_LABELS[stage] })),
    [],
  )

  const htmlPreviewStageLabel = STAGE_LABELS[htmlPreviewStage]

  const handleGenerateHtmlPreview = async () => {
    if (!jobId || htmlPreviewBusy) {
      return
    }

    setHtmlPreviewBusy(true)
    setHtmlPreviewError(null)
    try {
      const result = await generateStageHtmlPreview(jobId, { stage: htmlPreviewStage })
      setHtmlPreviewUrl(`/api/jobs/${jobId}/artifacts/${result.artifact_path}`)
      setHtmlPreviewExpanded(true)
    } catch (error) {
      setHtmlPreviewError(error instanceof Error ? error.message : '生成 HTML 预览失败')
    } finally {
      setHtmlPreviewBusy(false)
    }
  }

  const handleWeChatPublishDraft = async () => {
    if (!jobId) {
      return
    }
    if (wechatPublishBusy) {
      return
    }

    setWeChatPublishBusy(true)
    setWeChatPublishError(null)
    setWeChatPublishMessage('正在启动发布：将打开公众号后台，请在弹出的浏览器中完成登录')
    try {
      const accepted = await startWeChatPublish({ job_id: jobId, html_artifact: '11-wechat.html' })
      setWeChatPublishRunId(accepted.run_id)
    } catch (error) {
      setWeChatPublishError(error instanceof Error ? error.message : '启动公众号发布失败')
      setWeChatPublishBusy(false)
    }
  }

  const resetRetryArtifacts = () => {
    setRetryError(null)
    setStatusError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setArtifactLoading(false)
    artifactRequestRef.current += 1
  }

  const parseCommaList = (value: string): string[] =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)

  const discoveryKeywordPresetSelection = useMemo(
    () => new Set(parseCommaList(discoveryKeywords).map((item) => item.toLowerCase())),
    [discoveryKeywords],
  )

  const handleToggleDiscoveryKeywordPreset = (preset: string) => {
    setDiscoveryKeywords((current) => {
      const tokens = parseCommaList(current)
      const presetKey = preset.toLowerCase()
      const nextTokens = tokens.some((token) => token.toLowerCase() === presetKey)
        ? tokens.filter((token) => token.toLowerCase() !== presetKey)
        : [...tokens, preset]
      return nextTokens.join(', ')
    })
  }

  const resetDiscoveryDebug = () => {
    setDiscoveryDebugExpanded(false)
    setDiscoveryDebugFiles([])
    setDiscoveryDebugActiveFile(null)
    setDiscoveryDebugContent(null)
    setDiscoveryDebugLoading(false)
    setDiscoveryDebugError(null)
    discoveryDebugRequestRef.current += 1
  }

  const handleDiscoveryPreview = async () => {
    const accounts = parseCommaList(discoveryAccounts)
    const keywords = parseCommaList(discoveryKeywords)
    const requiredKeywords = parseCommaList(discoveryRequiredKeywords)

    if (accounts.length === 0 && keywords.length === 0 && !discoveryIncludeRecommendations) {
      setDiscoveryError('请至少填写一个账号、关键词，或勾选推荐流。')
      return
    }

    setDiscoveryLoading(true)
    setDiscoveryStopping(false)
    setDiscoveryError(null)
    setDiscoveryRunId(null)
    setDiscoveryStatus(null)
    setDiscoveryStats(null)
    setDiscoveryItems([])
    setDiscoverySelected({})
    resetDiscoveryDebug()

    try {
      const sources = [
        ...accounts.map((value) => ({ kind: 'account' as const, value })),
        ...keywords.map((value) => ({ kind: 'keyword' as const, value })),
        ...(discoveryIncludeRecommendations ? [{ kind: 'recommendation' as const, value: 'for_you' }] : []),
      ]
      const response = await previewDiscovery({
        sources,
        max_candidates: discoveryMaxCandidates,
        max_scrolls: discoveryMaxScrolls,
        search_mode: 'top',
        min_likes: discoveryMinLikes,
        required_keywords: requiredKeywords,
      })
      setDiscoveryRunId(response.run_id)
      setDiscoveryStatus({
        run_id: response.run_id,
        status: response.status,
        current_phase: null,
        progress_message: '正在准备 discovery 请求',
        progress_json: {},
        stats: {},
        error_message: null,
        completed: false,
      })
    } catch (error) {
      setDiscoveryError(error instanceof Error ? error.message : '预览失败')
      setDiscoveryLoading(false)
    }
  }

  const handleStopDiscoveryPreview = async () => {
    if (!discoveryRunId || discoveryStopping) {
      return
    }

    setDiscoveryStopping(true)
    setDiscoveryError(null)
    try {
      const stopped = await stopDiscoveryRun(discoveryRunId)
      setDiscoveryStatus(stopped)
      setDiscoveryStats(stopped.stats)
      setDiscoveryLoading(false)
      setDiscoveryItems([])
      setDiscoverySelected({})
    } catch (error) {
      setDiscoveryError(error instanceof Error ? error.message : '停止预览失败')
    } finally {
      setDiscoveryStopping(false)
    }
  }

  const handleDiscoveryEnqueue = async () => {
    if (!discoveryRunId) {
      setDiscoveryError('请先预览候选，再入队。')
      return
    }
    const selectedUrls = Object.entries(discoverySelected)
      .filter(([, checked]) => checked)
      .map(([url]) => url)
    if (selectedUrls.length === 0) {
      setDiscoveryError('请至少勾选一条候选再入队。')
      return
    }

    setDiscoveryEnqueueLoading(true)
    setDiscoveryError(null)
    try {
      const response = await enqueueDiscovery({ run_id: discoveryRunId, selected_urls: selectedUrls, max_enqueue: 10, auto_run: true, auto_run_limit: 0 })
      // 更新 UI 状态：把已入队的标记出来
      const newlyEnqueued = new Set(response.enqueued.map((item) => item.canonical_url))
      setDiscoveryItems((current) =>
        current.map((item) =>
          newlyEnqueued.has(item.canonical_url)
            ? { ...item, already_enqueued: true, job_id: response.enqueued.find((x) => x.canonical_url === item.canonical_url)?.job_id ?? item.job_id }
            : item,
        ),
      )
      setDiscoverySelected((current) => {
        const next = { ...current }
        for (const url of newlyEnqueued) {
          next[url] = false
        }
        return next
      })
      // 刷新 job 列表，让新任务可见
      const items = await listJobs()
      setJobs(items)

      const firstEnqueuedJobId = response.enqueued[0]?.job_id
      if (firstEnqueuedJobId) {
        const targetJob = items.find((item) => item.job_id === firstEnqueuedJobId)
        if (targetJob) {
          handleSelectJob(targetJob)
        } else {
          const fallbackJob: JobRecord = {
            job_id: firstEnqueuedJobId,
            url: response.enqueued[0]?.canonical_url ?? '',
            created_at: new Date().toISOString(),
            status: 'pending',
            current_stage: null,
            started_at: null,
            finished_at: null,
            stage_models: {},
            prompt_versions: {},
            stage_durations: {},
            stage_errors: {},
            stage_probes: {},
          }
          handleSelectJob(fallbackJob)
        }
      }
    } catch (error) {
      setDiscoveryError(error instanceof Error ? error.message : '入队失败')
    } finally {
      setDiscoveryEnqueueLoading(false)
    }
  }

  const handleStartDiscoveryLogin = async () => {
    setDiscoveryLoginLoading(true)
    try {
      const response = await startDiscoveryLogin()
      setDiscoveryLoginRunId(response.run_id)
      setDiscoveryLoginStatus({
        run_id: response.run_id,
        status: response.status,
        current_phase: null,
        progress_message: '正在打开 X 登录页',
        progress_json: {},
        error_message: null,
        completed: false,
      })
    } catch (error) {
      setDiscoveryLoginLoading(false)
      setDiscoveryError(error instanceof Error ? error.message : '打开登录页失败')
    }
  }

  const handleConfirmDiscoveryLogin = async () => {
    setDiscoveryError(null)
    await handleDiscoveryPreview()
  }

  const optimisticallyResetJob = (stage: StageName, currentJob: JobRecord): JobRecord => ({
    ...clearTailStageData(stage, currentJob),
    current_stage: stage,
  })

  const handleRetryFailedStage = async () => {
    if (!jobId || !job?.current_stage || job.status !== 'failed') {
      return
    }
    if (retryingJobIdsRef.current.has(jobId)) {
      return
    }

    retryRequestRef.current += 1
    const retryRequestId = retryRequestRef.current
    const targetJobId = jobId
    retryRequestByJobRef.current[targetJobId] = retryRequestId
    retryingJobIdsRef.current.add(targetJobId)
    setRetryingJobIds((current) => (current.includes(targetJobId) ? current : [...current, targetJobId]))
    resetRetryArtifacts()

    const retryStage = job.current_stage
    const failedJobSnapshot = job
    const resetJob = optimisticallyResetJob(retryStage, failedJobSnapshot)
    setJob(resetJob)
    mergeJobIntoList(resetJob)

    try {
      await retryJob(jobId, { stage: retryStage, mode: 'failed-stage' })
      const acceptedJob = markRetryAccepted(retryStage, failedJobSnapshot)
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        mergeJobIntoList(acceptedJob)
      }
      if (selectedJobIdRef.current === targetJobId && retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        setJob(acceptedJob)
        setPollTick(0)
        setJobSyncVersion((current) => current + 1)
      }
    } catch (error) {
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        mergeJobIntoList(failedJobSnapshot)
      }
      if (selectedJobIdRef.current === targetJobId && retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        setJob(failedJobSnapshot)
        setRetryError(formatRetryError(error, retryStage))
      }
    } finally {
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        delete retryRequestByJobRef.current[targetJobId]
        retryingJobIdsRef.current.delete(targetJobId)
        setRetryingJobIds((current) => current.filter((item) => item !== targetJobId))
      }
    }
  }

  const handleRetryFromStage = async () => {
    if (!jobId || !job || (job.status !== 'succeeded' && job.status !== 'failed')) {
      return
    }
    if (retryingJobIdsRef.current.has(jobId)) {
      return
    }

    retryRequestRef.current += 1
    const retryRequestId = retryRequestRef.current
    const targetJobId = jobId
    retryRequestByJobRef.current[targetJobId] = retryRequestId
    retryingJobIdsRef.current.add(targetJobId)
    setRetryingJobIds((current) => (current.includes(targetJobId) ? current : [...current, targetJobId]))
    resetRetryArtifacts()

    const retryJobSnapshot = job
    const selectedStage = retryStage
    const resetJob = optimisticallyResetJob(selectedStage, retryJobSnapshot)
    setJob(resetJob)
    mergeJobIntoList(resetJob)

    try {
      await retryJob(jobId, { stage: selectedStage, mode: 'from-stage' })
      const acceptedJob = markRetryAccepted(selectedStage, retryJobSnapshot)
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        mergeJobIntoList(acceptedJob)
      }
      if (selectedJobIdRef.current === targetJobId && retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        setJob(acceptedJob)
        setPollTick(0)
        setJobSyncVersion((current) => current + 1)
      }
    } catch (error) {
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        mergeJobIntoList(retryJobSnapshot)
      }
      if (selectedJobIdRef.current === targetJobId && retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        setJob(retryJobSnapshot)
        setRetryError(formatRetryError(error, selectedStage))
      }
    } finally {
      if (retryRequestByJobRef.current[targetJobId] === retryRequestId) {
        delete retryRequestByJobRef.current[targetJobId]
        retryingJobIdsRef.current.delete(targetJobId)
        setRetryingJobIds((current) => current.filter((item) => item !== targetJobId))
      }
    }
  }

  const handleRegenerateHtmlFromFinal = async (contentOverride?: string) => {
    if (!jobId || !job) {
      return
    }
    if (job.status === 'running') {
      return
    }
    if (finalMarkdownBusy) {
      return
    }

    setFinalMarkdownBusy(true)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    const targetJobId = jobId
    const jobSnapshot = job
    const desiredStage: StageName = 'render-html'

    try {
      const nextContent = contentOverride ?? finalMarkdownDraft
      await updateFinalMarkdown(targetJobId, nextContent)
      await retryJob(targetJobId, { stage: desiredStage, mode: 'from-stage' })
      const acceptedJob = markRetryAccepted(desiredStage, jobSnapshot)
      mergeJobIntoList(acceptedJob)
      if (selectedJobIdRef.current === targetJobId) {
        setJob(acceptedJob)
        setPollTick(0)
        setJobSyncVersion((current) => current + 1)
      }
      setFinalMarkdownDirty(false)
      setFinalMarkdownLoadedJobId(targetJobId)
      setFinalMarkdownMessage('已保存最终稿，并已触发 HTML 重新生成。')
    } catch (error) {
      setFinalMarkdownError(error instanceof Error ? error.message : '保存或重跑失败')
    } finally {
      setFinalMarkdownBusy(false)
    }
  }

  const handleOpenHtmlPreviewFromFinal = async (contentOverride?: string) => {
    if (!jobId || !job) {
      return
    }
    if (job.status === 'running' || finalMarkdownBusy) {
      return
    }

    setFinalMarkdownBusy(true)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    const targetJobId = jobId

    try {
      const nextContent = contentOverride ?? finalMarkdownDraft
      await updateFinalMarkdown(targetJobId, nextContent)
      const preview = await generateStageHtmlPreview(targetJobId, { stage: 'final-output', force: true })
      const previewUrl = `/api/jobs/${targetJobId}/artifacts/${preview.artifact_path}`

      setHtmlPreviewStage('final-output')
      setHtmlPreviewUrl(previewUrl)
      setHtmlPreviewExpanded(true)
      window.open(previewUrl, '_blank', 'noopener,noreferrer')

      setFinalMarkdownDirty(false)
      setFinalMarkdownLoadedJobId(targetJobId)
      setFinalMarkdownMessage('已保存最终稿，并已生成 HTML 预览。')
    } catch (error) {
      setFinalMarkdownError(error instanceof Error ? error.message : '保存或生成 HTML 预览失败')
    } finally {
      setFinalMarkdownBusy(false)
    }
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    setBatchSubmitMessage(null)
    setBatchSubmitError(null)
    setStatusError(null)
    setRetryError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setActiveArtifact('source')
    setArtifactPreviewExpanded(false)
    setHtmlPreviewExpanded(false)
    setFinalMarkdownDraft('')
    setFinalMarkdownDirty(false)
    setFinalMarkdownLoadedJobId(null)
    setFinalMarkdownBusy(false)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    setFinalDiffOpen(false)
    setFinalDiffBusy(false)
    setFinalDiffError(null)
    setFinalDiffSummary(null)
    setFinalDiffHunks(null)
    setFinalDiffPolishedBase(null)
    setTraceExpanded(false)
    setTraceFiles([])
    setTraceError(null)
    setActiveTraceFile(null)
    setTraceContent(null)
    setTraceLoading(false)
    setJobsError(null)
    setJob(null)
    selectedJobIdRef.current = null
    setJobId(null)
    setPollTick(0)
    setNowMs(Date.now())

    try {
      const submittedUrl = url
      const created = await createJob(url)
      const optimisticJob: JobRecord = {
        job_id: created.job_id,
        url: submittedUrl,
        created_at: new Date().toISOString(),
        status: 'pending',
        current_stage: null,
        started_at: null,
        finished_at: null,
        stage_models: {},
        prompt_versions: {},
        stage_durations: {},
        stage_errors: {},
        stage_probes: {},
      }
      mergeJobIntoList(optimisticJob)
      setJob(optimisticJob)
      selectedJobIdRef.current = created.job_id
      setJobId(created.job_id)
      await runJob(created.job_id)
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '任务提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBatchSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    setBatchSubmitMessage(null)
    setBatchSubmitError(null)
    setStatusError(null)
    setRetryError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setActiveArtifact('source')
    setArtifactPreviewExpanded(false)
    setHtmlPreviewExpanded(false)
    setFinalMarkdownDraft('')
    setFinalMarkdownDirty(false)
    setFinalMarkdownLoadedJobId(null)
    setFinalMarkdownBusy(false)
    setFinalMarkdownMessage(null)
    setFinalMarkdownError(null)

    setFinalDiffOpen(false)
    setFinalDiffBusy(false)
    setFinalDiffError(null)
    setFinalDiffSummary(null)
    setFinalDiffHunks(null)
    setFinalDiffPolishedBase(null)
    setTraceExpanded(false)
    setTraceFiles([])
    setTraceError(null)
    setActiveTraceFile(null)
    setTraceContent(null)
    setTraceLoading(false)
    setJobsError(null)
    setJob(null)
    selectedJobIdRef.current = null
    setJobId(null)
    setPollTick(0)
    setNowMs(Date.now())

    try {
      const result = await createJobsBatch({ urls_text: batchUrlsText, run: true })
      const okItems = result.items.filter((item) => item.ok && item.job_id && item.url)
      for (const item of okItems) {
        const optimisticJob: JobRecord = {
          job_id: item.job_id!,
          url: item.url!,
          created_at: new Date().toISOString(),
          status: 'pending',
          current_stage: null,
          started_at: null,
          finished_at: null,
          stage_models: {},
          prompt_versions: {},
          stage_durations: {},
          stage_errors: {},
          stage_probes: {},
        }
        mergeJobIntoList(optimisticJob)
      }

      const lastJob = okItems.length > 0 ? okItems[okItems.length - 1] : null
      if (lastJob?.job_id && lastJob.url) {
        const selected: JobRecord = {
          job_id: lastJob.job_id,
          url: lastJob.url,
          created_at: new Date().toISOString(),
          status: 'pending',
          current_stage: null,
          started_at: null,
          finished_at: null,
          stage_models: {},
          prompt_versions: {},
          stage_durations: {},
          stage_errors: {},
          stage_probes: {},
        }
        setJob(selected)
        selectedJobIdRef.current = lastJob.job_id
        setJobId(lastJob.job_id)
      }

      const invalid = result.stats.invalid
      const created = result.stats.created
      if (created > 0) {
        setBatchSubmitMessage(`已创建并开始运行 ${created} 个任务${invalid > 0 ? `，忽略 ${invalid} 行无效 URL` : ''}。`)
        setBatchUrlsText('')
      } else {
        setBatchSubmitError(invalid > 0 ? '没有可用的 URL：请检查输入格式（每行一个 tweet/article URL）。' : '没有可创建的任务。')
      }
    } catch (error) {
      setBatchSubmitError(error instanceof Error ? error.message : '批量提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <p className="eyebrow">AI workflow dashboard</p>
        <div className="page-title-row">
          <div>
            <h1 className="page-title">x-to-wechat-agent</h1>
            <p className="page-subtitle">X Article → 中文审校 → 微信公众号 HTML</p>
          </div>
        </div>
      </header>

      <div className="page-col">
          <JobForm
            value={url}
            batchValue={batchUrlsText}
            busy={submitting}
            error={submitError}
            batchError={batchSubmitError}
            batchMessage={batchSubmitMessage}
            onChange={setUrl}
            onBatchChange={setBatchUrlsText}
            onSubmit={handleSubmit}
            onBatchSubmit={handleBatchSubmit}
          />

          <section className="card">
            <h2>自动抓取 X 精品文章</h2>
            <p className="muted">从账号、关键词或推荐流自动发现 {discoveryMaxCandidates} 篇新的英文 X Article（点赞数 ≥ {discoveryMinLikes}、正文长度 ≥ 1000 字；账号来源会按关键词过滤 AI 相关，推荐流会直接筛英文文章并排除中文）。</p>
            <div className="stack">
          <label className="stack">
            <span className="muted">账号（handle，逗号分隔）</span>
            <input value={discoveryAccounts} onChange={(e) => setDiscoveryAccounts(e.target.value)} placeholder="regent0x_, hooeem" />
          </label>
          <label className="stack">
            <span className="muted">关键词（逗号分隔，建议填 AI 相关）</span>
            <input
              name="discovery-keywords"
              value={discoveryKeywords}
              onChange={(e) => setDiscoveryKeywords(e.target.value)}
              placeholder="ai, agent, 自定义关键词"
            />
            <div className="discovery-preset-row">
              {DISCOVERY_KEYWORD_PRESETS.map((preset) => {
                const selected = discoveryKeywordPresetSelection.has(preset)
                return (
                  <button
                    key={preset}
                    type="button"
                    className={selected ? 'discovery-preset-chip active' : 'discovery-preset-chip'}
                    onClick={() => handleToggleDiscoveryKeywordPreset(preset)}
                  >
                    {preset}
                  </button>
                )
              })}
            </div>
          </label>
          <label className="stack">
            <span className="muted">账号来源关键词过滤（逗号分隔）</span>
            <input value={discoveryRequiredKeywords} onChange={(e) => setDiscoveryRequiredKeywords(e.target.value)} />
          </label>
          <label className="discovery-toggle">
            <input
              type="checkbox"
              name="discovery-include-recommendations"
              className="discovery-toggle-checkbox"
              checked={discoveryIncludeRecommendations}
              onChange={(e) => setDiscoveryIncludeRecommendations(e.target.checked)}
            />
            <span className="discovery-toggle-copy">
              <span>包含我的推荐流（For You）</span>
              <span className="muted">默认开启，方便和关键词一起扫你的 feed 流。</span>
            </span>
          </label>

          <div className="retry-controls">
            <label>
              点赞阈值
              <input
                type="number"
                className="retry-select"
                value={discoveryMinLikes}
                min={0}
                onChange={(e) => setDiscoveryMinLikes(Number(e.target.value))}
              />
            </label>
            <label>
              目标新文章数
              <input
                type="number"
                className="retry-select"
                value={discoveryMaxCandidates}
                min={1}
                max={50}
                onChange={(e) => setDiscoveryMaxCandidates(Number(e.target.value))}
              />
            </label>
          </div>

          <label className="discovery-toggle" style={{ marginTop: 8 }}>
            <input
              type="checkbox"
              name="discovery-advanced"
              className="discovery-toggle-checkbox"
              checked={discoveryAdvanced}
              onChange={(e) => setDiscoveryAdvanced(e.target.checked)}
            />
            <span className="discovery-toggle-copy">
              <span>高级设置</span>
              <span className="muted">默认不需要手动设置滚动次数。</span>
            </span>
          </label>

          {discoveryAdvanced ? (
            <div className="retry-controls">
              <label>
                滚动次数
                <input
                  type="number"
                  className="retry-select"
                  value={discoveryMaxScrolls}
                  min={0}
                  max={10}
                  onChange={(e) => setDiscoveryMaxScrolls(Number(e.target.value))}
                />
              </label>
            </div>
          ) : null}

          <div className="preview-actions">
            <button type="button" onClick={() => void handleDiscoveryPreview()} disabled={discoveryLoading || discoveryEnqueueLoading || discoveryStopping}>
              {discoveryLoading ? '预览中…' : '预览候选'}
            </button>
            <button
              type="button"
              onClick={() => void handleStopDiscoveryPreview()}
              disabled={!discoveryRunId || discoveryStopping || Boolean(discoveryStatus?.completed) || (!discoveryLoading && discoveryStatus?.status !== 'running')}
            >
              {discoveryStopping ? '停止中…' : '停止预览'}
            </button>
            <button type="button" onClick={() => void handleDiscoveryEnqueue()} disabled={!discoveryRunId || discoveryEnqueueLoading || discoveryLoading}>
              {discoveryEnqueueLoading ? '入队中…' : '入队所选'}
            </button>
            {discoveryNeedsLogin || discoveryLoginStatus ? (
              <button type="button" onClick={() => void handleStartDiscoveryLogin()} disabled={discoveryLoginLoading}>
                {discoveryLoginLoading ? '打开中…' : '打开登录页'}
              </button>
            ) : null}
            {discoveryNeedsLogin || discoveryLoginStatus ? (
              <button type="button" onClick={() => void handleConfirmDiscoveryLogin()} disabled={discoveryLoading || discoveryEnqueueLoading}>
                {discoveryLoading ? '重新预览中…' : '我已登录，重新预览'}
              </button>
            ) : null}
          </div>

          {discoveryLoading ? <p className="muted">正在搜索合格新文章（最多约 5 分钟；会自动扩展关键词并排除历史重复）</p> : null}

          {discoveryStatus ? (
            <div className="discovery-status">
              {/* Compact, scannable status: summary (phase + counters) + chips + optional callout. */}
              <div className="discovery-status-summary">
                <span className="discovery-status-title">
                  状态：{formatDiscoveryPhase(discoveryStatus.current_phase, discoveryStatus.status)}
                </span>
                <span className="discovery-status-metrics">
                  候选 {discoveryCandidateStats.total} · 可入队 {discoveryCandidateStats.canEnqueue} · 已入队 {discoveryCandidateStats.alreadyEnqueued}
                </span>
              </div>

              <div className="discovery-status-chips">
                {discoveryProgress.current_source_value ? (
                  <span className="chip">
                    来源：{formatDiscoverySourceKind(discoveryProgress.current_source_kind)}
                    {discoverySourceValueLabel ? ` ${discoverySourceValueLabel}` : ''}
                  </span>
                ) : null}
                {discoveryProgress.current_query ? <span className="chip">查询：{discoveryProgress.current_query}</span> : null}
                {discoveryProgress.suspected_reason ? (
                  <span className="chip chip-mono">诊断：{discoveryProgress.suspected_reason}</span>
                ) : null}
              </div>

              {discoveryStatus.current_phase === 'searching' ? (
                <p className="muted" style={{ margin: 0 }}>
                  {formatDiscoverySearchingSummary(discoveryProgress) ?? '搜索中…'}
                </p>
              ) : null}

              {discoveryStatus.current_phase !== 'searching' && discoveryStatus.progress_message ? (
                <p className="muted" style={{ margin: 0 }}>
                  {discoveryStatus.progress_message}
                </p>
              ) : null}

              {discoveryReasonText ? (
                <div className="callout callout-info">
                  <div className="callout-title">疑似原因</div>
                  <div className="callout-body">{discoveryReasonText}</div>
                  {discoveryProgress.suspected_detail ? (
                    <div className="callout-meta">{discoveryProgress.suspected_detail}</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {discoveryError ? <p className="error">{discoveryError}</p> : null}
          {discoveryLoginStatus ? (
            <div className="stack" style={{ gap: 6 }}>
              <p className="muted">登录阶段：{formatXLoginPhase(discoveryLoginStatus.current_phase, discoveryLoginStatus.status)}</p>
              {discoveryLoginStatus.progress_message ? <p className="muted">{discoveryLoginStatus.progress_message}</p> : null}
              {discoveryLoginProgress.current_url ? <p className="muted">当前页面：{discoveryLoginProgress.current_url}</p> : null}
              {discoveryLoginProgress.storage_state_path ? <p className="muted">登录态文件：{discoveryLoginProgress.storage_state_path}</p> : null}
              {discoveryLoginStatus.error_message ? <p className="error">{discoveryLoginStatus.error_message}</p> : null}
            </div>
          ) : null}
          {discoveryStats ? (
            <p className="muted">
              本次发现：新文章={discoveryStats.returned ?? 0} / {discoveryStats.target ?? discoveryMaxCandidates}
              （可入队={discoveryStats.enqueueable ?? discoveryStats.returned ?? 0}，历史重复={discoveryStats.filtered_seen ?? discoveryStats.already_seen ?? 0}，已入队重复={discoveryStats.filtered_enqueued ?? discoveryStats.already_enqueued ?? 0}）
            </p>
          ) : null}

          {discoveryRunId ? (
            <div className="stack" style={{ gap: 8 }}>
              <button type="button" onClick={() => setDiscoveryDebugExpanded((current) => !current)}>
                查看调试详情
              </button>
              {discoveryDebugExpanded ? (
                <div className="artifact-preview" style={{ background: '#fff', color: '#0f172a' }}>
                  <div className="stack">
                    {discoveryDebugFiles.length > 0 ? (
                      <div className="preview-actions">
                        {discoveryDebugFiles.map((file) => (
                          <button key={file} type="button" onClick={() => setDiscoveryDebugActiveFile(file)} disabled={discoveryDebugActiveFile === file}>
                            {file}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {discoveryDebugLoading ? <p className="muted">调试详情加载中…</p> : null}
                    {discoveryDebugError ? <p className="error">{discoveryDebugError}</p> : null}
                    {discoveryDebugContent ? <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{discoveryDebugContent}</pre> : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {discoveryItems.length > 0 ? (
            <div className="artifact-preview" style={{ background: '#fff', color: '#0f172a' }}>
              <div className="stack">
                <label className="muted">
                  <input
                    type="checkbox"
                    checked={discoveryItems.every((item) => discoverySelected[item.canonical_url])}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setDiscoverySelected(Object.fromEntries(discoveryItems.map((item) => [item.canonical_url, checked && !item.already_enqueued])))
                    }}
                  />
                  全选未入队
                </label>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      <th align="left">选</th>
                      <th align="left">Likes</th>
                      <th align="left">URL</th>
                      <th align="left">来源</th>
                      <th align="left">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discoveryItems.map((item) => (
                      <tr key={item.canonical_url} style={{ borderTop: '1px solid #e2e8f0' }}>
                        <td>
                          <input
                            type="checkbox"
                            disabled={item.already_enqueued}
                            checked={Boolean(discoverySelected[item.canonical_url])}
                            onChange={(e) => setDiscoverySelected((current) => ({ ...current, [item.canonical_url]: e.target.checked }))}
                          />
                        </td>
                        <td>{item.likes}</td>
                        <td>
                          <a href={item.canonical_url} target="_blank" rel="noreferrer">
                            {item.canonical_url}
                          </a>
                        </td>
                        <td>
                          {item.source_kind}:{item.source_value}
                        </td>
                        <td>
                          {item.already_enqueued ? (
                            item.job_id ? (
                              <>
                                <span>{buildDiscoveryItemStatus(item, jobsById)}</span>{' '}
                                <button
                                  type="button"
                                  className="job-list-delete"
                                  onClick={() => {
                                    const target = jobsById[item.job_id ?? '']
                                    if (target) {
                                      handleSelectJob(target)
                                    }
                                  }}
                                >
                                  打开任务
                                </button>
                              </>
                            ) : (
                              '已入队'
                            )
                          ) : (
                            '可入队'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      </section>

          <section className="card">
            <h2>任务列表</h2>
            {!hasAnyJobs && !activeListError ? <p className="muted">暂无任务记录。</p> : null}
            {hasAnyJobs ? (
              <div className="job-list-toolbar">
                <label className="job-list-search">
                  <span className="muted">搜索</span>
                  <input
                    value={jobListQuery}
                    onChange={(event) => setJobListQuery(event.target.value)}
                    placeholder="按标题 / URL / job_id / 阶段搜索"
                  />
                </label>
                <div className="tabs" role="tablist" aria-label="任务筛选">
                  <button
                    type="button"
                    className={jobListSegment === 'needs_action' ? 'tab active' : 'tab'}
                    onClick={() => setJobListSegment('needs_action')}
                  >
                    需要处理（{jobListStats.needs_action}）
                  </button>
                  <button
                    type="button"
                    className={jobListSegment === 'all' ? 'tab active' : 'tab'}
                    onClick={() => setJobListSegment('all')}
                  >
                    全部（{jobListStats.all}）
                  </button>
                  <button
                    type="button"
                    className={jobListSegment === 'succeeded' ? 'tab active' : 'tab'}
                    onClick={() => setJobListSegment('succeeded')}
                  >
                    成功（{jobListStats.succeeded}）
                  </button>
                  <button
                    type="button"
                    className={jobListSegment === 'canceled' ? 'tab active' : 'tab'}
                    onClick={() => setJobListSegment('canceled')}
                  >
                    取消（{jobListStats.canceled}）
                  </button>
                  <button
                    type="button"
                    className={jobListSegment === 'trash' ? 'tab active' : 'tab'}
                    onClick={() => setJobListSegment('trash')}
                  >
                    回收站（{jobListStats.trash}）
                  </button>
                </div>
                <label className="job-list-sort">
                  <span className="muted">排序</span>
                  <select value={jobListSort} onChange={(event) => setJobListSort(event.target.value as JobListSort)}>
                    <option value="newest">最新优先</option>
                    <option value="oldest">最早优先</option>
                  </select>
                </label>
              </div>
            ) : null}
            {hasAnyJobs ? (
              <ul className="job-list">
                {visibleJobs.length === 0 ? (
                  <li className="job-list-empty">
                    <p className="muted" style={{ margin: 0 }}>
                      没有匹配的任务。
                    </p>
                  </li>
                ) : null}
                {visibleJobs.map((item) => {
                  const selectable = jobListSegment !== 'trash'
                  return (
                    <li
                      key={item.job_id}
                      className={`job-list-item${item.job_id === jobId ? ' active' : ''}`}
                      onClick={selectable ? () => handleSelectJob(item) : undefined}
                      onKeyDown={
                        selectable
                          ? (event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                handleSelectJob(item)
                              }
                            }
                          : undefined
                      }
                      role={selectable ? 'button' : undefined}
                      tabIndex={selectable ? 0 : -1}
                    >
                      <div className="job-list-header">
                        <span className="job-list-url-inline">{item.url}</span>
                        <div className="job-list-actions">
                          <span className={`status-badge status-badge-${item.status}`}>{item.status}</span>
                          <a
                            className="job-list-open"
                            href={item.url}
                            target="_blank"
                            rel="noreferrer noopener"
                            onClick={(event) => event.stopPropagation()}
                          >
                            打开原文
                          </a>
                          <button
                            type="button"
                            className="job-list-copy"
                            onClick={(event) => {
                              event.stopPropagation()
                              const text = item.job_id
                              const setCopied = () => {
                                setCopiedJobId(item.job_id)
                                if (copiedJobTimerRef.current !== null) {
                                  window.clearTimeout(copiedJobTimerRef.current)
                                }
                                copiedJobTimerRef.current = window.setTimeout(() => {
                                  setCopiedJobId((current) => (current === item.job_id ? null : current))
                                  copiedJobTimerRef.current = null
                                }, 1200)
                              }

                              const writeClipboard = async () => {
                                try {
                                  await navigator.clipboard.writeText(text)
                                  setCopied()
                                  return
                                } catch {
                                  // fallback
                                }
                                try {
                                  const textarea = document.createElement('textarea')
                                  textarea.value = text
                                  textarea.setAttribute('readonly', 'true')
                                  textarea.style.position = 'fixed'
                                  textarea.style.left = '-9999px'
                                  textarea.style.top = '0'
                                  document.body.appendChild(textarea)
                                  textarea.select()
                                  document.execCommand('copy')
                                  textarea.remove()
                                  setCopied()
                                } catch {
                                  // ignore
                                }
                              }

                              void writeClipboard()
                            }}
                            aria-label={`复制 job_id ${item.job_id}`}
                          >
                            {copiedJobId === item.job_id ? '已复制' : '复制 ID'}
                          </button>
                          {jobListSegment === 'trash' ? (
                            <button
                              type="button"
                              className="job-list-restore"
                              disabled={restoringJobIds.includes(item.job_id)}
                              onClick={(event) => {
                                event.stopPropagation()
                                void handleRestoreJob(item)
                              }}
                            >
                              {restoringJobIds.includes(item.job_id) ? '恢复中…' : '恢复'}
                            </button>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="job-list-preview"
                                disabled={!(item.status === 'succeeded' || item.status === 'published')}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  setFinalHtmlModalJob(item)
                                }}
                              >
                                预览 HTML
                              </button>
                              <button
                                type="button"
                                className="job-list-publish"
                                disabled={item.status !== 'succeeded'}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void handleMarkPublished(item)
                                }}
                              >
                                {item.status === 'published' ? '已发布' : '标记已发布'}
                              </button>
                              <button
                                type="button"
                                className="job-list-delete"
                                disabled={
                                  item.status === 'running' || deletingJobIds.includes(item.job_id) || retryingJobIds.includes(item.job_id)
                                }
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void handleDeleteJob(item)
                                }}
                              >
                                {deletingJobIds.includes(item.job_id) ? '删除中…' : '删除'}
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                      <strong className="job-list-title">{buildJobListTitle(item)}</strong>
                      <p className="job-list-meta">
                        <span className="job-list-meta-chip">{item.job_id}</span>
                        <span className="job-list-meta-chip">{buildListStageLabel(item)}</span>
                      </p>
                      {item.status === 'running' || item.status === 'failed' ? (
                        <p className="job-list-meta">{buildProgressMessage(item)}</p>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            ) : null}
            {activeListError ? <p className="error">{activeListError}</p> : null}
          </section>
          <JobStatus
            job={job}
            jobId={jobId}
            error={statusError}
            progressMessage={progressMessage}
            progressSteps={progressSteps}
            elapsedSummary={elapsedSummary}
            retryBusy={Boolean(jobId && retryingJobIds.includes(jobId))}
            retryDisabled={Boolean(jobId && (retryingJobIds.includes(jobId) || deletingJobIds.includes(jobId)))}
            retryError={retryError}
            retryStage={retryStage}
            retryStageOptions={retryStageOptions}
            onRetryStageChange={setRetryStage}
            onRetryFromStage={
              job?.status === 'succeeded' || job?.status === 'published' || job?.status === 'failed' || job?.status === 'canceled'
                ? handleRetryFromStage
                : null
            }
            onRetryFailedStage={job?.status === 'failed' && job.current_stage ? handleRetryFailedStage : null}
            stopEnabled={stopEnabled}
            stopBusy={Boolean(jobId && stoppingJobId === jobId)}
            stopError={stopError}
            onStopJob={job?.status === 'running' ? handleStopJob : null}
          />

          <ArtifactTabs
            activeKey={activeArtifact}
            content={artifactContent}
            expanded={artifactPreviewExpanded}
            jobReady={Boolean(jobId)}
            loading={artifactLoading}
            error={artifactError}
            finalEditor={
              job && activeArtifact === 'final'
                ? {
                    enabled: Boolean(jobId && job.status !== 'running'),
                    value: finalMarkdownDraft,
                    busy: finalMarkdownBusy,
                    message: finalMarkdownMessage,
                    error: finalMarkdownError,
                    diff: {
                      enabled: Boolean(jobId && job.status !== 'running'),
                      open: finalDiffOpen,
                      busy: finalDiffBusy,
                      error: finalDiffError,
                      summary: finalDiffSummary,
                      hunks: finalDiffHunks,
                      onToggleOpen: () => {
                        setFinalDiffOpen((current) => !current)
                      },
                      onLoad: () => {
                        if (!jobId || finalDiffBusy) {
                          return
                        }
                        setFinalDiffBusy(true)
                        setFinalDiffError(null)
                        setFinalDiffSummary(null)
                        const polishedUrl = `/api/jobs/${jobId}/artifacts/05-polished.md`
                        const diffUrl = `/api/jobs/${jobId}/artifacts/diff.assets/final/05-polished_vs_10-final.patch`

                        void Promise.all([getArtifactText(polishedUrl), getArtifactText(diffUrl)])
                          .then(([polished, patch]) => {
                            if (polished === null) {
                              throw new Error('轻编辑稿尚未生成，无法展示 diff。')
                            }
                            if (patch === null) {
                              throw new Error('diff 尚未生成（请先完成最终定稿阶段）。')
                            }

                            const hunks = parseUnifiedDiffToFinalView(patch)
                            const replaceCount = hunks.reduce(
                              (acc, hunk) => acc + hunk.blocks.filter((block) => block.kind === 'replace').length,
                              0,
                            )
                            const insertCount = hunks.reduce(
                              (acc, hunk) => acc + hunk.blocks.filter((block) => block.kind === 'insert').length,
                              0,
                            )
                            const deleteCount = hunks.reduce(
                              (acc, hunk) => acc + hunk.blocks.filter((block) => block.kind === 'delete').length,
                              0,
                            )
                            setFinalDiffSummary(`变更块：替换 ${replaceCount} · 新增 ${insertCount} · 删除 ${deleteCount}`)
                            setFinalDiffPolishedBase(polished)
                            setFinalDiffHunks(hunks)
                          })
                          .catch((error) => {
                            setFinalDiffError(error instanceof Error ? error.message : 'diff 读取失败')
                          })
                          .finally(() => {
                            setFinalDiffBusy(false)
                          })
                      },
                      onChoose: (id, value) => {
                        setFinalDiffHunks((current) => {
                          if (!current) {
                            return current
                          }
                          return current.map((hunk) => ({
                            ...hunk,
                            blocks: hunk.blocks.map((block) => {
                              if ('id' in block && block.id === id) {
                                if (block.kind === 'replace' && (value === 'final' || value === 'polished')) {
                                  return { ...block, choice: value }
                                }
                                if ((block.kind === 'insert' || block.kind === 'delete') && typeof value === 'boolean') {
                                  return { ...block, accepted: value }
                                }
                              }
                              return block
                            }),
                          }))
                        })
                      },
                  onSelectAllFinal: () => {
                    setFinalDiffHunks((current) =>
                      current
                        ? current.map((hunk) => ({
                            ...hunk,
                            blocks: hunk.blocks.map((block) => {
                              if (block.kind === 'replace') {
                                return { ...block, choice: 'final' }
                              }
                              if (block.kind === 'insert' || block.kind === 'delete') {
                                return { ...block, accepted: true }
                              }
                              return block
                            }),
                          }))
                        : current,
                    )
                  },
                  onSelectAllPolished: () => {
                    setFinalDiffHunks((current) =>
                      current
                        ? current.map((hunk) => ({
                            ...hunk,
                            blocks: hunk.blocks.map((block) => {
                              if (block.kind === 'replace') {
                                return { ...block, choice: 'polished' }
                              }
                              if (block.kind === 'insert' || block.kind === 'delete') {
                                return { ...block, accepted: false }
                              }
                              return block
                            }),
                          }))
                        : current,
                    )
                  },
                  onApplyToEditor: () => {
                    if (!finalDiffPolishedBase || !finalDiffHunks) {
                      return
                    }
                    const result = applyFinalDiffSelection(finalDiffPolishedBase, finalDiffHunks)
                    if (result.error) {
                      setFinalDiffError(result.error)
                      return
                    }
                    setFinalMarkdownDraft(result.content)
                    setFinalMarkdownDirty(true)
                    setFinalMarkdownMessage('已将 diff 选择应用到编辑框，请点击“保存并重新生成 HTML”。')
                    setFinalMarkdownError(null)
                  },
                  onApplyAndRegenerate: () => {
                    if (!finalDiffPolishedBase || !finalDiffHunks) {
                      return
                    }
                    if (finalMarkdownBusy) {
                      return
                    }
                    const result = applyFinalDiffSelection(finalDiffPolishedBase, finalDiffHunks)
                    if (result.error) {
                      setFinalDiffError(result.error)
                      return
                    }
                    setFinalMarkdownDraft(result.content)
                    setFinalMarkdownDirty(true)
                    setFinalMarkdownMessage('已将 diff 选择应用到编辑框，正在保存并触发 HTML 重新生成…')
                    setFinalMarkdownError(null)
                    void handleRegenerateHtmlFromFinal(result.content)
                  },
                },
                onChange: (value) => {
                  setFinalMarkdownDraft(value)
                  setFinalMarkdownDirty(true)
                  setFinalMarkdownMessage(null)
                  setFinalMarkdownError(null)
                },
                onRegenerateHtml: () => {
                  void handleRegenerateHtmlFromFinal()
                },
                onOpenHtmlPreview: () => {
                  void handleOpenHtmlPreviewFromFinal()
                },
              }
            : null
        }
        onSelect={setActiveArtifact}
        onToggleExpanded={() => setArtifactPreviewExpanded((current) => !current)}
      />

      <section className="card" hidden>
        <div className="preview-header">
          <h2>运行细节</h2>
          <button
            type="button"
            className="preview-toggle"
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((current) => !current)}
          >
            {traceExpanded ? '收起' : '展开'}
          </button>
        </div>
        {!traceExpanded ? <p className="muted">用于排查：每次模型请求/返回、diff 等都在这里按文件列出。</p> : null}
        {traceExpanded ? (
          <div className="stack">
            {!jobId ? <p className="muted">选择任务后可查看运行细节。</p> : null}
            {jobId && traceError ? <p className="error">{traceError}</p> : null}
            {jobId ? (
              <label className="stack">
                <span className="muted">选择文件（自动只显示 *.assets 下的调试产物）</span>
                <select
                  className="retry-select"
                  value={activeTraceFile ?? ''}
                  onChange={(event) => {
                    const value = event.target.value
                    setActiveTraceFile(value ? value : null)
                  }}
                >
                  <option value="">请选择…</option>
                  {traceFiles.map((file) => (
                    <option key={file} value={file}>
                      {file}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {jobId && activeTraceFile && traceLoading ? <p className="muted">正在读取运行细节…</p> : null}
            {jobId && activeTraceFile && !traceLoading ? (
              traceContent === null ? (
                <div className="artifact-empty">该文件尚未生成或已被清理。</div>
              ) : (
                <pre className="artifact-preview">{traceContent}</pre>
              )
            ) : null}
          </div>
        ) : null}
      </section>

      <div hidden>
        <JobPrompts jobId={jobId} promptDocs={promptDocs} promptError={promptError} />
      </div>

      <HtmlPreview
        expanded={htmlPreviewExpanded}
        htmlUrl={htmlPreviewUrl}
        onToggleExpanded={() => setHtmlPreviewExpanded((current) => !current)}
        ready={htmlPreviewReady}
        stageLabel={htmlPreviewStageLabel}
        stage={htmlPreviewStage}
        stageOptions={htmlPreviewStageOptions}
        stageBusy={htmlPreviewBusy}
        stageError={htmlPreviewError}
        onStageChange={(stage) => {
          setHtmlPreviewStage(stage as StageName)
          setHtmlPreviewUrl(null)
          setHtmlPreviewError(null)
        }}
        onGenerate={() => void handleGenerateHtmlPreview()}

        publishEnabled={Boolean(jobId && job && (job.status === 'succeeded' || job.status === 'published'))}
        publishBusy={wechatPublishBusy}
        publishError={wechatPublishError}
        publishMessage={wechatPublishMessage}
        onPublish={() => void handleWeChatPublishDraft()}
      />

      {finalHtmlModalJob && finalHtmlModalUrl ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => {
            setFinalHtmlModalJob(null)
          }}
        >
          <div
            className="modal"
            ref={finalHtmlModalRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="最终 HTML 预览"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div className="modal-title">
                <div className="modal-title-text">最终 HTML 预览</div>
                <div className="modal-title-sub">{buildJobListTitle(finalHtmlModalJob)}</div>
              </div>
              <div className="modal-actions">
                <a className="modal-link" href={finalHtmlModalUrl} target="_blank" rel="noreferrer noopener">
                  新标签打开
                </a>
                <button
                  type="button"
                  className="modal-close"
                  ref={finalHtmlModalCloseRef}
                  onClick={() => {
                    setFinalHtmlModalJob(null)
                  }}
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="modal-body">
              <div className="wechat-preview modal-wechat-preview">
                <div className="wechat-device">
                  <div className="wechat-device-shell">
                    <div className="wechat-device-top">
                      <div className="wechat-device-title">微信公众号文章预览</div>
                      <div className="wechat-device-subtitle">最终产物 · {buildJobListTitle(finalHtmlModalJob)}</div>
                    </div>
                    <div className="wechat-device-screen">
                      <iframe
                        className="wechat-frame"
                        referrerPolicy="no-referrer"
                        sandbox="allow-same-origin"
                        src={finalHtmlModalUrl}
                        title="最终 HTML 预览"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      </div>
    </main>
  )
}

function stageIndex(stage: string | null): number {
  if (!stage) {
    return -1
  }

  return STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number])
}

function buildProgressSteps(job: JobRecord | null, nowMs: number): ProgressStep[] {
  const currentIndex = stageIndex(job?.current_stage ?? null)
  const activeStageSeconds = currentStageElapsedSeconds(job, nowMs)

  return STAGE_ORDER.map((stage, index) => {
    let status: ProgressStepStatus = 'pending'

    if (job?.status === 'succeeded' || job?.status === 'published') {
      status = 'completed'
    } else if (job?.status === 'running') {
      if (index < currentIndex) {
        status = 'completed'
      } else if (index === currentIndex) {
        status = 'active'
      }
    } else if (job?.status === 'failed') {
      if (index < currentIndex) {
        status = 'completed'
      } else if (index === currentIndex) {
        status = 'failed'
      }
    }

    return {
      key: stage,
      label: STAGE_LABELS[stage],
      status,
      detail: stageStepDetail(job, stage, status, activeStageSeconds),
    }
  })
}

function buildProgressMessage(job: JobRecord | null): string {
  if (!job) {
    return '等待选择任务。'
  }

  if (job.status === 'pending') {
    return '任务已创建，等待开始抓取原文。'
  }

  if (job.status === 'succeeded') {
    return '原文、翻译、审阅、路由判断、后处理、终检与 HTML 渲染均已完成。'
  }

  if (job.status === 'published') {
    return '任务已标记为已发布（内容已完成，可用于记录发布进度）。'
  }

  if (job.status === 'failed') {
    return failedStageMessage(job.current_stage)
  }

  if (job.status === 'canceled') {
    return '任务已停止，可在确认原因后从某个阶段重新开始。'
  }

  switch (job.current_stage) {
    case 'x-fetch':
      return '正在抓取原文，完成后会自动进入翻译。'
    case 'translate':
      return '原文已生成，正在翻译。'
    case 'review':
      return '翻译已完成，正在审阅。'
    case 'route':
      return '审阅已完成，正在判断是直出还是轻编辑。'
    case 'light-polish':
      return '路由已完成，正在执行轻编辑。'
    case 'final-check':
      return '候选终稿已生成，正在做发布前终检。'
    case 'targeted-fix':
      return '终检发现可自动修复的问题，正在做定点修复。'
    case 'final-output':
      return '修复已完成，正在整理最终 Markdown 定稿。'
    case 'render-html':
      return '最终 Markdown 已定稿，正在渲染 HTML。'
    default:
      return '任务正在运行。'
  }
}

function buildDiscoveryItemStatus(item: DiscoveryPreviewItem, jobsById: Record<string, JobRecord>): string {
  if (!item.already_enqueued) {
    return '可入队'
  }

  if (!item.job_id) {
    return '已入队'
  }

  const job = jobsById[item.job_id]
  if (!job) {
    return '已入队，等待同步状态'
  }

  switch (job.status) {
    case 'pending':
      return '已入队，等待开始'
    case 'running':
      return `进行中：${job.current_stage ? (STAGE_LABELS[job.current_stage] ?? job.current_stage) : '处理中'}`
    case 'succeeded':
      return '已完成'
    case 'published':
      return '已发布'
    case 'failed':
      return `失败：${job.current_stage ? (STAGE_LABELS[job.current_stage] ?? job.current_stage) : '未知阶段'}`
    case 'canceled':
      return '已停止'
    default:
      return '已入队'
  }
}

function formatDiscoveryPhase(phase: DiscoveryRunStatusResponse['current_phase'], status: DiscoveryRunStatusResponse['status']): string {
  if (status === 'canceled') {
    return '已停止'
  }
  if (status === 'failed') {
    return '失败'
  }
  switch (phase) {
    case 'preparing':
      return '准备请求'
    case 'searching':
      return '搜索候选'
    case 'filtering':
      return '整理结果'
    case 'completed':
      return '已完成'
    default:
      return status === 'pending' ? '等待开始' : '运行中'
  }
}

function formatDiscoverySourceKind(kind: string | null | undefined): string {
  switch (kind) {
    case 'keyword':
      return '关键词'
    case 'account':
      return '账号'
    case 'recommendation':
      return '推荐流'
    default:
      return kind || '来源'
  }
}

function formatDiscoverySearchingSummary(progress: DiscoveryRunStatusResponse['progress_json']): string | null {
  const sourceIndex = typeof progress?.source_index === 'number' ? progress.source_index : null
  const sourceTotal = typeof progress?.source_total === 'number' ? progress.source_total : null
  const currentScroll = typeof progress?.current_scroll === 'number' ? progress.current_scroll : null
  const maxScrolls = typeof progress?.max_scrolls === 'number' ? progress.max_scrolls : null

  const parts: string[] = []
  if (sourceIndex !== null && sourceTotal !== null && sourceTotal > 0) {
    parts.push(`来源 ${sourceIndex} / ${sourceTotal}`)
  }
  if (currentScroll !== null && maxScrolls !== null && maxScrolls >= 0) {
    parts.push(`滚动 ${currentScroll} / ${maxScrolls}`)
  }
  return parts.length > 0 ? `搜索中：${parts.join(' · ')}` : null
}

function formatDiscoverySuspectedReason(
  reason: string | null | undefined,
  progress: DiscoveryRunStatusResponse['progress_json'],
): string | null {
  if (!reason) {
    return null
  }

  switch (reason) {
    case 'login_required':
      if (progress.current_source_kind === 'recommendation') {
        return '推荐流需要登录态才能扫描。请点击“打开登录页”，完成登录后再点“我已登录，重新预览”。'
      }
      return '当前页疑似跳回 X 登录页。请点击“打开登录页”，完成登录后再点“我已登录，重新预览”。'
    case 'rate_limited_or_challenged':
      return 'X 侧疑似触发限流或风控挑战，本次结果不可靠。'
    case 'filtered_by_min_likes':
      return '当前页有结果，但达到点赞阈值的推文不足。可以降低点赞阈值再试。'
    case 'filtered_by_keywords':
      return '当前页有高赞推文，但没有通过关键词过滤。可以换更宽的关键词或调整账号来源关键词过滤。'
    case 'graphql_failed':
      return 'GraphQL 拉取失败，推荐流不会再退回 DOM 扫描（太不稳定）。建议先重试；若反复出现，可重新“打开登录页”刷新登录态，或改用关键词/账号来源。'
    case 'no_article_links_found':
      if (progress.current_source_kind === 'keyword') {
        return '命中的高赞推文里没有可解析的 X Article 链接，通常是关键词过宽，命中了普通推文、外部 article 链接或用户名/handle；这通常不是登录问题。'
      }
      return '命中的高赞推文里没有可解析的 X Article 链接，这通常不是登录问题。'
    case 'filtered_by_language_or_length':
      return '已找到疑似 X Article，但被“排除中文/正文长度 ≥ 1000”规则过滤掉了；可在调试详情里看 sample。'
    case 'all_duplicates':
      return '命中了一些文章，但都和之前滚动/来源重复（去重后为 0）。可以扩大关键词或提高搜索预算后再试。'
    case 'no_search_results':
      return '当前查询没有返回可扫描的结果。可以换关键词、账号或增加滚动次数。'
    case 'page_structure_unmatched':
      if (progress.current_source_kind === 'recommendation') {
        return '推荐流页面结构未命中预期 selector；常见原因是没有有效登录态（或被灰度/风控）。可先点“打开登录页”生成登录态后重试。'
      }
      return '页面结构和预期不一致，可能是 X 页面结构变动或被灰度了。'
    default:
      return reason
  }
}

function formatXLoginPhase(phase: XLoginRunStatusResponse['current_phase'], status: XLoginRunStatusResponse['status']): string {
  if (status === 'failed') {
    return '失败'
  }
  switch (phase) {
    case 'starting_browser':
      return '打开浏览器'
    case 'awaiting_login':
      return '等待登录'
    case 'saving_state':
      return '保存登录态'
    case 'completed':
      return '已完成'
    default:
      return status === 'pending' ? '等待开始' : '运行中'
  }
}

function failedStageMessage(stage: string | null): string {
  switch (stage) {
    case 'x-fetch':
      return '任务在原文抓取阶段失败，请检查抓取日志。'
    case 'translate':
      return '任务在翻译阶段失败，请检查模型输出或配置。'
    case 'review':
      return '任务在审阅阶段失败，请检查审阅提示词或输入内容。'
    case 'route':
      return '任务在路由判断阶段失败，请检查路由 JSON 输出或路由 Prompt。'
    case 'light-polish':
      return '任务在轻编辑阶段失败，请检查轻编辑输入或长度保护。'
    case 'final-check':
      return '任务在终检阶段失败，请检查终检 JSON 输出。'
    case 'targeted-fix':
      return '任务在定点修复阶段失败，请检查终检问题与修复结果。'
    case 'final-output':
      return '任务在最终定稿阶段失败，请检查最终稿清洗逻辑。'
    case 'render-html':
      return '任务在 HTML 渲染阶段失败，请检查渲染器输出。'
    default:
      return '任务执行失败，请检查阶段错误。'
  }
}

function buildListStageLabel(job: JobRecord): string {
  const label = job.current_stage
    ? STAGE_LABELS[job.current_stage as keyof typeof STAGE_LABELS] ?? job.current_stage
    : '等待开始'

  return `当前阶段：${label}`
}

function buildPromptDocs(
  job: JobRecord | null,
  promptTexts: Record<string, string>,
): PromptDoc[] {
  // Prompt 是静态文件，但文件名/模型会跟随任务元数据变化；
  // 这里在 UI 层把两部分合并，保证排查时能同时看到“用了哪个 prompt”和“跑在哪个模型上”。
  return PROMPT_STAGE_ORDER.map((stage) => ({
    stage,
    label: STAGE_LABELS[stage],
    filename: promptFilenameForStage(job, stage),
    model: job?.stage_models[stage]?.model ?? null,
    content: promptTexts[promptFilenameForStage(job, stage)] ?? 'Prompt 加载中…',
  }))
}

function promptFilenameForStage(job: JobRecord | null, stage: PromptStage): string {
  return job?.prompt_versions[stage] ?? STAGE_PROMPT_FILENAMES[stage]
}

function stageStepDetail(
  job: JobRecord | null,
  stage: (typeof STAGE_ORDER)[number],
  status: ProgressStepStatus,
  activeStageSeconds: number | null,
): string | null {
  if (!job) {
    return null
  }

  const durationSeconds = job.stage_durations[stage]
  if (status === 'completed' && typeof durationSeconds === 'number') {
    return `耗时 ${formatDuration(durationSeconds)}`
  }

  if (status === 'failed' && typeof durationSeconds === 'number') {
    return `失败前耗时 ${formatDuration(durationSeconds)}`
  }

  if (status === 'active' && activeStageSeconds !== null) {
    return activeStageSeconds >= ACTIVE_STAGE_STALE_AFTER_SECONDS
      ? `已运行较久（${formatDuration(activeStageSeconds)}），可能卡住`
      : `已运行 ${formatDuration(activeStageSeconds)}`
  }

  return null
}

function buildElapsedSummary(job: JobRecord | null, nowMs: number): string | null {
  if (!job?.started_at) {
    return null
  }

  const startedAtMs = Date.parse(job.started_at)
  if (Number.isNaN(startedAtMs)) {
    return null
  }

  const finishedAtMs = job.finished_at ? Date.parse(job.finished_at) : nowMs
  const effectiveEndMs = Number.isNaN(finishedAtMs) ? nowMs : finishedAtMs
  return formatDuration(Math.max(0, (effectiveEndMs - startedAtMs) / 1000))
}

function currentStageElapsedSeconds(job: JobRecord | null, nowMs: number): number | null {
  if (!job?.started_at || !job.current_stage) {
    return null
  }

  if (job.status === 'failed') {
    const failedDuration = job.stage_durations[job.current_stage]
    return typeof failedDuration === 'number' ? failedDuration : null
  }

  if (job.status !== 'running') {
    return null
  }

  const startedAtMs = Date.parse(job.started_at)
  if (Number.isNaN(startedAtMs)) {
    return null
  }

  const totalElapsedSeconds = Math.max(0, (nowMs - startedAtMs) / 1000)
  const currentIndex = stageIndex(job.current_stage)
  const completedSeconds = STAGE_ORDER.slice(0, Math.max(0, currentIndex)).reduce((sum, stage) => {
    const duration = job.stage_durations[stage]
    return sum + (typeof duration === 'number' ? duration : 0)
  }, 0)

  return Math.max(0, totalElapsedSeconds - completedSeconds)
}

function formatDuration(seconds: number): string {
  const normalized = Math.max(0, seconds)
  if (normalized < 60) {
    return `${normalized.toFixed(normalized < 10 ? 1 : 0)}秒`
  }

  const totalSeconds = Math.round(normalized)
  const minutes = Math.floor(totalSeconds / 60)
  const remainingSeconds = totalSeconds % 60
  if (minutes < 60) {
    return `${minutes}分${remainingSeconds}秒`
  }

  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}小时${remainingMinutes}分${remainingSeconds}秒`
}

import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, buildArtifactUrls, createJob, deleteJob, getArtifactText, getJob, getPromptText, listJobs, retryJob, runJob } from './api'
import { ArtifactTabs } from './components/ArtifactTabs'
import { HtmlPreview } from './components/HtmlPreview'
import { JobForm } from './components/JobForm'
import { JobStatus } from './components/JobStatus'
import type { ArtifactKey, JobRecord, StageName } from './types'

type PreviewArtifactKey = Exclude<ArtifactKey, 'html'>
type ProgressStepStatus = 'pending' | 'active' | 'completed' | 'failed'

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

type PromptStage = 'translate' | 'review' | 'route' | 'light-polish' | 'wechat-rewrite' | 'final-check' | 'targeted-fix'

const TERMINAL_STATUSES = new Set(['succeeded', 'failed'])
const STAGE_ORDER: StageName[] = [
  'x-fetch',
  'translate',
  'review',
  'route',
  'light-polish',
  'wechat-rewrite',
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
  'wechat-rewrite': '强改写',
  'final-check': '终检',
  'targeted-fix': '定点修复',
  'final-output': '最终定稿',
  'render-html': 'HTML 渲染',
}
const PROMPT_STAGE_ORDER: PromptStage[] = ['translate', 'review', 'route', 'light-polish', 'wechat-rewrite', 'final-check', 'targeted-fix']
const STAGE_PROMPT_FILENAMES: Record<PromptStage, string> = {
  translate: 'translate_zh.txt',
  review: 'review_zh.txt',
  route: 'route_zh.txt',
  'light-polish': 'light_polish_zh.txt',
  'wechat-rewrite': 'wechat_rewrite_zh.txt',
  'final-check': 'final_check_zh.txt',
  'targeted-fix': 'targeted_fix_zh.txt',
}
const ARTIFACT_STAGE_INDEX: Record<PreviewArtifactKey, number> = {
  source: 0,
  translation: 1,
  reviewed: 2,
  polished: 4,
  rewritten: 5,
  final: 8,
}
const ACTIVE_STAGE_STALE_AFTER_SECONDS = 30 * 60

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

function isArtifactReady(job: JobRecord | null, artifactKey: PreviewArtifactKey): boolean {
  if (!job || job.status === 'pending') {
    return false
  }

  if (job.status === 'succeeded') {
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
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobRecord | null>(null)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [deletingJobIds, setDeletingJobIds] = useState<string[]>([])
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [activeArtifact, setActiveArtifact] = useState<PreviewArtifactKey>('source')
  const [artifactPreviewExpanded, setArtifactPreviewExpanded] = useState(false)
  const [htmlPreviewExpanded, setHtmlPreviewExpanded] = useState(false)
  const [pollTick, setPollTick] = useState(0)
  const [jobSyncVersion, setJobSyncVersion] = useState(0)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [promptTexts, setPromptTexts] = useState<Record<string, string>>({})
  const [promptError, setPromptError] = useState<string | null>(null)
  const [retryingJobIds, setRetryingJobIds] = useState<string[]>([])
  const [retryError, setRetryError] = useState<string | null>(null)
  const [retryStage, setRetryStage] = useState<StageName>('render-html')
  // 轮询和产物读取都可能在用户快速切换任务/标签时“晚到”；
  // 用递增请求号拦住过期响应，避免旧数据覆盖当前选中的任务状态。
  const pollSessionRef = useRef(0)
  const artifactRequestRef = useRef(0)
  const retryRequestRef = useRef(0)
  const retryRequestByJobRef = useRef<Record<string, number>>({})
  const jobsMutationRef = useRef(0)
  const retryingJobIdsRef = useRef(new Set<string>())
  const deletingJobIdsRef = useRef(new Set<string>())
  const selectedJobIdRef = useRef<string | null>(null)

  const artifactUrls = useMemo(
    () => (jobId ? buildArtifactUrls(jobId) : null),
    [jobId],
  )

  const mergeJobIntoList = (nextJob: JobRecord) => {
    jobsMutationRef.current += 1
    setJobs((current) => {
      const remainingJobs = current.filter((item) => item.job_id !== nextJob.job_id)
      return [nextJob, ...remainingJobs].sort(
        (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
      )
    })
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
    setArtifactPreviewExpanded(false)
    setHtmlPreviewExpanded(false)
    setPollTick(0)
  }

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
        setPollTick(0)
      }
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '任务删除失败')
    } finally {
      deletingJobIdsRef.current.delete(targetJob.job_id)
      setDeletingJobIds((current) => current.filter((item) => item !== targetJob.job_id))
    }
  }

  const progressSteps = useMemo(() => buildProgressSteps(job, nowMs), [job, nowMs])
  const progressMessage = useMemo(() => buildProgressMessage(job), [job])
  const elapsedSummary = useMemo(() => buildElapsedSummary(job, nowMs), [job, nowMs])
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

    void listJobs()
      .then((items) => {
        if (!cancelled && jobsMutationRef.current === jobsMutationVersion) {
          setJobs(items)
          setJobsError(null)
        }
      })
      .catch((error) => {
        if (!cancelled && jobsMutationRef.current === jobsMutationVersion) {
          setJobsError(error instanceof Error ? '任务列表读取失败' : '任务列表读取失败')
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

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

  const htmlPreviewReady = job?.status === 'succeeded' && Boolean(artifactUrls?.html)

  const resetRetryArtifacts = () => {
    setRetryError(null)
    setStatusError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setArtifactLoading(false)
    artifactRequestRef.current += 1
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

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    setStatusError(null)
    setRetryError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setActiveArtifact('source')
    setArtifactPreviewExpanded(false)
    setHtmlPreviewExpanded(false)
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

  return (
    <main className="page">
      <header className="page-header">
        <p className="eyebrow">本地 Web UI</p>
        <h1>x-to-wechat-agent</h1>
        <p className="muted">输入 X 链接后提交任务，轮询状态并查看阶段产物与 HTML 预览。</p>
      </header>

      <JobForm
        value={url}
        busy={submitting}
        error={submitError}
        onChange={setUrl}
        onSubmit={handleSubmit}
      />

      <section className="card">
        <h2>任务列表</h2>
        {jobs.length === 0 && !jobsError ? <p className="muted">暂无任务记录。</p> : null}
        {jobs.length > 0 ? (
          <ul className="job-list">
            {jobs.map((item) => (
              <li
                key={item.job_id}
                className={`job-list-item${item.job_id === jobId ? ' active' : ''}`}
                onClick={() => handleSelectJob(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    handleSelectJob(item)
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <div className="job-list-header">
                  <strong>{item.job_id}</strong>
                  <div className="job-list-actions">
                    <span>{item.status}</span>
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
                  </div>
                </div>
                <p className="job-list-url">{item.url}</p>
                <p className="job-list-meta">{buildListStageLabel(item)}</p>
                <p className="job-list-meta">{buildProgressMessage(item)}</p>
              </li>
            ))}
          </ul>
        ) : null}
        {jobsError ? <p className="error">{jobsError}</p> : null}
      </section>

      <JobStatus
        job={job}
        jobId={jobId}
        error={statusError}
        progressMessage={progressMessage}
        progressSteps={progressSteps}
        elapsedSummary={elapsedSummary}
        promptDocs={promptDocs}
        promptError={promptError}
        retryBusy={Boolean(jobId && retryingJobIds.includes(jobId))}
        retryDisabled={Boolean(jobId && (retryingJobIds.includes(jobId) || deletingJobIds.includes(jobId)))}
        retryError={retryError}
        retryStage={retryStage}
        retryStageOptions={retryStageOptions}
        onRetryStageChange={setRetryStage}
        onRetryFromStage={job?.status === 'succeeded' || job?.status === 'failed' ? handleRetryFromStage : null}
        onRetryFailedStage={job?.status === 'failed' && job.current_stage ? handleRetryFailedStage : null}
      />

      <ArtifactTabs
        activeKey={activeArtifact}
        content={artifactContent}
        expanded={artifactPreviewExpanded}
        jobReady={Boolean(jobId)}
        loading={artifactLoading}
        error={artifactError}
        onSelect={setActiveArtifact}
        onToggleExpanded={() => setArtifactPreviewExpanded((current) => !current)}
      />

      <HtmlPreview
        expanded={htmlPreviewExpanded}
        htmlUrl={artifactUrls?.html ?? null}
        onToggleExpanded={() => setHtmlPreviewExpanded((current) => !current)}
        ready={htmlPreviewReady}
      />
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

    if (job?.status === 'succeeded') {
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

  if (job.status === 'failed') {
    return failedStageMessage(job.current_stage)
  }

  switch (job.current_stage) {
    case 'x-fetch':
      return '正在抓取原文，完成后会自动进入翻译。'
    case 'translate':
      return '原文已生成，正在翻译。'
    case 'review':
      return '翻译已完成，正在审阅。'
    case 'route':
      return '审阅已完成，正在判断是直出、轻编辑还是强改写。'
    case 'light-polish':
      return '路由已完成，正在执行轻编辑。'
    case 'wechat-rewrite':
      return '路由已完成，正在执行强改写。'
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
    case 'wechat-rewrite':
      return '任务在强改写阶段失败，请检查改写输入或长度保护。'
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

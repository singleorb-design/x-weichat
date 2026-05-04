import { useEffect, useMemo, useRef, useState } from 'react'

import { buildArtifactUrls, createJob, getArtifactText, getJob, runJob } from './api'
import { ArtifactTabs } from './components/ArtifactTabs'
import { HtmlPreview } from './components/HtmlPreview'
import { JobForm } from './components/JobForm'
import { JobStatus } from './components/JobStatus'
import type { ArtifactKey, JobRecord } from './types'

type PreviewArtifactKey = Exclude<ArtifactKey, 'html'>

const TERMINAL_STATUSES = new Set(['succeeded', 'failed'])

export default function App() {
  const [url, setUrl] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobRecord | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [artifactContent, setArtifactContent] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [activeArtifact, setActiveArtifact] = useState<PreviewArtifactKey>('source')
  const [pollTick, setPollTick] = useState(0)
  const pollSessionRef = useRef(0)
  const artifactRequestRef = useRef(0)

  const artifactUrls = useMemo(
    () => (jobId ? buildArtifactUrls(jobId) : null),
    [jobId],
  )

  useEffect(() => {
    if (!jobId) {
      return
    }

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

        setJob(nextJob)
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
  }, [jobId])

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

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    setStatusError(null)
    setArtifactError(null)
    setArtifactContent(null)
    setActiveArtifact('source')
    setJob(null)
    setJobId(null)
    setPollTick(0)

    try {
      const created = await createJob(url)
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

      <JobStatus job={job} jobId={jobId} error={statusError} />

      <ArtifactTabs
        activeKey={activeArtifact}
        content={artifactContent}
        jobReady={Boolean(jobId)}
        loading={artifactLoading}
        error={artifactError}
        onSelect={setActiveArtifact}
      />

      <HtmlPreview htmlUrl={artifactUrls?.html ?? null} ready={htmlPreviewReady} />
    </main>
  )
}

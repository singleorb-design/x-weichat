import { useEffect, useState } from 'react'

import type { JobRecord, StageName } from '../types'

interface ProgressStep {
  key: string
  label: string
  status: 'pending' | 'active' | 'completed' | 'failed'
  detail: string | null
}

interface PromptDoc {
  stage: string
  label: string
  filename: string
  model: string | null
  content: string
}

interface JobStatusProps {
  job: JobRecord | null
  jobId: string | null
  error: string | null
  progressMessage: string | null
  progressSteps: ProgressStep[]
  elapsedSummary: string | null
  retryBusy: boolean
  retryDisabled: boolean
  retryError: string | null
  retryStage: StageName
  retryStageOptions: Array<{ value: StageName; label: string }>
  onRetryStageChange: (stage: StageName) => void
  onRetryFromStage: (() => void) | null
  onRetryFailedStage: (() => void) | null
  stopEnabled: boolean
  stopBusy: boolean
  stopError: string | null
  onStopJob: (() => void) | null
}

interface JobPromptsProps {
  jobId: string | null
  promptDocs: PromptDoc[]
  promptError: string | null
}

export function JobPrompts({ jobId, promptDocs, promptError }: JobPromptsProps) {
  const [expandedPrompts, setExpandedPrompts] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setExpandedPrompts({})
  }, [jobId])

  const togglePrompt = (stage: string) => {
    setExpandedPrompts((current) => ({
      ...current,
      [stage]: !current[stage],
    }))
  }

  return (
    <section className="card">
      <h2>阶段 Prompt</h2>
      {!jobId ? <p className="muted">选择任务后将在这里展示各阶段 Prompt。</p> : null}
      {jobId ? (
        <>
          <p className="muted">默认折叠展示每个阶段的 Prompt，需要排查时再展开查看正文。</p>
          {promptError ? <p className="error">{promptError}</p> : null}
          {promptDocs.map((prompt) => {
            const expanded = Boolean(expandedPrompts[prompt.stage])
            return (
              <article key={prompt.stage} className={expanded ? 'accordion open' : 'accordion'}>
                <header className="accordion-summary">
                  <span className="accordion-title">
                    <span>{prompt.label}</span>
                    <span className="accordion-meta">{prompt.model ? `${prompt.filename} · ${prompt.model}` : prompt.filename}</span>
                  </span>
                  <button
                    type="button"
                    className="accordion-action"
                    data-prompt-stage={prompt.stage}
                    aria-expanded={expanded}
                    onClick={() => togglePrompt(prompt.stage)}
                  >
                    {expanded ? '收起' : '展开'}
                  </button>
                </header>
                {expanded ? <pre className="prompt-preview">{prompt.content}</pre> : null}
              </article>
            )
          })}
        </>
      ) : null}
    </section>
  )
}

export function JobStatus({
  job,
  jobId,
  error,
  progressMessage,
  progressSteps,
  elapsedSummary,
  retryBusy,
  retryDisabled,
  retryError,
  retryStage,
  retryStageOptions,
  onRetryStageChange,
  onRetryFromStage,
  onRetryFailedStage,
  stopEnabled,
  stopBusy,
  stopError,
  onStopJob,
}: JobStatusProps) {
  const hasStageErrors = Boolean(job?.stage_errors && Object.keys(job.stage_errors).length > 0)
  const orderedStageProbes = progressSteps
    .map((step) => {
      const probe = job?.stage_probes?.[step.key]
      return probe ? { stage: step.key, label: step.label, probe } : null
    })
    .filter((entry): entry is { stage: string; label: string; probe: NonNullable<JobRecord['stage_probes'][string]> } => entry !== null)
  const failedStageProbes = orderedStageProbes.filter(({ probe }) => probe.status === 'failed')
  const hasFailedStageProbes = failedStageProbes.length > 0
  const showFailedStageRetry = Boolean(job?.status === 'failed' && job.current_stage)
  const showAdvancedRetry = Boolean(
    job &&
      (job.status === 'succeeded' || job.status === 'published' || job.status === 'failed' || job.status === 'canceled') &&
      onRetryFromStage,
  )
  const failedStageLabel = showFailedStageRetry
    ? progressSteps.find((step) => step.key === job?.current_stage)?.label ?? job?.current_stage ?? '未知阶段'
    : null

  return (
    <>
      <section className="card">
        <h2>当前任务状态</h2>
        {!jobId ? <p className="muted">提交 URL 后将在这里显示任务进度。</p> : null}
        {jobId ? (
          <dl className="status-grid">
            <div>
              <dt>Job ID</dt>
              <dd>{jobId}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{job?.status ?? '已创建'}</dd>
            </div>
            <div>
              <dt>当前阶段</dt>
              <dd>{job?.current_stage ? progressSteps.find((step) => step.key === job.current_stage)?.label ?? job.current_stage : '等待开始'}</dd>
            </div>
            <div>
              <dt>执行耗时</dt>
              <dd>{elapsedSummary ?? '尚未开始'}</dd>
            </div>
          </dl>
        ) : null}
        {jobId ? (
          <>
            <p className="progress-summary">{progressMessage ?? '等待任务进入流水线。'}</p>
            <ol className="progress-steps">
              {progressSteps.map((step) => (
                <li key={step.key} className={`progress-step progress-step-${step.status}`}>
                  <span className="progress-step-dot" aria-hidden="true" />
                  <div className="progress-step-body">
                    <span className="progress-step-label">{step.label}</span>
                    {step.detail ? <span className="progress-step-detail">{step.detail}</span> : null}
                  </div>
                  <div className="progress-step-status">
                    <strong>
                      {step.status === 'completed'
                        ? '已完成'
                        : step.status === 'failed'
                          ? '失败'
                          : step.status === 'active'
                            ? '进行中'
                            : '未开始'}
                    </strong>
                  </div>
                </li>
              ))}
            </ol>
          </>
        ) : null}
        {error ? <p className="error">{error}</p> : null}
      </section>

      <section className="card">
        <h2>高级重跑</h2>
        {!jobId ? <p className="muted">选择任务后可在此停止任务或从指定阶段重跑。</p> : null}
        {hasStageErrors || showFailedStageRetry ? (
          <div className="error-block">
            <div className="retry-header">
              <div className="retry-header-copy">
                <strong>{showFailedStageRetry ? '任务失败' : '阶段错误'}</strong>
                {showFailedStageRetry ? <span className="retry-subtitle">失败阶段：{failedStageLabel}</span> : null}
              </div>
              {showFailedStageRetry && onRetryFailedStage ? (
                <button type="button" onClick={onRetryFailedStage} disabled={retryDisabled}>
                  {retryBusy ? '重试中…' : '重试此阶段'}
                </button>
              ) : null}
            </div>
            {showFailedStageRetry ? <p className="retry-hint">将从当前失败阶段重新开始，并继续执行后续阶段。</p> : null}
            {hasStageErrors ? (
              <div className="stage-error-list">
                {Object.entries(job!.stage_errors).map(([stage, stageError]) => (
                  <article key={stage} className="stage-error-card">
                    <header>{progressSteps.find((step) => step.key === stage)?.label ?? stage}</header>
                    {job?.stage_models[stage]?.model ? (
                      <p>
                        <strong>当前模型：</strong>
                        {job.stage_models[stage].model}
                      </p>
                    ) : null}
                    <p>
                      <strong>错误类型：</strong>
                      {stageError.error_type}
                    </p>
                    <p>
                      <strong>错误信息：</strong>
                      {stageError.message}
                    </p>
                    <p>
                      <strong>可重试：</strong>
                      {stageError.retryable ? '是' : '否'}
                    </p>
                    <p>
                      <strong>建议：</strong>
                      {stageError.suggestion}
                    </p>
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {hasFailedStageProbes ? (
          <div className="prompt-block">
            <strong>运行前模型探测结果</strong>
            <p className="muted">仅展示探测失败的阶段，便于快速定位异常模型链路。</p>
            <div className="stage-error-list">
              {failedStageProbes.map(({ stage, label, probe }) => (
                <article key={stage} className="stage-error-card">
                  <header>{`${label}探测${probe.status === 'passed' ? '通过' : '失败'}`}</header>
                  {job?.stage_models[stage]?.model ? (
                    <p>
                      <strong>当前模型：</strong>
                      {job.stage_models[stage].model}
                    </p>
                  ) : null}
                  <p>
                    <strong>探测信息：</strong>
                    {probe.message}
                  </p>
                  <p>
                    <strong>探测时间：</strong>
                    {probe.checked_at}
                  </p>
                </article>
              ))}
            </div>
          </div>
        ) : null}

        {showAdvancedRetry ? (
          <div className="retry-panel">
            <div className="retry-header">
              <strong>从指定阶段重跑</strong>
            </div>
            <p className="retry-hint">选择一个阶段后，将从该阶段重新开始，并继续执行后续阶段。</p>
            <div className="retry-controls">
              <label htmlFor="retry-stage">起始阶段</label>
              <select
                id="retry-stage"
                name="retry-stage"
                className="retry-select"
                value={retryStage}
                onChange={(event) => onRetryStageChange(event.target.value as StageName)}
                disabled={retryDisabled}
              >
                {retryStageOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button type="button" onClick={() => onRetryFromStage?.()} disabled={retryDisabled}>
                {retryBusy ? '重跑中…' : '从该阶段重跑'}
              </button>
            </div>
          </div>
        ) : null}

        {jobId && job?.status === 'running' ? (
          <div className="retry-panel">
            <div className="retry-header">
              <strong>停止任务</strong>
            </div>
            <p className="retry-hint">当任务卡住（例如超过 10 分钟无进展）时，可以先停止，再删除或重跑。</p>
            <div className="retry-controls">
              <button type="button" onClick={() => onStopJob?.()} disabled={!stopEnabled || stopBusy || !onStopJob}>
                {stopBusy ? '停止中…' : stopEnabled ? '停止任务' : '运行不足 10 分钟'}
              </button>
            </div>
            {stopError ? <p className="error">{stopError}</p> : null}
          </div>
        ) : null}

        {retryError ? <p className="error">{retryError}</p> : null}
      </section>
    </>
  )
}

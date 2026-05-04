import type { JobRecord } from '../types'

interface JobStatusProps {
  job: JobRecord | null
  jobId: string | null
  error: string | null
}

export function JobStatus({ job, jobId, error }: JobStatusProps) {
  return (
    <section className="card">
      <h2>任务状态</h2>
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
            <dd>{job?.current_stage ?? '等待开始'}</dd>
          </div>
        </dl>
      ) : null}
      {job?.stage_errors && Object.keys(job.stage_errors).length > 0 ? (
        <div className="error-block">
          <strong>阶段错误</strong>
          <ul>
            {Object.entries(job.stage_errors).map(([stage, message]) => (
              <li key={stage}>
                {stage}: {message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  )
}

import type { ArtifactKey } from '../types'

const ARTIFACT_LABELS: Array<{ key: Exclude<ArtifactKey, 'html'>; label: string }> = [
  { key: 'source', label: '原文' },
  { key: 'translation', label: '翻译稿' },
  { key: 'reviewed', label: '审校稿' },
  { key: 'wechat', label: '公众号稿' },
]

interface ArtifactTabsProps {
  activeKey: Exclude<ArtifactKey, 'html'>
  content: string | null
  jobReady: boolean
  loading: boolean
  error: string | null
  onSelect: (key: Exclude<ArtifactKey, 'html'>) => void
}

export function ArtifactTabs({
  activeKey,
  content,
  jobReady,
  loading,
  error,
  onSelect,
}: ArtifactTabsProps) {
  return (
    <section className="card">
      <h2>产物预览</h2>
      <div className="tabs" role="tablist" aria-label="产物标签">
        {ARTIFACT_LABELS.map((artifact) => (
          <button
            key={artifact.key}
            type="button"
            className={artifact.key === activeKey ? 'tab active' : 'tab'}
            onClick={() => onSelect(artifact.key)}
            disabled={!jobReady}
          >
            {artifact.label}
          </button>
        ))}
      </div>
      {!jobReady ? <p className="muted">任务运行后可在此查看各阶段产物。</p> : null}
      {jobReady && loading ? <p className="muted">正在读取产物…</p> : null}
      {jobReady && !loading && error ? <p className="error">{error}</p> : null}
      {jobReady && !loading && !error ? (
        <pre className="artifact-preview">{content ?? '该产物尚未生成。'}</pre>
      ) : null}
    </section>
  )
}

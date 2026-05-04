import { marked } from 'marked'

import type { ArtifactKey } from '../types'

const ARTIFACT_LABELS: Array<{ key: Exclude<ArtifactKey, 'html'>; label: string }> = [
  { key: 'source', label: '原文' },
  { key: 'translation', label: '翻译稿' },
  { key: 'reviewed', label: '审校稿' },
  { key: 'polished', label: '轻编辑稿' },
  { key: 'rewritten', label: '强改写稿' },
  { key: 'final', label: '最终稿' },
]

interface ArtifactTabsProps {
  activeKey: Exclude<ArtifactKey, 'html'>
  content: string | null
  expanded: boolean
  jobReady: boolean
  loading: boolean
  error: string | null
  onSelect: (key: Exclude<ArtifactKey, 'html'>) => void
  onToggleExpanded: () => void
}

function renderMarkdown(content: string): string {
  return marked.parse(content, { async: false, breaks: false, gfm: true }) as string
}

function shouldRenderMarkdown(key: Exclude<ArtifactKey, 'html'>): boolean {
  return key !== 'source'
}

export function ArtifactTabs({
  activeKey,
  content,
  expanded,
  jobReady,
  loading,
  error,
  onSelect,
  onToggleExpanded,
}: ArtifactTabsProps) {
  return (
    <section className="card">
      <div className="preview-header">
        <h2>产物预览</h2>
        <button
          type="button"
          className="preview-toggle"
          data-artifact-preview-toggle="true"
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >
          {expanded ? '收起' : '展开'}
        </button>
      </div>
      {!expanded ? <p className="muted">{jobReady ? '默认折叠，展开后可查看各阶段产物。' : '任务运行后可在此查看各阶段产物。'}</p> : null}
      {expanded ? (
        <div className="preview-body">
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
            content === null ? (
              <div className="artifact-empty">该产物尚未生成。</div>
            ) : shouldRenderMarkdown(activeKey) ? (
              <article className="artifact-markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
            ) : (
              <pre className="artifact-preview">{content}</pre>
            )
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

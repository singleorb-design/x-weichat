interface HtmlPreviewProps {
  expanded: boolean
  htmlUrl: string | null
  onToggleExpanded: () => void
  ready: boolean
}

export function HtmlPreview({ expanded, htmlUrl, onToggleExpanded, ready }: HtmlPreviewProps) {
  return (
    <section className="card">
      <div className="preview-header">
        <h2>HTML 预览</h2>
        <div className="preview-actions">
          {ready && htmlUrl && expanded ? (
            <a className="preview-link" href={htmlUrl} target="_blank" rel="noreferrer noopener">
              新标签全屏预览
            </a>
          ) : null}
          <button
            type="button"
            className="preview-toggle"
            data-html-preview-toggle="true"
            aria-expanded={expanded}
            onClick={onToggleExpanded}
          >
            {expanded ? '收起' : '展开'}
          </button>
        </div>
      </div>
      {!expanded ? <p className="muted">{ready && htmlUrl ? '默认折叠，展开后可查看 HTML 预览。' : 'HTML 产物生成完成后会显示在这里。'}</p> : null}
      {expanded ? (
        !ready || !htmlUrl ? (
          <p className="muted">HTML 产物生成完成后会显示在这里。</p>
        ) : (
          <iframe
            className="html-frame"
            referrerPolicy="no-referrer"
            sandbox="allow-same-origin"
            src={htmlUrl}
            title="HTML 预览"
          />
        )
      ) : null}
    </section>
  )
}

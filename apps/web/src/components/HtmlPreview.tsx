interface HtmlPreviewProps {
  expanded: boolean
  htmlUrl: string | null
  onToggleExpanded: () => void
  ready: boolean
  stageLabel: string
  stage: string
  stageOptions: Array<{ value: string; label: string }>
  stageBusy: boolean
  stageError: string | null
  onStageChange: (stage: string) => void
  onGenerate: () => void

  publishEnabled?: boolean
  publishBusy?: boolean
  publishError?: string | null
  publishMessage?: string | null
  onPublish?: () => void
}

export function HtmlPreview({
  expanded,
  htmlUrl,
  onToggleExpanded,
  ready,
  stageLabel,
  stage,
  stageOptions,
  stageBusy,
  stageError,
  onStageChange,
  onGenerate,
  publishEnabled = false,
  publishBusy = false,
  publishError = null,
  publishMessage = null,
  onPublish,
}: HtmlPreviewProps) {
  return (
    <section className="card">
      <div className="preview-header">
        <h2>HTML 预览</h2>
        <div className="preview-actions">
          <label className="preview-select-label" htmlFor="html-preview-stage">
            阶段
          </label>
          <select
            id="html-preview-stage"
            name="html-preview-stage"
            className="preview-select"
            value={stage}
            onChange={(event) => onStageChange(event.target.value)}
            disabled={stageBusy}
          >
            {stageOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" className="preview-generate" onClick={onGenerate} disabled={stageBusy || !ready}>
            {stageBusy ? '生成中…' : '生成预览'}
          </button>
          <button
            type="button"
            className="preview-generate"
            onClick={onPublish}
            disabled={!publishEnabled || publishBusy || stageBusy || !ready}
            title={publishEnabled ? '打开公众号后台并尝试保存草稿' : '需要先生成最终 HTML（11-wechat.html）'}
          >
            {publishBusy ? '发布中…' : '发布到公众号草稿'}
          </button>
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
      {!expanded ? (
        <p className="muted">
          {ready && htmlUrl
            ? `当前展示：${stageLabel}。默认折叠，展开后可查看 HTML 预览。`
            : '选择阶段后点击“生成预览”，HTML 会显示在这里。'}
        </p>
      ) : null}
      {stageError ? <p className="error">{stageError}</p> : null}
      {publishError ? <p className="error">{publishError}</p> : null}
      {publishMessage ? <p className="muted">{publishMessage}</p> : null}
      {expanded ? (
        !ready || !htmlUrl ? (
          <p className="muted">选择阶段后点击“生成预览”，HTML 会显示在这里。</p>
        ) : (
          <div className="wechat-preview">
            <div className="wechat-device">
              <div className="wechat-device-shell">
                <div className="wechat-device-top">
                  <div className="wechat-device-title">微信公众号文章预览</div>
                  <div className="wechat-device-subtitle">当前展示：{stageLabel}</div>
                </div>
                <div className="wechat-device-screen">
                  <iframe
                    className="wechat-frame"
                    referrerPolicy="no-referrer"
                    sandbox="allow-same-origin"
                    src={htmlUrl}
                    title="HTML 预览"
                  />
                </div>
              </div>
            </div>
          </div>
        )
      ) : null}
    </section>
  )
}

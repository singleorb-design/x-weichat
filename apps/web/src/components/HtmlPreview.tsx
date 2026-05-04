interface HtmlPreviewProps {
  htmlUrl: string | null
  ready: boolean
}

export function HtmlPreview({ htmlUrl, ready }: HtmlPreviewProps) {
  return (
    <section className="card">
      <h2>HTML 预览</h2>
      {!ready || !htmlUrl ? (
        <p className="muted">HTML 产物生成完成后会显示在这里。</p>
      ) : (
        <iframe
          className="html-frame"
          referrerPolicy="no-referrer"
          sandbox="allow-same-origin"
          src={htmlUrl}
          title="HTML 预览"
        />
      )}
    </section>
  )
}

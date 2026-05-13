interface JobFormProps {
  value: string
  batchValue?: string
  busy: boolean
  error: string | null
  batchError?: string | null
  batchMessage?: string | null
  onChange: (value: string) => void
  onBatchChange?: (value: string) => void
  onSubmit: () => void | Promise<void>
  onBatchSubmit?: () => void | Promise<void>
}

export function JobForm({
  value,
  batchValue = '',
  busy,
  error,
  batchError = null,
  batchMessage = null,
  onChange,
  onBatchChange,
  onSubmit,
  onBatchSubmit,
}: JobFormProps) {
  return (
    <section className="card">
      <h2>提交任务</h2>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault()
          void onSubmit()
        }}
      >
        <label htmlFor="url">X URL</label>
        <input
          id="url"
          name="url"
          type="url"
          placeholder="https://x.com/..."
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={busy}
          required
        />
        <button type="submit" disabled={busy || !value.trim()}>
          {busy ? '提交中…' : '开始生成'}
        </button>
        {error ? <p className="error">{error}</p> : null}
      </form>

      <div className="divider" />

      <div className="stack">
        <p className="muted">批量提交（每行一个 URL）：</p>
        <textarea
          name="urls_text"
          rows={6}
          placeholder={
            'https://x.com/meta_alchemist/status/2051264391908344283?s=12\n'
            + 'https://x.com/anatolikopadze/status/2051010118657962462?s=12\n'
            + 'https://x.com/karlmehta/status/2051346282434945129?s=12'
          }
          value={batchValue}
          onChange={(event) => onBatchChange?.(event.target.value)}
          disabled={busy}
        />
        <button
          type="button"
          disabled={busy || !batchValue.trim() || !onBatchSubmit}
          onClick={() => {
            void onBatchSubmit?.()
          }}
        >
          {busy ? '提交中…' : '批量开始生成'}
        </button>
        {batchMessage ? <p className="success">{batchMessage}</p> : null}
        {batchError ? <p className="error">{batchError}</p> : null}
      </div>
    </section>
  )
}

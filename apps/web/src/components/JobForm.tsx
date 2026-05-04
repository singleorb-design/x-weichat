interface JobFormProps {
  value: string
  busy: boolean
  error: string | null
  onChange: (value: string) => void
  onSubmit: () => void | Promise<void>
}

export function JobForm({ value, busy, error, onChange, onSubmit }: JobFormProps) {
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
    </section>
  )
}

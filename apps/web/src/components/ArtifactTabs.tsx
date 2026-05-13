import { marked } from 'marked'
import { useEffect, useMemo, useState } from 'react'

import type { ArtifactKey } from '../types'

const ARTIFACT_LABELS: Array<{ key: Exclude<ArtifactKey, 'html'>; label: string }> = [
  { key: 'source', label: '原文' },
  { key: 'translation', label: '翻译稿' },
  { key: 'reviewed', label: '审校稿' },
  { key: 'polished', label: '轻编辑稿' },
  { key: 'final', label: '最终稿' },
]

interface ArtifactTabsProps {
  activeKey: Exclude<ArtifactKey, 'html'>
  content: string | null
  expanded: boolean
  jobReady: boolean
  loading: boolean
  error: string | null
  finalEditor?: {
    enabled: boolean
    value: string
    busy: boolean
    message: string | null
    error: string | null
    diff?: {
      enabled: boolean
      open: boolean
      busy: boolean
      error: string | null
      summary: string | null
      hunks:
        | Array<{
            header: string
            blocks: Array<
              | { kind: 'context'; lines: string[] }
              | {
                  kind: 'replace'
                  id: string
                  oldLines: string[]
                  newLines: string[]
                  choice: 'final' | 'polished'
                }
              | { kind: 'insert'; id: string; lines: string[]; accepted: boolean }
              | { kind: 'delete'; id: string; lines: string[]; accepted: boolean }
            >
          }>
        | null
      onToggleOpen: () => void
      onLoad: () => void
      onChoose: (id: string, value: 'final' | 'polished' | boolean) => void
      onSelectAllFinal: () => void
      onSelectAllPolished: () => void
      onApplyToEditor: () => void
      onApplyAndRegenerate: () => void
    } | null
    onChange: (value: string) => void
    onRegenerateHtml: () => void
    onOpenHtmlPreview: () => void
  } | null
  onSelect: (key: Exclude<ArtifactKey, 'html'>) => void
  onToggleExpanded: () => void
}

function renderMarkdown(content: string): string {
  return marked.parse(content, { async: false, breaks: false, gfm: true }) as string
}

function shouldRenderMarkdown(key: Exclude<ArtifactKey, 'html'>): boolean {
  return key !== 'source'
}

function normalizeQuery(value: string): string {
  return value.trim().toLowerCase()
}

function highlightText(text: string, query: string): Array<string | { match: string }> {
  if (!query) {
    return [text]
  }
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  const parts: Array<string | { match: string }> = []

  let cursor = 0
  while (cursor < text.length) {
    const index = lower.indexOf(q, cursor)
    if (index === -1) {
      parts.push(text.slice(cursor))
      break
    }
    if (index > cursor) {
      parts.push(text.slice(cursor, index))
    }
    parts.push({ match: text.slice(index, index + q.length) })
    cursor = index + q.length
  }

  return parts
}

export function ArtifactTabs({
  activeKey,
  content,
  expanded,
  jobReady,
  loading,
  error,
  finalEditor,
  onSelect,
  onToggleExpanded,
}: ArtifactTabsProps) {
  const showFinalEditor = Boolean(expanded && activeKey === 'final' && finalEditor?.enabled)
  const showArtifactContent = !(showFinalEditor && activeKey === 'final')
  const finalDiff = finalEditor?.diff ?? null

  const [diffSearch, setDiffSearch] = useState('')
  const [diffOnlyChanges, setDiffOnlyChanges] = useState(true)
  const [diffCollapseContext, setDiffCollapseContext] = useState(true)
  const [expandedContexts, setExpandedContexts] = useState<Record<string, boolean>>({})
  const [activeChangeId, setActiveChangeId] = useState<string | null>(null)

  const normalizedDiffSearch = useMemo(() => normalizeQuery(diffSearch), [diffSearch])

  useEffect(() => {
    // diff 数据切换时重置搜索/导航状态，避免跨 job/跨 diff 复用。
    setDiffSearch('')
    setDiffOnlyChanges(true)
    setDiffCollapseContext(true)
    setExpandedContexts({})
    setActiveChangeId(null)
  }, [finalDiff?.hunks])

  const filteredHunks = useMemo(() => {
    if (!finalDiff?.hunks) {
      return null
    }

    const blockMatches = (block: NonNullable<NonNullable<typeof finalDiff>['hunks']>[number]['blocks'][number]) => {
      if (!normalizedDiffSearch) {
        return true
      }
      const haystack =
        block.kind === 'context'
          ? block.lines
          : block.kind === 'replace'
            ? [...block.oldLines, ...block.newLines]
            : block.lines
      return haystack.some((line) => line.toLowerCase().includes(normalizedDiffSearch))
    }

    return finalDiff.hunks
      .map((hunk) => {
        const blocks = hunk.blocks.filter((block) => {
          if (diffOnlyChanges && block.kind === 'context') {
            return false
          }
          return blockMatches(block)
        })
        return { ...hunk, blocks }
      })
      .filter((hunk) => hunk.blocks.length > 0)
  }, [diffOnlyChanges, finalDiff?.hunks, normalizedDiffSearch])

  const visibleChangeIds = useMemo(() => {
    if (!filteredHunks) {
      return []
    }
    const ids: string[] = []
    for (const hunk of filteredHunks) {
      for (const block of hunk.blocks) {
        if (block.kind === 'context') {
          continue
        }
        ids.push(block.id)
      }
    }
    return ids
  }, [filteredHunks])

  const activeChangeIndex = useMemo(() => {
    if (!activeChangeId) {
      return -1
    }
    return visibleChangeIds.indexOf(activeChangeId)
  }, [activeChangeId, visibleChangeIds])

  const scrollToChange = (changeId: string) => {
    setActiveChangeId(changeId)
    window.setTimeout(() => {
      const element = document.getElementById(`diff-change-${changeId}`)
      element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 0)
  }

  const goPrev = () => {
    if (visibleChangeIds.length === 0) {
      return
    }
    const nextIndex = activeChangeIndex <= 0 ? 0 : activeChangeIndex - 1
    scrollToChange(visibleChangeIds[nextIndex])
  }

  const goNext = () => {
    if (visibleChangeIds.length === 0) {
      return
    }
    const nextIndex = activeChangeIndex === -1 ? 0 : Math.min(visibleChangeIds.length - 1, activeChangeIndex + 1)
    scrollToChange(visibleChangeIds[nextIndex])
  }

  const renderDiffText = (text: string) => (
    <span className="diff-text">
      {highlightText(text, normalizedDiffSearch).map((part, index) =>
        typeof part === 'string' ? (
          <span key={index}>{part}</span>
        ) : (
          <mark key={index} className="diff-mark">
            {part.match}
          </mark>
        ),
      )}
    </span>
  )

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
          {showFinalEditor ? (
            <div className="final-editor">
              <label className="stack">
                <span className="muted">最终稿可编辑（将保存为 `10-final.md`，可重跑最终 HTML，或直接生成最新预览并新开标签查看）</span>
                <textarea
                  className="final-markdown-editor"
                  data-final-markdown-editor="true"
                  value={finalEditor?.value ?? ''}
                  onChange={(event) => finalEditor?.onChange(event.target.value)}
                  onInput={(event) => finalEditor?.onChange((event.target as HTMLTextAreaElement).value)}
                  rows={20}
                  disabled={!finalEditor?.enabled || finalEditor?.busy}
                />
              </label>
              {finalDiff?.enabled ? (
                <div className="diff-panel">
                  <div className="diff-panel-header">
                    <div className="stack">
                      <span className="muted">逐行选择是否采用最终稿（基于轻编辑稿 vs 最终稿 diff）</span>
                      {finalDiff.summary ? <span className="muted">{finalDiff.summary}</span> : null}
                    </div>
                    <div className="preview-actions">
                      <button
                        type="button"
                        className="preview-toggle"
                        data-final-diff-toggle="true"
                        aria-expanded={finalDiff.open}
                        onClick={finalDiff.onToggleOpen}
                        disabled={!finalDiff.enabled}
                      >
                        {finalDiff.open ? '收起 diff' : '展开 diff'}
                      </button>
                    </div>
                  </div>
                  {finalDiff.open ? (
                    <div className="diff-panel-body">
                      <div className="diff-tools">
                        <label className="diff-search">
                          <span className="muted">查找</span>
                          <input
                            value={diffSearch}
                            onChange={(event) => setDiffSearch(event.target.value)}
                            placeholder="在 diff 中搜索关键词"
                          />
                        </label>
                        <label className="diff-toggle">
                          <input type="checkbox" checked={diffOnlyChanges} onChange={(e) => setDiffOnlyChanges(e.target.checked)} />
                          <span>仅看变更</span>
                        </label>
                        <label className="diff-toggle">
                          <input
                            type="checkbox"
                            checked={diffCollapseContext}
                            onChange={(e) => setDiffCollapseContext(e.target.checked)}
                            disabled={diffOnlyChanges}
                          />
                          <span>折叠上下文</span>
                        </label>
                        <div className="diff-nav">
                          <button type="button" className="diff-secondary" onClick={goPrev} disabled={visibleChangeIds.length === 0}>
                            上一个变更
                          </button>
                          <button type="button" className="diff-secondary" onClick={goNext} disabled={visibleChangeIds.length === 0}>
                            下一个变更
                          </button>
                          <span className="muted">{visibleChangeIds.length > 0 ? `共 ${visibleChangeIds.length} 个变更块` : '无变更块'}</span>
                        </div>
                      </div>
                      {finalDiff.error ? <p className="error">{finalDiff.error}</p> : null}
                      {!finalDiff.hunks ? (
                        <div className="diff-panel-controls">
                          <button
                            type="button"
                            data-final-diff-load="true"
                            onClick={finalDiff.onLoad}
                            disabled={finalDiff.busy}
                          >
                            {finalDiff.busy ? '读取 diff 中…' : '读取 diff'}
                          </button>
                        </div>
                      ) : (
                        <>
                          <div className="diff-panel-controls">
                            <button type="button" onClick={finalDiff.onSelectAllFinal} disabled={finalDiff.busy}>
                              全部采用最终稿
                            </button>
                            <button type="button" className="diff-secondary" onClick={finalDiff.onSelectAllPolished} disabled={finalDiff.busy}>
                              全部保留轻编辑稿
                            </button>
                            <button type="button" className="diff-secondary" onClick={finalDiff.onApplyToEditor} disabled={finalDiff.busy}>
                              应用到编辑框
                            </button>
                            <button type="button" className="diff-secondary" onClick={finalDiff.onApplyAndRegenerate} disabled={finalDiff.busy}>
                              应用并保存 + 重跑 HTML
                            </button>
                          </div>
                          <div className="diff-view">
                            {(filteredHunks ?? finalDiff.hunks).map((hunk) => (
                              <div key={hunk.header} className="diff-hunk">
                                <div className="diff-hunk-header">{hunk.header}</div>
                                <div className="diff-lines">
                                  {hunk.blocks.map((block, blockIndex) => {
                                    if (block.kind === 'context') {
                                      const contextKey = `${hunk.header}::${blockIndex}`
                                      const expanded = Boolean(expandedContexts[contextKey])
                                      const shouldCollapse = diffCollapseContext && !expanded
                                      const visibleLines = shouldCollapse ? block.lines.slice(0, 2) : block.lines
                                      const hiddenCount = shouldCollapse ? Math.max(0, block.lines.length - visibleLines.length) : 0

                                      return (
                                        <div key={contextKey} className="diff-block">
                                          {hiddenCount > 0 ? (
                                            <div className="diff-block-controls">
                                              <button
                                                type="button"
                                                className="diff-secondary"
                                                onClick={() => setExpandedContexts((current) => ({ ...current, [contextKey]: true }))}
                                              >
                                                展开上下文（+{hiddenCount} 行）
                                              </button>
                                            </div>
                                          ) : null}
                                          {visibleLines.map((line, index) => (
                                            <div key={`ctx-${index}`} className="diff-line diff-line-context">
                                              <span className="diff-prefix"> </span>
                                              {renderDiffText(line)}
                                            </div>
                                          ))}
                                        </div>
                                      )
                                    }

                                    if (block.kind === 'replace') {
                                      return (
                                        <div key={block.id} id={`diff-change-${block.id}`} className="diff-block">
                                          <div className="diff-block-controls">
                                            <label className="diff-choice">
                                              <input
                                                type="radio"
                                                name={`choice-${block.id}`}
                                                checked={block.choice === 'final'}
                                                onChange={() => finalDiff.onChoose(block.id, 'final')}
                                              />
                                              <span>采用最终</span>
                                            </label>
                                            <label className="diff-choice">
                                              <input
                                                type="radio"
                                                name={`choice-${block.id}`}
                                                checked={block.choice === 'polished'}
                                                onChange={() => finalDiff.onChoose(block.id, 'polished')}
                                              />
                                              <span>保留轻编辑</span>
                                            </label>
                                          </div>
                                          {block.oldLines.map((line, index) => (
                                            <div key={`old-${index}`} className="diff-line diff-line-del">
                                              <span className="diff-prefix">-</span>
                                              {renderDiffText(line)}
                                            </div>
                                          ))}
                                          {block.newLines.map((line, index) => (
                                            <div key={`new-${index}`} className="diff-line diff-line-add">
                                              <span className="diff-prefix">+</span>
                                              {renderDiffText(line)}
                                            </div>
                                          ))}
                                        </div>
                                      )
                                    }

                                    if (block.kind === 'insert') {
                                      return (
                                        <div key={block.id} id={`diff-change-${block.id}`} className="diff-block">
                                          <div className="diff-block-controls">
                                            <label className="diff-choice">
                                              <input
                                                type="checkbox"
                                                checked={block.accepted}
                                                onChange={(event) => finalDiff.onChoose(block.id, event.target.checked)}
                                              />
                                              <span>采用新增行</span>
                                            </label>
                                          </div>
                                          {block.lines.map((line, index) => (
                                            <div key={`ins-${index}`} className="diff-line diff-line-add">
                                              <span className="diff-prefix">+</span>
                                              {renderDiffText(line)}
                                            </div>
                                          ))}
                                        </div>
                                      )
                                    }

                                    return (
                                      <div key={block.id} id={`diff-change-${block.id}`} className="diff-block">
                                        <div className="diff-block-controls">
                                          <label className="diff-choice">
                                            <input
                                              type="checkbox"
                                              checked={block.accepted}
                                              onChange={(event) => finalDiff.onChoose(block.id, event.target.checked)}
                                            />
                                            <span>删除该行</span>
                                          </label>
                                        </div>
                                        {block.lines.map((line, index) => (
                                          <div key={`del-${index}`} className="diff-line diff-line-del">
                                            <span className="diff-prefix">-</span>
                                            {renderDiffText(line)}
                                          </div>
                                        ))}
                                      </div>
                                    )
                                  })}
                                </div>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="retry-controls final-editor-actions">
                <button
                  type="button"
                  data-regenerate-html="true"
                  onClick={() => finalEditor?.onRegenerateHtml()}
                  disabled={!finalEditor?.enabled || finalEditor?.busy}
                >
                  {finalEditor?.busy ? '保存并重跑中…' : '保存并重新生成 HTML'}
                </button>
                <button
                  type="button"
                  className="diff-secondary"
                  data-open-html-preview="true"
                  onClick={() => finalEditor?.onOpenHtmlPreview()}
                  disabled={!finalEditor?.enabled || finalEditor?.busy}
                >
                  {finalEditor?.busy ? '生成预览中…' : '生成 HTML 并新标签预览'}
                </button>
              </div>
              {finalEditor?.message ? <p className="muted">{finalEditor.message}</p> : null}
              {finalEditor?.error ? <p className="error">{finalEditor.error}</p> : null}
            </div>
          ) : null}
          {jobReady && !loading && !error && showArtifactContent ? (
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

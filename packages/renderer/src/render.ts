import { Renderer, marked } from 'marked'

import { wechatTemplate } from './template.js'

const UNSAFE_URL_SCHEMES = ['javascript:', 'data:']

const MAC_CODE_SVG = `
  <svg xmlns="http://www.w3.org/2000/svg" version="1.1" x="0px" y="0px" width="45px" height="13px" viewBox="0 0 450 130">
    <ellipse cx="50" cy="65" rx="50" ry="52" stroke="rgb(220,60,54)" stroke-width="2" fill="rgb(237,108,96)" />
    <ellipse cx="225" cy="65" rx="50" ry="52" stroke="rgb(218,151,33)" stroke-width="2" fill="rgb(247,193,81)" />
    <ellipse cx="400" cy="65" rx="50" ry="52" stroke="rgb(27,161,37)" stroke-width="2" fill="rgb(100,200,86)" />
  </svg>
`.trim()

const URL_ENTITY_NAMES: Record<string, string> = {
  amp: '&',
  colon: ':',
}

const BLOCKQUOTE_LEADING_SPACES = '&nbsp;&nbsp;'

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function escapeHtmlAttribute(value: string): string {
  return escapeHtml(value).replaceAll('`', '&#96;')
}

function normalizeCodeLanguage(value: string | undefined): string {
  const language = value?.trim().split(/\s+/, 1)[0] ?? ''
  return /^[a-z0-9_-]+$/i.test(language) ? language : ''
}

function styledContent(styleLabel: string, content: string, tagName?: string): string {
  const tag = tagName ?? styleLabel
  const className = styleLabel.replace(/_/g, '-')
  const headingAttr = /^h\d$/.test(tag) ? ' data-heading="true"' : ''
  return `<${tag} class="${className}"${headingAttr}>${content}</${tag}>`
}

function indentBlockquoteContent(content: string): string {
  return content.replace(/<p class="p">/g, `<p class="p">${BLOCKQUOTE_LEADING_SPACES}`)
}

function decodeCodePoint(value: number, fallback: string): string {
  if (!Number.isInteger(value) || value < 0 || value > 0x10ffff) {
    return fallback
  }

  return String.fromCodePoint(value)
}

function decodeHtmlEntitiesForUrlCheck(value: string): string {
  return value.replace(/&(?:#(\d+);?|#x([\da-f]+);?|(amp|colon);?)/gi, (match, decimal, hexadecimal, named) => {
    if (decimal) {
      return decodeCodePoint(Number(decimal), match)
    }

    if (hexadecimal) {
      return decodeCodePoint(Number.parseInt(hexadecimal, 16), match)
    }

    if (named) {
      return URL_ENTITY_NAMES[named.toLowerCase()] ?? match
    }

    return match
  })
}

function hasUnsafeUrlScheme(value: string): boolean {
  let normalized = value

  for (let index = 0; index < 5; index += 1) {
    const decoded = decodeHtmlEntitiesForUrlCheck(normalized)

    if (decoded === normalized) {
      break
    }

    normalized = decoded
  }

  normalized = normalized.replace(/[\u0000-\u0020]+/g, '').toLowerCase()

  return UNSAFE_URL_SCHEMES.some((scheme) => normalized.startsWith(scheme))
}

function splitBareUrlDescription(href: string, text: string): { href: string; suffix: string } | null {
  if (href !== text || !href.includes('—')) {
    return null
  }

  const [safeHref, ...suffixParts] = href.split('—')
  if (!safeHref || suffixParts.length === 0) {
    return null
  }

  return {
    href: safeHref,
    suffix: `—${suffixParts.join('—')}`,
  }
}

function normalizeMarkdownInput(markdown: string): string {
  return markdown.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
}

function unwrapTopLevelMarkdownFence(markdown: string): string {
  // 改写阶段偶尔会把整篇文章包进 ```markdown 代码块；
  // 如果不先拆掉，渲染器会把正文当成代码块而不是文章结构来输出。
  const trimmed = markdown.trim()
  const wrappedMatch = trimmed.match(/^```(?:markdown|md)\s*\n([\s\S]*?)\n```$/i)
  if (wrappedMatch) {
    return wrappedMatch[1]
  }

  if (!/^```(?:markdown|md)\s*$/i.test(trimmed.split('\n', 1)[0] ?? '')) {
    return markdown
  }

  const withoutOpeningFence = trimmed.replace(/^```(?:markdown|md)\s*\n/i, '')
  if (/\n```\s*$/m.test(withoutOpeningFence)) {
    return markdown
  }

  return withoutOpeningFence.replace(/\n```\s*$/i, '')
}

function mergeAdjacentBlockquoteBlocks(markdown: string): string {
  const blocks = markdown.split(/\n{2,}/)
  const merged: string[] = []
  let pendingQuote: string | null = null

  for (const block of blocks) {
    const isQuoteBlock = block
      .split('\n')
      .filter((line) => line.trim() !== '')
      .every((line) => line.trimStart().startsWith('>'))

    if (isQuoteBlock) {
      pendingQuote = pendingQuote === null ? block : `${pendingQuote}\n>\n${block}`
      continue
    }

    if (pendingQuote !== null) {
      merged.push(pendingQuote)
      pendingQuote = null
    }
    merged.push(block)
  }

  if (pendingQuote !== null) {
    merged.push(pendingQuote)
  }

  return merged.join('\n\n')
}

function splitFrontmatter(markdown: string): { body: string; frontmatter: string | null } {
  if (!markdown.startsWith('---\n')) {
    return { body: markdown, frontmatter: null }
  }

  const frontmatterMatch = markdown.match(/^---\n([\s\S]*?)\n---(?:\n|$)/)
  if (!frontmatterMatch) {
    return { body: markdown, frontmatter: null }
  }

  return {
    frontmatter: frontmatterMatch[1],
    body: markdown.slice(frontmatterMatch[0].length).trimStart(),
  }
}

function extractTitle(frontmatter: string | null, body: string): string {
  if (frontmatter) {
    const frontmatterTitle = frontmatter.match(/^title:\s*["']?(.*?)["']?\s*$/m)?.[1]?.trim()
    if (frontmatterTitle) {
      return frontmatterTitle
    }
  }

  const headingTitle = body.match(/^#\s+(.+)$/m)?.[1]?.trim()
  return headingTitle || 'x-to-wechat-agent'
}

export function renderWechatHtml(markdown: string): string {
  const normalizedMarkdown = unwrapTopLevelMarkdownFence(normalizeMarkdownInput(markdown))
  const { body: renderableMarkdown, frontmatter } = splitFrontmatter(normalizedMarkdown)
  const mergedMarkdown = mergeAdjacentBlockquoteBlocks(renderableMarkdown)
  const title = extractTitle(frontmatter, mergedMarkdown)
  const renderer = new Renderer()
  const listOrderedStack: boolean[] = []
  const listCounters: number[] = []

  renderer.html = ({ text }) => escapeHtml(text)
  renderer.heading = ({ tokens, depth }) => {
    const text = renderer.parser.parseInline(tokens)
    const tag = `h${depth}`
    return styledContent(tag, text)
  }
  renderer.paragraph = ({ tokens }) => {
    const text = renderer.parser.parseInline(tokens)
    const isFigureImage = text.includes('<figure') && text.includes('<img')
    const isEmpty = text.trim() === ''
    if (isFigureImage || isEmpty) {
      return text
    }
    return styledContent('p', text)
  }
  renderer.blockquote = ({ tokens }) => styledContent('blockquote', indentBlockquoteContent(renderer.parser.parse(tokens)))
  renderer.link = (token) => {
    const { href, tokens } = token
    const text = renderer.parser.parseInline(tokens)
    const literalText = 'text' in token ? String(token.text) : text
    const bareUrlDescription = splitBareUrlDescription(href, literalText)
    if (bareUrlDescription) {
      if (hasUnsafeUrlScheme(bareUrlDescription.href)) {
        return escapeHtml(literalText)
      }

      const safeHref = escapeHtmlAttribute(bareUrlDescription.href)
      return `<a href="${safeHref}">${escapeHtml(bareUrlDescription.href)}</a>${escapeHtml(bareUrlDescription.suffix)}`
    }

    if (hasUnsafeUrlScheme(href)) {
      return text
    }

    return Renderer.prototype.link.call(renderer, token)
  }
  renderer.image = (token) => {
    const { href, text } = token

    if (hasUnsafeUrlScheme(href)) {
      return escapeHtml(text)
    }

    return Renderer.prototype.image.call(renderer, token)
  }
  renderer.strong = ({ tokens }) => styledContent('strong', renderer.parser.parseInline(tokens))
  renderer.em = ({ tokens }) => styledContent('em', renderer.parser.parseInline(tokens))
  renderer.code = (token) => {
    const language = normalizeCodeLanguage(token.lang)
    const classAttribute = language ? ` class="language-${escapeHtmlAttribute(language)}"` : ''
    const macSign = `<span class="mac-sign" style="padding: 10px 14px 0;">${MAC_CODE_SVG}</span>`

    return [
      '<pre class="hljs code__pre">',
      macSign,
      `<code${classAttribute}>${escapeHtml(token.text)}\n</code>`,
      '</pre>',
    ].join('')
  }
  renderer.codespan = ({ text }) => styledContent('codespan', escapeHtml(text), 'code')
  renderer.list = ({ ordered, items, start = 1 }) => {
    listOrderedStack.push(ordered)
    listCounters.push(Number(start))
    const html = items.map((item) => renderer.listitem(item)).join('')
    listOrderedStack.pop()
    listCounters.pop()
    return styledContent(ordered ? 'ol' : 'ul', html)
  }
  renderer.listitem = (token) => {
    const ordered = listOrderedStack[listOrderedStack.length - 1]
    const idx = listCounters[listCounters.length - 1] ?? 1
    listCounters[listCounters.length - 1] = idx + 1
    const prefix = ordered ? `${idx}. ` : '• '
    let content: string
    try {
      content = renderer.parser.parseInline(token.tokens)
    } catch {
      content = renderer.parser.parse(token.tokens).replace(/^<p(?:\s[^>]*)?>([\s\S]*?)<\/p>/, '$1')
    }
    return styledContent('listitem', `${prefix}${content}`, 'li')
  }
  renderer.table = ({ header, rows }) => {
    const headerRow = header
      .map((cell) => styledContent('th', renderer.parser.parseInline(cell.tokens)))
      .join('')
    const bodyRows = rows
      .map((row) => styledContent('tr', row.map((cell) => renderer.tablecell(cell)).join('')))
      .join('')
    return `
        <section style="max-width: 100%; overflow: auto">
          <table class="preview-table">
            <thead>${headerRow}</thead>
            <tbody>${bodyRows}</tbody>
          </table>
        </section>
      `
  }
  renderer.tablecell = (token) => styledContent('td', renderer.parser.parseInline(token.tokens))
  renderer.hr = () => styledContent('hr', '')

  const body = marked.parse(mergedMarkdown, {
    async: false,
    renderer,
  }) as string

  return wechatTemplate(body, title)
}

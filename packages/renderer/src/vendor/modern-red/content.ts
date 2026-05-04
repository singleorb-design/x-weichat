function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function normalizeHeadingText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

export function removeFirstHeading(html: string, title: string): string {
  const normalizedTitle = normalizeHeadingText(title)

  if (!normalizedTitle) {
    return html
  }

  const firstHeadingPattern = new RegExp(
    `^\\s*<h1>(?:${escapeRegExp(normalizedTitle)}|${escapeRegExp(normalizedTitle).replace(/ /g, '\\s+')})<\\/h1>\\s*`,
    'i',
  )

  return html.replace(firstHeadingPattern, '')
}

export function wrapModernRedContent(html: string): string {
  return `<section class="container">${html}</section>`
}

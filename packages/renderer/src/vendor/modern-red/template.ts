import { MODERN_RED_STYLES } from './styles.js'

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

export function renderModernRedPage(contentHtml: string, title = 'x-to-wechat-agent'): string {
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(title)}</title>
    <style>${MODERN_RED_STYLES}</style>
  </head>
  <body>
    <div id="output">${contentHtml}</div>
  </body>
</html>`
}

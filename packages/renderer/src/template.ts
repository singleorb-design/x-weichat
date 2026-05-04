import { renderModernRedPage, wrapModernRedContent } from './vendor/modern-red/index.js'

export function wechatTemplate(body: string, title = 'x-to-wechat-agent'): string {
  return renderModernRedPage(wrapModernRedContent(body), title)
}

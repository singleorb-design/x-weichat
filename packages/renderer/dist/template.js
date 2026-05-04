import { renderModernRedPage, wrapModernRedContent } from './vendor/modern-red/index.js';
export function wechatTemplate(body, title = 'x-to-wechat-agent') {
    return renderModernRedPage(wrapModernRedContent(body), title);
}

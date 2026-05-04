import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { renderWechatHtml } from './render.js';
export { renderWechatHtml } from './render.js';
export { wechatTemplate } from './template.js';
export { MODERN_RED_ACCENT, MODERN_RED_CONTAINER_BACKGROUND, MODERN_RED_PRIMARY, MODERN_RED_QUOTE_BACKGROUND, MODERN_RED_STYLES, removeFirstHeading, renderModernRedPage, wrapModernRedContent, } from './vendor/modern-red/index.js';
export function runCli(args = process.argv.slice(2)) {
    const inputPath = args[0];
    const outputPath = args[1];
    if (!inputPath || !outputPath) {
        return;
    }
    const markdown = readFileSync(inputPath, 'utf-8');
    writeFileSync(outputPath, renderWechatHtml(markdown), 'utf-8');
}
const entryPath = process.argv[1];
if (entryPath && import.meta.url === pathToFileURL(entryPath).href) {
    runCli();
}

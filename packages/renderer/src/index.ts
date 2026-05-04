import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

import { renderWechatHtml } from './render.js'

export { renderWechatHtml } from './render.js'
export { wechatTemplate } from './template.js'

export function runCli(args: string[] = process.argv.slice(2)): void {
  const inputPath = args[0]
  const outputPath = args[1]

  if (!inputPath || !outputPath) {
    return
  }

  const markdown = readFileSync(inputPath, 'utf-8')
  writeFileSync(outputPath, renderWechatHtml(markdown), 'utf-8')
}

const entryPath = process.argv[1]

if (entryPath && import.meta.url === pathToFileURL(entryPath).href) {
  runCli()
}

export function wechatTemplate(body) {
    return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>x-to-wechat-agent</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; padding: 24px; line-height: 1.8; }
      h1, h2, h3 { line-height: 1.4; }
      blockquote { border-left: 4px solid #ddd; padding-left: 12px; color: #666; }
    </style>
  </head>
  <body>${body}</body>
</html>`;
}

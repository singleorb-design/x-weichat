export const MODERN_RED_PRIMARY = '#A93226'
export const MODERN_RED_ACCENT = '#E4B1A0'
export const MODERN_RED_CONTAINER_BACKGROUND = 'rgba(250, 249, 245, 1)'
export const MODERN_RED_QUOTE_BACKGROUND = 'rgba(255, 255, 255, 0.6)'

const FONT_FAMILY = '-apple-system-font,BlinkMacSystemFont, Helvetica Neue, PingFang SC, Hiragino Sans GB , Microsoft YaHei UI , Microsoft YaHei ,Arial,sans-serif'

const BASE_CSS = `
section,
container {
  font-family: var(--md-font-family);
  font-size: var(--md-font-size);
  line-height: 1.75;
  text-align: left;
}

#output {
  font-family: var(--md-font-family);
  font-size: var(--md-font-size);
  line-height: 1.75;
  text-align: left;
}

blockquote {
  margin-top: 0;
  margin-right: 0;
  margin-bottom: 0;
  margin-left: 0;
}

#output section > :first-child {
  margin-top: 0 !important;
}

.mermaid-diagram .nodeLabel p {
  color: unset !important;
  letter-spacing: unset !important;
}
`.trim()

const MODERN_THEME_CSS = `
section,
container {
  font-family: var(--md-font-family);
  font-size: var(--md-font-size);
  line-height: 2;
  letter-spacing: 0px;
  font-weight: 400;
  background-color: var(--md-container-bg);
  border: 1px solid rgba(255, 255, 255, 0.01);
  border-radius: 25px;
  padding: 12px 12px;
}

#output {
  font-family: var(--md-font-family);
  font-size: var(--md-font-size);
  line-height: 2;
}

h1 {
  display: table;
  padding: 0.3em 1em;
  margin: 20px auto;
  color: #3f3f3f;
  background: var(--md-primary-color);
  border-radius: 15px;
  font-size: 28px;
  font-weight: bold;
  text-align: center;
}

h2 {
  display: block;
  padding: 0.2em 0;
  padding-bottom: 0;
  margin: 0 auto 20px;
  width: 100%;
  color: var(--md-primary-color);
  font-size: 20px;
  font-weight: bold;
  letter-spacing: 0.578px;
  line-height: 1.7;
  border-bottom: 2px solid var(--md-accent-color);
  text-align: left;
}

h3 {
  padding-left: 10px;
  border-left: 4px solid var(--md-primary-color);
  border-radius: 2px;
  margin: 0 8px 10px;
  color: #3f3f3f;
  font-size: 20px;
  font-weight: bold;
  line-height: 1.2;
}

h4 {
  margin: 0 8px 10px;
  color: var(--md-primary-color);
  font-size: 16px;
  font-weight: bold;
}

h5 {
  display: inline-block;
  margin: 0 8px 10px;
  padding: 4px 12px;
  color: #3f3f3f;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgb(189, 224, 254);
  border-radius: 20px;
  font-size: 16px;
  font-weight: 500;
}

h6 {
  margin: 0 8px 10px;
  color: var(--md-primary-color);
  font-size: 16px;
  font-weight: bold;
}

p {
  margin: 20px 0;
  color: #3f3f3f;
  line-height: 2;
  letter-spacing: 0px;
  font-size: 15px;
  font-weight: 400;
  text-indent: 0;
  word-break: break-all;
}

blockquote {
  font-style: normal;
  padding: 15px 0;
  margin: 12px 0;
  border-left: 7px solid var(--md-accent-color);
  border-radius: 10px;
  color: #3f3f3f;
  background-color: var(--blockquote-background);
}

blockquote > p {
  display: block;
  font-size: 1em;
  letter-spacing: 0.1em;
  color: #3f3f3f;
  margin: 0;
  text-indent: 0;
}

pre.code__pre,
.hljs.code__pre {
  font-size: 90%;
  overflow-x: auto;
  border-radius: 10px;
  padding: 0 !important;
  line-height: 1.5;
  margin: 10px 8px;
  box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.05);
}

.hljs.code__pre > .mac-sign {
  display: flex;
}

img {
  display: block;
  max-width: 100%;
  margin: 0.1em auto 0.5em;
  border-radius: 10px;
}

ol {
  padding-left: 1em;
  margin-left: 0;
  color: #3f3f3f;
  line-height: 2;
}

ul {
  list-style: circle;
  padding-left: 1em;
  margin-left: 0;
  color: #3f3f3f;
  line-height: 2;
}

li {
  display: block;
  margin: 0.2em 8px;
  color: #3f3f3f;
}

p.footnotes {
  margin: 0.5em 8px;
  font-size: 80%;
  color: #3f3f3f;
  text-indent: 0;
}

figure {
  margin: 1.5em 8px;
  color: #3f3f3f;
}

figcaption,
.md-figcaption {
  text-align: center;
  color: #888;
  font-size: 0.8em;
}

hr {
  border-style: solid;
  border-width: 1px 0 0;
  border-color: var(--md-accent-color);
  margin: 1.5em 0;
}

code {
  font-size: 90%;
  color: #d14;
  background: rgba(27, 31, 35, 0.05);
  padding: 3px 5px;
  border-radius: 4px;
}

pre.code__pre > code,
.hljs.code__pre > code {
  display: block;
  padding: 0.5em 1em 1em;
  overflow-x: auto;
  text-indent: 0;
  color: inherit;
  background: none;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

em {
  font-style: italic;
  font-size: inherit;
}

a {
  color: var(--md-primary-color);
  text-decoration: none;
}

strong {
  color: var(--md-primary-color);
  font-weight: bold;
  font-size: inherit;
}

table {
  color: #3f3f3f;
}

thead {
  font-weight: bold;
  color: #3f3f3f;
}

th {
  border: 1px solid #dfdfdf;
  padding: 0.25em 0.5em;
  color: #3f3f3f;
  word-break: keep-all;
  background: color-mix(in srgb, var(--md-primary-color) 10%, transparent);
}

td {
  border: 1px solid #dfdfdf;
  padding: 0.25em 0.5em;
  color: #3f3f3f;
  word-break: keep-all;
}
`.trim()

const GITHUB_CODE_CSS = `
pre code.hljs {
  display: block;
  overflow-x: auto;
  padding: 1em
}
code.hljs {
  padding: 3px 5px
}
.hljs {
  color: #24292e;
  background: #ffffff
}
.hljs-doctag,
.hljs-keyword,
.hljs-meta .hljs-keyword,
.hljs-template-tag,
.hljs-template-variable,
.hljs-type,
.hljs-variable.language_ {
  color: #d73a49
}
.hljs-title,
.hljs-title.class_,
.hljs-title.class_.inherited__,
.hljs-title.function_ {
  color: #6f42c1
}
.hljs-attr,
.hljs-attribute,
.hljs-literal,
.hljs-meta,
.hljs-number,
.hljs-operator,
.hljs-variable,
.hljs-selector-attr,
.hljs-selector-class,
.hljs-selector-id {
  color: #005cc5
}
.hljs-regexp,
.hljs-string,
.hljs-meta .hljs-string {
  color: #032f62
}
.hljs-built_in,
.hljs-symbol {
  color: #e36209
}
.hljs-comment,
.hljs-code,
.hljs-formula {
  color: #6a737d
}
.hljs-name,
.hljs-quote,
.hljs-selector-tag,
.hljs-selector-pseudo {
  color: #22863a
}
.hljs-subst {
  color: #24292e
}
.hljs-section {
  color: #005cc5;
  font-weight: bold
}
.hljs-bullet {
  color: #735c0f
}
.hljs-emphasis {
  color: #24292e;
  font-style: italic
}
.hljs-strong {
  color: #24292e;
  font-weight: bold
}
.hljs-addition {
  color: #22863a;
  background-color: #f0fff4
}
.hljs-deletion {
  color: #b31d28;
  background-color: #ffeef0
}
.hljs-char.escape_,
.hljs-link,
.hljs-params,
.hljs-property,
.hljs-punctuation,
.hljs-tag {
}
`.trim()

export const MODERN_RED_STYLES = `
:root {
  --md-primary-color: ${MODERN_RED_PRIMARY};
  --md-font-family: ${FONT_FAMILY};
  --md-font-size: 15px;
  --foreground: 0 0% 25%;
  --blockquote-background: ${MODERN_RED_QUOTE_BACKGROUND};
  --md-accent-color: ${MODERN_RED_ACCENT};
  --md-container-bg: ${MODERN_RED_CONTAINER_BACKGROUND};
}

body {
  margin: 0;
  padding: 24px;
  background: #ffffff;
}

#output {
  max-width: 860px;
  margin: 0 auto;
}

${BASE_CSS}

${MODERN_THEME_CSS}

${GITHUB_CODE_CSS}
`.trim()

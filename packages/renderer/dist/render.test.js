import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWechatHtml } from './render.js';
describe('renderWechatHtml', () => {
    it('renders modern-red page structure and article elements', () => {
        const html = renderWechatHtml([
            '# 标题',
            '',
            '这是一段带有[链接](https://example.com)和**强调**的正文。',
            '',
            '## 二级标题',
            '',
            '### 三级标题',
            '',
            '> 引用内容',
            '',
            '| 列1 | 列2 |',
            '| --- | --- |',
            '| A | B |',
            '',
            '```ts',
            'const value = 1',
            '```',
        ].join('\n'));
        expect(html).toContain('<div id="output">');
        expect(html).toContain('<section class="container">');
        expect(html).toContain('#A93226');
        expect(html).toContain('<h1 class="h1" data-heading="true">标题</h1>');
        expect(html).toContain('<h2 class="h2" data-heading="true">二级标题</h2>');
        expect(html).toContain('<h3 class="h3" data-heading="true">三级标题</h3>');
        expect(html).toContain('<blockquote class="blockquote">');
        expect(html).toContain('<table class="preview-table">');
        expect(html).toContain('<pre class="hljs code__pre">');
        expect(html).toContain('<span class="mac-sign" style="padding: 10px 14px 0;">');
        expect(html).toContain('<code class="language-ts">const value = 1\n</code>');
        expect(html).toContain('<a href="https://example.com">链接</a>');
        expect(html).toContain('<strong class="strong">强调</strong>');
    });
    it('unwraps top-level markdown fences and uses frontmatter title', () => {
        const html = renderWechatHtml('```markdown\n---\ntitle: "外层标题"\n---\n\n# 正文标题\n\n正文\n```');
        expect(html).toContain('<title>外层标题</title>');
        expect(html).toContain('<h1 class="h1" data-heading="true">正文标题</h1>');
        expect(html).toContain('<p class="p">正文</p>');
        expect(html).not.toContain('<code class="language-markdown">');
        expect(html).not.toContain('title: &quot;外层标题&quot;');
    });
    it('unwraps a dangling top-level markdown fence when the closing fence is missing', () => {
        const html = renderWechatHtml('```markdown\n---\ntitle: "外层标题"\n---\n\n# 正文标题\n\n正文');
        expect(html).toContain('<title>外层标题</title>');
        expect(html).toContain('<h1 class="h1" data-heading="true">正文标题</h1>');
        expect(html).toContain('<p class="p">正文</p>');
        expect(html).not.toContain('<code class="language-markdown">');
        expect(html).not.toContain('title: &quot;外层标题&quot;');
    });
    it('does not unwrap a normal top-level fenced code block without markdown language', () => {
        const html = renderWechatHtml('```\n# 这是一段代码\n```');
        expect(html).toContain('<pre class="hljs code__pre">');
        expect(html).toContain('<span class="mac-sign" style="padding: 10px 14px 0;">');
        expect(html).toContain('<code># 这是一段代码\n</code>');
        expect(html).not.toContain('<h1>这是一段代码</h1>');
    });
    it('does not unwrap a markdown-labelled code block when it is not the entire wrapped document', () => {
        const html = renderWechatHtml('```markdown\n# 示例\n```\n\n后面还有正文说明。');
        expect(html).toContain('<pre class="hljs code__pre">');
        expect(html).toContain('<code class="language-markdown"># 示例\n</code>');
        expect(html).toContain('<p class="p">后面还有正文说明。</p>');
        expect(html).not.toContain('<h1>示例</h1>');
    });
    it('renders a full markdown-labelled CLAUDE sample as article structure instead of a code card', () => {
        const html = renderWechatHtml([
            '```markdown',
            '## CLAUDE.md',
            '',
            '## project',
            '- 技术栈：Next.js 14、TypeScript、Tailwind、Prisma 连接 PostgreSQL',
            '- 部署平台：Vercel，staging 分支自动部署',
            '- 单体仓库结构：`/apps/web`、`/apps/api`、`/packages/shared`',
            '',
            '## conventions',
            '- 所有组件名使用 PascalCase',
            '- API 路径统一返回 `{ data, error }` 格式',
            '```',
        ].join('\n'));
        expect(html).toContain('<h2 class="h2" data-heading="true">CLAUDE.md</h2>');
        expect(html).toContain('<h2 class="h2" data-heading="true">project</h2>');
        expect(html).toContain('<li class="listitem">• 技术栈：Next.js 14、TypeScript、Tailwind、Prisma 连接 PostgreSQL</li>');
        expect(html).not.toContain('<code class="language-markdown">');
        expect(html).not.toContain('## project');
    });
    it('preserves line breaks inside fenced code blocks', () => {
        const html = renderWechatHtml([
            '```',
            '## CLAUDE.md',
            '',
            '## 项目',
            '- 技术栈：Next.js 14、TypeScript、Tailwind CSS、通过 Prisma 使用 PostgreSQL',
            '- 部署在 Vercel 上，staging 分支会自动部署',
            '',
            '## 规范',
            '- 所有组件采用 PascalCase 命名',
            '```',
        ].join('\n'));
        expect(html).toContain('white-space: pre-wrap;');
        expect(html).not.toContain('white-space: nowrap;');
        expect(html).toContain('<code>## CLAUDE.md\n\n## 项目\n- 技术栈：Next.js 14、TypeScript、Tailwind CSS、通过 Prisma 使用 PostgreSQL');
        expect(html).toContain('\n## 规范\n- 所有组件采用 PascalCase 命名\n</code>');
    });
    it('uses the modern-red white Mac-style code block styling', () => {
        const html = renderWechatHtml([
            '```text',
            '社交监听提醒',
            '→ 数据库',
            '→ AI 提取痛点',
            '```',
        ].join('\n'));
        expect(html).toContain('--md-primary-color: #A93226;');
        expect(html).toContain('pre.code__pre');
        expect(html).toContain('.hljs.code__pre > .mac-sign');
        expect(html).toContain('<code class="language-text">社交监听提醒\n→ 数据库\n→ AI 提取痛点\n</code>');
    });
    it('does not apply first-line indentation to article paragraphs by default', () => {
        const html = renderWechatHtml('第一段正文。\n\n第二段正文。');
        expect(html).toContain('<p class="p">第一段正文。</p>');
        expect(html).toContain('<p class="p">第二段正文。</p>');
        expect(html).toContain('text-indent: 0;');
        expect(html).not.toContain('text-indent: 2em;');
    });
    it('supports CRLF frontmatter inside a wrapped markdown document', () => {
        const html = renderWechatHtml('```markdown\r\n---\r\ntitle: "CRLF 标题"\r\n---\r\n\r\n# 正文标题\r\n\r\n正文\r\n```');
        expect(html).toContain('<title>CRLF 标题</title>');
        expect(html).toContain('<h1 class="h1" data-heading="true">正文标题</h1>');
        expect(html).toContain('<p class="p">正文</p>');
        expect(html).not.toContain('<hr>');
        expect(html).not.toContain('title: &quot;CRLF 标题&quot;');
    });
    it('supports frontmatter closed at end of file without leaking metadata into the body', () => {
        const html = renderWechatHtml('---\ntitle: "EOF 标题"\n---');
        expect(html).toContain('<title>EOF 标题</title>');
        expect(html).not.toContain('<hr>');
        expect(html).not.toContain('title: &quot;EOF 标题&quot;');
    });
    it('escapes malicious raw html instead of emitting executable html', () => {
        const html = renderWechatHtml('hello<script>alert(1)</script><img src=x onerror=alert(2) />');
        expect(html).not.toContain('<script>alert(1)</script>');
        expect(html).not.toContain('<img src=x onerror=alert(2) />');
        expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
        expect(html).toContain('&lt;img src=x onerror=alert(2) /&gt;');
    });
    it('does not emit executable href or src for unsafe markdown urls', () => {
        const html = renderWechatHtml('[危险链接](javascript:alert(1))\n\n![危险图片](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p class="p">危险链接</p>');
        expect(html).toContain('<p class="p">危险图片</p>');
        expect(html).not.toContain('<a href="javascript:alert(1)"');
        expect(html).not.toContain('<img src="data:text/html');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data:text/html');
    });
    it('does not include Chinese dash descriptions in bare URL links', () => {
        const html = renderWechatHtml('> https://github.com/wshobson/agents——2.5 万+ 星');
        expect(html).toContain('<blockquote class="blockquote">');
        expect(html).toContain('&nbsp;&nbsp;<a href="https://github.com/wshobson/agents">https://github.com/wshobson/agents</a>——2.5 万+ 星');
        expect(html).not.toContain('%E2%80%94');
        expect(html).not.toContain('href="https://github.com/wshobson/agents——2.5"');
    });
    it('adds two non-collapsing spaces before blockquote content', () => {
        const html = renderWechatHtml('> https://github.com/karpathy/llm-wiki');
        expect(html).toContain('<blockquote class="blockquote"><p class="p">&nbsp;&nbsp;<a href="https://github.com/karpathy/llm-wiki">https://github.com/karpathy/llm-wiki</a></p></blockquote>');
    });
    it('blocks entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[实体危险链接](javascript&#58;alert(1))\n\n![实体危险图片](data&#x3A;text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p class="p">实体危险链接</p>');
        expect(html).toContain('<p class="p">实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&#58;alert(1)"');
        expect(html).not.toContain('<img src="data&#x3A;text/html');
        expect(html).not.toContain('javascript&#58;alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&#x3A;text/html');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks nested entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[嵌套实体危险链接](javascript&amp;#58;alert(1))\n\n![嵌套实体危险图片](data&amp;#x3A;text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p class="p">嵌套实体危险链接</p>');
        expect(html).toContain('<p class="p">嵌套实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&amp;#58;alert(1)"');
        expect(html).not.toContain('<img src="data&amp;#x3A;text/html');
        expect(html).not.toContain('javascript&amp;#58;alert(1)');
        expect(html).not.toContain('javascript&#58;alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&amp;#x3A;text/html');
        expect(html).not.toContain('data&#x3A;text/html');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks semicolon-less entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[无分号实体危险链接](javascript&#58alert(1))\n\n![无分号实体危险图片](data&#x3Atext/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p class="p">无分号实体危险链接</p>');
        expect(html).toContain('<p class="p">无分号实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&#58alert(1)"');
        expect(html).not.toContain('<img src="data&#x3Atext/html');
        expect(html).not.toContain('javascript&#58alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&#x3Atext/html');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks nested semicolon-less entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[嵌套无分号实体危险链接](javascript&amp;#58alert(1))\n\n![嵌套无分号实体危险图片](data&amp;#x3Atext/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p class="p">嵌套无分号实体危险链接</p>');
        expect(html).toContain('<p class="p">嵌套无分号实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&amp;#58alert(1)"');
        expect(html).not.toContain('<img src="data&amp;#x3Atext/html');
        expect(html).not.toContain('javascript&amp;#58alert(1)');
        expect(html).not.toContain('javascript&#58alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&amp;#x3Atext/html');
        expect(html).not.toContain('data&#x3Atext/html');
        expect(html).not.toContain('data:text/html');
    });
});
describe('renderer entrypoint', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.resetModules();
    });
    it('does not read or write files when imported as a module', async () => {
        const readFileSync = vi.fn(() => '');
        const writeFileSync = vi.fn();
        const originalArgv = process.argv;
        vi.doMock('node:fs', () => ({
            readFileSync,
            writeFileSync,
        }));
        try {
            process.argv = ['node', '/tmp/another-entry.js', 'input.md', 'output.html'];
            vi.resetModules();
            await import('./index.js');
            expect(readFileSync).not.toHaveBeenCalled();
            expect(writeFileSync).not.toHaveBeenCalled();
        }
        finally {
            process.argv = originalArgv;
            vi.doUnmock('node:fs');
        }
    });
});

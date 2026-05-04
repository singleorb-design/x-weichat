import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWechatHtml } from './render.js';
describe('renderWechatHtml', () => {
    it('renders heading and paragraph', () => {
        const html = renderWechatHtml('# 标题\n\n正文');
        expect(html).toContain('<h1>标题</h1>');
        expect(html).toContain('<p>正文</p>');
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
        expect(html).toContain('<p>危险链接</p>');
        expect(html).toContain('<p>危险图片</p>');
        expect(html).not.toContain('<a href="javascript:alert(1)"');
        expect(html).not.toContain('<img src="data:text/html');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[实体危险链接](javascript&#58;alert(1))\n\n![实体危险图片](data&#x3A;text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p>实体危险链接</p>');
        expect(html).toContain('<p>实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&#58;alert(1)"');
        expect(html).not.toContain('<img src="data&#x3A;text/html');
        expect(html).not.toContain('javascript&#58;alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&#x3A;text/html');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks nested entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[嵌套实体危险链接](javascript&amp;#58;alert(1))\n\n![嵌套实体危险图片](data&amp;#x3A;text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p>嵌套实体危险链接</p>');
        expect(html).toContain('<p>嵌套实体危险图片</p>');
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
        expect(html).toContain('<p>无分号实体危险链接</p>');
        expect(html).toContain('<p>无分号实体危险图片</p>');
        expect(html).not.toContain('<a href="javascript&#58alert(1)"');
        expect(html).not.toContain('<img src="data&#x3Atext/html');
        expect(html).not.toContain('javascript&#58alert(1)');
        expect(html).not.toContain('javascript:alert(1)');
        expect(html).not.toContain('data&#x3Atext/html');
        expect(html).not.toContain('data:text/html');
    });
    it('blocks nested semicolon-less entity-encoded unsafe markdown urls', () => {
        const html = renderWechatHtml('[嵌套无分号实体危险链接](javascript&amp;#58alert(1))\n\n![嵌套无分号实体危险图片](data&amp;#x3Atext/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)');
        expect(html).toContain('<p>嵌套无分号实体危险链接</p>');
        expect(html).toContain('<p>嵌套无分号实体危险图片</p>');
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

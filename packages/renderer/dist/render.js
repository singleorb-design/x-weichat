import { Renderer, marked } from 'marked';
import { wechatTemplate } from './template.js';
const UNSAFE_URL_SCHEMES = ['javascript:', 'data:'];
const URL_ENTITY_NAMES = {
    amp: '&',
    colon: ':',
};
function escapeHtml(value) {
    return value
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}
function decodeCodePoint(value, fallback) {
    if (!Number.isInteger(value) || value < 0 || value > 0x10ffff) {
        return fallback;
    }
    return String.fromCodePoint(value);
}
function decodeHtmlEntitiesForUrlCheck(value) {
    return value.replace(/&(?:#(\d+);?|#x([\da-f]+);?|(amp|colon);?)/gi, (match, decimal, hexadecimal, named) => {
        if (decimal) {
            return decodeCodePoint(Number(decimal), match);
        }
        if (hexadecimal) {
            return decodeCodePoint(Number.parseInt(hexadecimal, 16), match);
        }
        if (named) {
            return URL_ENTITY_NAMES[named.toLowerCase()] ?? match;
        }
        return match;
    });
}
function hasUnsafeUrlScheme(value) {
    let normalized = value;
    for (let index = 0; index < 5; index += 1) {
        const decoded = decodeHtmlEntitiesForUrlCheck(normalized);
        if (decoded === normalized) {
            break;
        }
        normalized = decoded;
    }
    normalized = normalized.replace(/[\u0000-\u0020]+/g, '').toLowerCase();
    return UNSAFE_URL_SCHEMES.some((scheme) => normalized.startsWith(scheme));
}
export function renderWechatHtml(markdown) {
    const renderer = new Renderer();
    renderer.html = ({ text }) => escapeHtml(text);
    renderer.link = (token) => {
        const { href, tokens } = token;
        const text = renderer.parser.parseInline(tokens);
        if (hasUnsafeUrlScheme(href)) {
            return text;
        }
        return Renderer.prototype.link.call(renderer, token);
    };
    renderer.image = (token) => {
        const { href, text } = token;
        if (hasUnsafeUrlScheme(href)) {
            return escapeHtml(text);
        }
        return Renderer.prototype.image.call(renderer, token);
    };
    const body = marked.parse(markdown, {
        async: false,
        renderer,
    });
    return wechatTemplate(body);
}

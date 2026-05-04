function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
function normalizeHeadingText(value) {
    return value.replace(/\s+/g, ' ').trim();
}
export function removeFirstHeading(html, title) {
    const normalizedTitle = normalizeHeadingText(title);
    if (!normalizedTitle) {
        return html;
    }
    const firstHeadingPattern = new RegExp(`^\\s*<h1>(?:${escapeRegExp(normalizedTitle)}|${escapeRegExp(normalizedTitle).replace(/ /g, '\\s+')})<\\/h1>\\s*`, 'i');
    return html.replace(firstHeadingPattern, '');
}
export function wrapModernRedContent(html) {
    return `<section class="container">${html}</section>`;
}

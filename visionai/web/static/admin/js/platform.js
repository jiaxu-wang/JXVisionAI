/* JXVisionAI admin — 平台接入：配置了嵌入 URL 则 iframe，否则未接入。 */

function platformEmbedFieldFromUnits(units, key) {
    if (!Array.isArray(units)) return null;
    for (let i = 0; i < units.length; i++) {
        const fields = (units[i] && units[i].fields) || [];
        for (let j = 0; j < fields.length; j++) {
            const f = fields[j];
            if (f && f.key === key) {
                return String(f.value == null ? '' : f.value).trim();
            }
        }
    }
    return null;
}

function applyPlatformEmbedUrl(url) {
    const frame = document.getElementById('platformEmbedFrame');
    const empty = document.getElementById('platformEmbedEmpty');
    const page = document.getElementById('platformPage');
    const contentEl = document.querySelector('.content');
    if (!frame || !empty) return;
    const u = String(url || '').trim();
    if (u) {
        empty.style.display = 'none';
        frame.style.display = 'block';
        if (contentEl) contentEl.classList.add('is-platform-embed');
        if (page && page.style.display !== 'none') page.style.display = 'flex';
        if (frame.getAttribute('src') !== u) {
            frame.setAttribute('src', u);
        }
    } else {
        frame.removeAttribute('src');
        frame.style.display = 'none';
        empty.style.display = 'block';
        if (contentEl) contentEl.classList.remove('is-platform-embed');
        if (page && page.style.display !== 'none') page.style.display = 'block';
    }
}

function loadPlatformEmbedPage() {
    applyPlatformEmbedUrl(window.__PLATFORM_EMBED_URL__ || '');
    fetch('/api/system/config')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
            if (!data || !data.success) return;
            const fromFile = platformEmbedFieldFromUnits(data.units, 'platform_embed_url');
            if (fromFile !== null) {
                applyPlatformEmbedUrl(fromFile);
            }
        })
        .catch(function () { /* keep already applied url */ });
}

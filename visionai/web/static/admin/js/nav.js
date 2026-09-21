/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* nav.js */

function goToPage(pageKey, opts) {
    opts = opts || {};
    pageKey = resolveNavPageKey(pageKey, opts);
    const navKey = pageKey === 'access' ? 'access' : pageKey;
    const navEl = document.querySelector('.menu-nav-btn[data-page="' + navKey + '"]');
    if (opts.streamId) pendingHighlightStreamId = String(opts.streamId);
    applyVisionaiMainPage(pageKey, navEl || null, opts);
    try {
        const q = new URLSearchParams();
        q.set('page', pageKey);
        if (pageKey === 'access') q.set('tab', currentAccessTab || 'direct');
        if (opts.streamId) q.set('stream', opts.streamId);
        history.replaceState(null, '', '#' + q.toString());
    } catch (e) { /* ignore */ }
}

function highlightStreamCard(streamId) {
    if (!streamId) return;
    const safe = String(streamId).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    const el = document.querySelector('.stream-item[data-id="' + safe + '"]');
    if (!el) return;
    el.classList.add('stream-item-highlight');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(function () { el.classList.remove('stream-item-highlight'); }, 2600);
    pendingHighlightStreamId = '';
}

function showAccessTab(tab, afterLoad) {
    const tabKey = ACCESS_TABS[tab] ? tab : 'direct';
    currentAccessTab = tabKey;
    document.querySelectorAll('.access-tab-btn').forEach(function (btn) {
        btn.classList.toggle('active', btn.getAttribute('data-access-tab') === tabKey);
    });
    document.querySelectorAll('.access-tab-panel').forEach(function (panel) {
        panel.classList.toggle('active', panel.getAttribute('data-access-panel') === tabKey);
    });
    const pt = document.getElementById('pageTitle');
    if (pt) {
        pt.textContent = t('access.titleWithTab', { tab: t('access.tab.' + tabKey) });
    }
    const done = typeof afterLoad === 'function' ? afterLoad : function () {};
    let p = Promise.resolve();
    if (tabKey === 'direct') p = loadDirectStreams();
    else if (tabKey === 'onvif') p = loadOnvifStreams();
    else if (tabKey === 'gb28181') p = loadGb28181Streams();
    Promise.resolve(p).then(done).catch(done);
    try {
        const q = new URLSearchParams((location.hash || '').replace(/^#/, ''));
        q.set('page', 'access');
        q.set('tab', tabKey);
        if (pendingHighlightStreamId) q.set('stream', pendingHighlightStreamId);
        else q.delete('stream');
        history.replaceState(null, '', '#' + q.toString());
    } catch (e) { /* ignore */ }
}

function applyVisionaiMainPage(pageKey, navEl, opts) {
    if (!pageKey) {
        return;
    }
    opts = opts || {};
    pageKey = resolveNavPageKey(pageKey, opts);
    try {
        safeCloseModalsForNav();
        document.querySelectorAll('.menu-nav-btn[data-page]').forEach(function (item) {
            item.classList.remove('active');
        });
        const navKey = pageKey === 'access' ? 'access' : pageKey;
        if (!navEl) {
            navEl = document.querySelector('.menu-nav-btn[data-page="' + navKey + '"]');
        }
        if (navEl) {
            navEl.classList.add('active');
        }
        document.querySelectorAll('.page-content').forEach(function (page) {
            page.style.display = 'none';
        });
        const contentEl = document.querySelector('.content');
        if (contentEl) {
            contentEl.classList.remove('is-platform-embed');
        }
        const pageEl = document.getElementById(pageKey + 'Page');
        if (!pageEl) {
            console.warn('missing page: #' + pageKey + 'Page');
            return;
        }
        pageEl.style.display = 'block';
        const pt = document.getElementById('pageTitle');
        if (pt && pageKey === 'access') {
            /* title set in showAccessTab */
        } else if (pt) {
            const map = {
                overview: 'nav.overview',
                preview: 'nav.preview',
                policy: 'nav.policy',
                alerts: 'nav.alerts',
                settings: 'nav.settings',
                platform: 'nav.platform'
            };
            pt.textContent = t(map[pageKey] || ('nav.' + pageKey));
        }
        const afterLoad = function () {
            const sid = pendingHighlightStreamId;
            if (sid) highlightStreamCard(sid);
            if (pageKey === 'policy' && sid && opts.openDetection) {
                const safe = String(sid).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
                const card = document.querySelector('.stream-item[data-id="' + safe + '"]');
                const btn = card && card.querySelector('.stream-detection-config-btn');
                if (btn) openDetectionConfig(btn);
            }
        };
        if (pageKey === 'overview') {
            loadStatusData();
        } else if (pageKey === 'alerts') {
            loadAlertsData();
        } else if (pageKey === 'access') {
            showAccessTab(opts.tab || currentAccessTab || 'direct', afterLoad);
        } else if (pageKey === 'policy') {
            loadPolicyStreams().then(afterLoad);
        } else if (pageKey === 'settings') {
            loadSystemSettings();
        } else if (pageKey === 'preview') {
            schedulePreviewNavRefresh();
        } else if (pageKey === 'platform') {
            if (typeof loadPlatformEmbedPage === 'function') loadPlatformEmbedPage();
        }
    } catch (err) {
        console.error('navigation error', err);
    }
}

window.__visionaiGoPage = applyVisionaiMainPage;

function visionaiMenuActivate(event, el) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    if (!el) {
        return false;
    }
    const pageKey = el.getAttribute('data-page');
    if (!pageKey) {
        return false;
    }
    goToPage(pageKey);
    return false;
}

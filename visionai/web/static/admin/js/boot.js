/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* boot.js */

function applyHashRoute() {
    try {
        const raw = (location.hash || '').replace(/^#/, '');
        if (!raw) return false;
        const q = new URLSearchParams(raw);
        let page = q.get('page') || '';
        if (page === 'video') page = 'direct';
        const tab = q.get('tab') || '';
        const sid = q.get('stream') || '';
        if (!page) return false;
        const opts = {};
        if (sid) opts.streamId = sid;
        if (tab) opts.tab = tab;
        goToPage(page, opts);
        return true;
    } catch (e) {
        return false;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    if (window.VisionAI && VisionAI.i18n) {
        VisionAI.i18n.mountLangSwitch(document.getElementById('langSwitch'));
        await VisionAI.i18n.ready();
    }
    await fetchConfig();
    await loadDetectionCatalog();
    syncAlertsPageSizeSelect();
    if (!applyHashRoute()) {
        loadStatusData();
    }
    schedulePreviewNavRefresh();
    window.addEventListener('hashchange', function () {
        applyHashRoute();
    });
    
    // 定时刷新状态数据（每10秒）
    setInterval(() => {
        const ov = document.getElementById('overviewPage');
        if (ov && ov.style.display !== 'none') {
            loadStatusData();
        }
    }, 10000);
    
    // 启动检测记录自动刷新
    startAutoRefresh();
});

window.__visionaiOnLocaleChange = function () {
    const active = document.querySelector('.menu-nav-btn.active[data-page]');
    const pageKey = active ? active.getAttribute('data-page') : 'overview';
    const pt = document.getElementById('pageTitle');
    if (pt) {
        if (pageKey === 'access') {
            pt.textContent = t('access.titleWithTab', { tab: t('access.tab.' + (currentAccessTab || 'direct')) });
        } else {
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
    }
    fillAlertFilterTypeOptions();
    const ov = document.getElementById('overviewPage');
    if (ov && ov.style.display !== 'none') loadStatusData();
    const al = document.getElementById('alertsPage');
    if (al && al.style.display !== 'none' && typeof loadAlertsData === 'function') loadAlertsData(currentPage);
    const ac = document.getElementById('accessPage');
    if (ac && ac.style.display !== 'none' && typeof showAccessTab === 'function') {
        showAccessTab(currentAccessTab || 'direct');
    }
    const po = document.getElementById('policyPage');
    if (po && po.style.display !== 'none' && typeof loadPolicyStreams === 'function') loadPolicyStreams();
    const pr = document.getElementById('previewPage');
    if (pr && pr.style.display !== 'none') schedulePreviewNavRefresh();
    const dcm = document.getElementById('detectionConfigModal');
    if (dcm && dcm.classList.contains('show') && typeof renderDetectionModalList === 'function') {
        const q = document.getElementById('detectionConfigSearch');
        renderDetectionModalList(q ? q.value : '');
    }
    if (typeof renderOnvifDevices === 'function' && document.getElementById('onvifModal') &&
        document.getElementById('onvifModal').classList.contains('show')) {
        renderOnvifDevices();
    }
    const se = document.getElementById('settingsPage');
    if (se && se.style.display !== 'none' && typeof rerenderSystemSettingsKeepValues === 'function') {
        rerenderSystemSettingsKeepValues();
    }
    const pf = document.getElementById('platformPage');
    if (pf && pf.style.display !== 'none' && typeof loadPlatformEmbedPage === 'function') {
        loadPlatformEmbedPage();
    }
};

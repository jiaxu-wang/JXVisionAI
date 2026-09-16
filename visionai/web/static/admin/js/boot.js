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

// 页面加载时加载数据
document.addEventListener('DOMContentLoaded', async () => {
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

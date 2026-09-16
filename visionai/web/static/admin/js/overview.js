/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* overview.js */

async function loadStatusData() {
    try {
        const [response, statsRes, metricsRes, zlmRes] = await Promise.all([
            fetch('/api/streams'),
            fetch('/api/stats/alerts-today'),
            fetch('/api/metrics').catch(() => null),
            fetch('/api/zlm/status').catch(() => null),
        ]);
        const streams = await response.json();
        const stats = await statsRes.json();
        let metrics = null;
        let zlm = null;
        try { metrics = metricsRes && metricsRes.ok ? await metricsRes.json() : null; } catch (e) { metrics = null; }
        try { zlm = zlmRes && zlmRes.ok ? await zlmRes.json() : null; } catch (e) { zlm = null; }
        
        // 统计在线流数量
        const onlineStreams = streams.filter(stream => stream.status === '在线').length;
        
        // 更新状态数据（在线数/视频总数）
        document.getElementById('streamOnlineSummary').textContent =
            `（${onlineStreams}/${streams.length}）`;
        const todayAlerts = stats.success ? (Number(stats.count) || 0) : 0;
        document.getElementById('alertCount').textContent = String(todayAlerts);

        const metricEl = document.getElementById('runtimeMetricSummary');
        const zlmHint = document.getElementById('zlmRuntimeHint');
        if (metricEl) {
            const q = metrics && metrics.alert_queue_depth != null ? metrics.alert_queue_depth : '—';
            const up = metrics && metrics.uptime_sec != null ? Math.round(metrics.uptime_sec) + 's' : '—';
            metricEl.textContent = `队列 ${q} · 运行 ${up}`;
        }
        if (zlmHint) {
            if (!zlm || !zlm.enabled) {
                zlmHint.textContent = 'ZLM 未启用';
                zlmHint.className = 'status status-offline';
            } else if (zlm.alive) {
                const on = (zlm.streams || []).filter(s => s.online).length;
                zlmHint.textContent = `ZLM 在线 · 代理 ${on}/${(zlm.streams || []).length}`;
                zlmHint.className = 'status status-online';
            } else if (zlm.reachable && zlm.auth_ok === false) {
                zlmHint.textContent = 'ZLM 鉴权失败';
                zlmHint.className = 'status status-offline';
                zlmHint.title = zlm.message || '请将 [zlm] secret 改为非默认值，并与 config/zlm/config.ini 一致后重启 zlmediakit';
            } else {
                zlmHint.textContent = 'ZLM 不可达';
                zlmHint.className = 'status status-offline';
            }
        }
        window._zlmStatusCache = zlm;
        
        if (streams.length === 0) {
            document.getElementById('streamStatus').className = 'status status-offline';
            document.getElementById('streamStatus').textContent = '无流配置';
        } else if (onlineStreams === streams.length) {
            document.getElementById('streamStatus').className = 'status status-online';
            document.getElementById('streamStatus').textContent = '全部在线';
        } else if (onlineStreams === 0) {
            document.getElementById('streamStatus').className = 'status status-offline';
            document.getElementById('streamStatus').textContent = '全部离线';
        } else {
            document.getElementById('streamStatus').className = 'status status-online';
            document.getElementById('streamStatus').textContent = '部分在线';
        }
        
        // 加载流状态列表
        const streamStatusList = document.getElementById('streamStatusList');
        streamStatusList.innerHTML = '';
        
        if (streams.length === 0) {
            streamStatusList.innerHTML = '<p style="color: #6c757d; text-align: center; padding: 20px;">暂无视频配置</p>';
        } else {
            const zlmById = {};
            if (zlm && zlm.streams) {
                zlm.streams.forEach(s => { if (s.id) zlmById[s.id] = s; });
            }
            streams.forEach(stream => {
                const streamItem = document.createElement('div');
                streamItem.className = 'stream-item';
                const statusClass = stream.status === '在线' ? 'status-online' : 'status-offline';
                const enabled = stream.enabled !== false;
                const joined = isAnalysisJoined(stream);
                const hasTypes = streamHasAnyDetection(stream);
                let enabledClass;
                let enabledText;
                if (!joined) {
                    enabledClass = 'status-warn';
                    enabledText = '未接入分析';
                } else if (!enabled) {
                    enabledClass = 'status-offline';
                    enabledText = '检测禁用';
                } else if (!hasTypes) {
                    enabledClass = 'status-warn';
                    enabledText = '未配置检测类型';
                } else {
                    enabledClass = 'status-online';
                    enabledText = '检测开启';
                }
                const sid = stream.id || '';
                const zs = zlmById[sid];
                const zlmBadge = zs
                    ? `<span class="status ${zs.online ? 'status-online' : 'status-offline'}">ZLM ${zs.online ? '代理中' : '未上线'}</span>`
                    : '';
                const isOnvif = normalizeAccessMethodClient(stream) === 'onvif';
                const talkOk = !!stream.talk_supported;
                const talkBadge = isOnvif
                    ? (talkOk
                        ? `<span class="talk-badge yes">支持对讲</span>`
                        : `<span class="talk-badge no">未确认对讲</span>`)
                    : '';
                const accessBadge = `<span class="access-badge">${escapeHtml(accessLabelForStream(stream))}</span>`;
                const nameHtml = sid
                    ? `<a href="#page=access&tab=${accessTabForStream(stream)}&stream=${encodeURIComponent(sid)}" class="stream-name-link" data-sid="${escapeHtml(sid)}">${escapeHtml(stream.name)}</a>`
                    : `<strong>${escapeHtml(stream.name)}</strong>`;
                streamItem.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                        <div style="flex: 1; min-width: 200px;">
                            ${nameHtml}${accessBadge}${talkBadge}
                            <p style="color: #6c757d; font-size: 14px; word-break: break-all;">${escapeHtml(stream.url || '')}</p>
                        </div>
                        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                            <span class="status ${statusClass}">${escapeHtml(stream.status)}</span>
                            <span class="status ${enabledClass}">${enabledText}</span>
                            ${zlmBadge}
                            <button type="button" class="btn-filter-apply btn-goto-access" ${sid ? '' : 'disabled'} title="跳转到对应接入配置">接入配置</button>
                        </div>
                    </div>
                `;
                streamStatusList.appendChild(streamItem);
                const goAccess = function () {
                    goToPage(accessPageForStream(stream), { streamId: sid });
                };
                const nameLink = streamItem.querySelector('.stream-name-link');
                if (nameLink && sid) {
                    nameLink.addEventListener('click', function (e) {
                        e.preventDefault();
                        goAccess();
                    });
                }
                const gotoBtn = streamItem.querySelector('.btn-goto-access');
                if (gotoBtn && sid) {
                    gotoBtn.addEventListener('click', goAccess);
                }
            });
        }
    } catch (error) {
        // 加载失败时显示默认数据
        document.getElementById('streamOnlineSummary').textContent = '（0/0）';
        document.getElementById('alertCount').textContent = '0';
        document.getElementById('streamStatus').className = 'status status-offline';
        document.getElementById('streamStatus').textContent = '加载失败';
        
        const streamStatusList = document.getElementById('streamStatusList');
        streamStatusList.innerHTML = '<p style="color: #6c757d; text-align: center; padding: 20px;">加载流状态失败</p>';
    }
}

// 当前页码和每页数量（默认 5，可通过历史告警页下拉框修改）
let currentPage = 1;
let itemsPerPage = 5;
const ALERTS_PAGE_SIZE_OPTIONS = [5, 10, 15, 20, 30, 50];
let autoRefreshInterval = null;
let configRefreshInterval = 20000; // 默认20秒
let appTimezone = 'Asia/Shanghai'; // 与 [basic] timezone / VISIONAI_TIMEZONE 一致

let detectionCatalog = [];

function streamHasAnyDetection(stream) {
    const d = (stream && stream.detections) || {};
    return Object.keys(d).some(function (k) { return !!d[k]; });
}

function isAnalysisJoined(stream) {
    if (!stream) return false;
    if (!Object.prototype.hasOwnProperty.call(stream, 'analyze') || stream.analyze == null) {
        return true;
    }
    return !!stream.analyze;
}

function defaultAllOffDetections() {
    const d = {};
    for (let i = 0; i < 80; i++) d[String(i)] = false;
    if (Array.isArray(detectionCatalog)) {
        detectionCatalog.forEach(function (it) {
            if (it && it.class_id === null && it.key) d[it.key] = false;
        });
    } else {
        d.call = false;
        d.phone_play = false;
        d.gather = false;
        d.smoking = false;
    }
    return d;
}

function normalizeDetectionsClient(raw) {
    const d = defaultAllOffDetections();
    if (!raw || typeof raw !== 'object') return d;
    for (let i = 0; i < 80; i++) {
        const k = String(i);
        if (Object.prototype.hasOwnProperty.call(raw, k)) d[k] = !!raw[k];
    }
    if (Array.isArray(detectionCatalog)) {
        detectionCatalog.forEach(function (it) {
            if (!it || it.class_id !== null || !it.key) return;
            if (Object.prototype.hasOwnProperty.call(raw, it.key)) {
                d[it.key] = !!raw[it.key];
            }
        });
    }
    return d;
}

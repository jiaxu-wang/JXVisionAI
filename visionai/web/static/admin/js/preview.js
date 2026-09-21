/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* preview.js */

const ACCESS_TAB = { rtsp_url: 'direct', onvif: 'onvif', gb28181: 'gb28181' };
const ACCESS_TAB_LABEL = { direct: 'RTSP直连', onvif: 'ONVIF 接入', gb28181: '国标 28181' };
const ACCESS_LABEL = { rtsp_url: 'RTSP直连', onvif: 'ONVIF', gb28181: '国标 28181' };
const DIRECT_METHODS = { rtsp_url: 1 };
const ACCESS_TABS = { direct: 1, onvif: 1, gb28181: 1 };
let pendingHighlightStreamId = '';
let currentAccessTab = 'direct';

function normalizeAccessMethodClient(stream) {
    if (!stream || typeof stream !== 'object') return 'rtsp_url';
    const raw = String(stream.access_method || '').trim().toLowerCase();
    if (ACCESS_TAB[raw]) return raw;
    if (stream.gb28181 && typeof stream.gb28181 === 'object') return 'gb28181';
    const ov = stream.onvif;
    if (ov && typeof ov === 'object' && (String(ov.host || '').trim() || String(ov.profile_token || '').trim())) {
        return 'onvif';
    }
    return 'rtsp_url';
}

function accessTabForStream(stream) {
    return ACCESS_TAB[normalizeAccessMethodClient(stream)] || 'direct';
}

/** 兼容旧名：返回接入子 Tab key */
function accessPageForStream(stream) {
    return accessTabForStream(stream);
}

function accessTabLabel(tab) {
    return t('access.tab.' + tab);
}

function accessMethodLabel(method) {
    return t('access.method.' + method);
}

function accessLabelForStream(stream) {
    const m = normalizeAccessMethodClient(stream);
    return accessMethodLabel(m) || ACCESS_LABEL[m] || m;
}

const PREVIEW_WALL_MAX = 25;
let previewWallSlots = [];
let previewNavExpand = { rtsp_url: true, onvif: true, gb28181: true };
let previewNavDevExpand = {};
let previewNavLeafIndex = {};
let previewNavRefreshTimer = null;
let previewWallPending = {};

function previewWallKeyStream(streamId) {
    return 'stream:' + String(streamId || '');
}

function previewWallKeyGb(deviceId, channelId) {
    return 'gb:' + String(deviceId || '') + ':' + String(channelId || '');
}

function findPreviewWallSlot(key) {
    return previewWallSlots.find(function (s) { return s.key === key; });
}

function isPreviewPageVisible() {
    const page = document.getElementById('previewPage');
    return !!(page && page.style.display !== 'none');
}

function ensurePreviewPage() {
    if (!isPreviewPageVisible()) goToPage('preview');
}

function updatePreviewWallCount() {
    const el = document.getElementById('previewWallCount');
    if (el) el.textContent = previewWallSlots.length + ' / ' + PREVIEW_WALL_MAX;
    syncPreviewNavPlaying();
    updatePreviewWallLayout();
}

function updatePreviewWallLayout() {
    const grid = document.getElementById('previewWallGrid');
    if (!grid) return;
    const n = previewWallSlots.length;
    let cols = 5;
    if (n <= 1) cols = 1;
    else if (n <= 4) cols = 2;
    else if (n <= 9) cols = 3;
    else if (n <= 16) cols = 4;
    grid.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    grid.style.gridTemplateRows = n ? ('repeat(' + cols + ', minmax(110px, 1fr))') : '';
}

function syncPreviewNavPlaying() {
    const keys = {};
    previewWallSlots.forEach(function (s) { keys[s.key] = true; });
    document.querySelectorAll('#previewNavTree .preview-nav-leaf[data-preview-key]').forEach(function (el) {
        el.classList.toggle('playing', !!keys[el.getAttribute('data-preview-key')]);
    });
}

function ensurePreviewEmptyHint() {
    const grid = document.getElementById('previewWallGrid');
    if (!grid) return;
    let empty = grid.querySelector('.preview-wall-empty');
    if (previewWallSlots.length === 0) {
        if (!empty) {
            empty = document.createElement('div');
            empty.className = 'preview-wall-empty';
            empty.setAttribute('data-i18n', 'preview.empty');
            empty.textContent = t('preview.empty');
            grid.appendChild(empty);
        }
    } else if (empty) {
        empty.remove();
    }
}

function flashPreviewTile(slot) {
    if (!slot || !slot.tileEl) return;
    slot.tileEl.classList.add('preview-wall-flash');
    setTimeout(function () {
        if (slot.tileEl) slot.tileEl.classList.remove('preview-wall-flash');
    }, 700);
}

function closePreviewWallSlot(slot) {
    if (!slot) return;
    if (slot.handle) {
        try { slot.handle.stop(); } catch (e) { /* ignore */ }
        slot.handle = null;
    }
    const sess = slot.gbPreview;
    if (sess && sess.bye_on_close && sess.device_id && sess.channel_id) {
        fetch('/api/gb28181/devices/' + encodeURIComponent(sess.device_id) +
            '/channels/' + encodeURIComponent(sess.channel_id) + '/bye', { method: 'POST' })
            .catch(function () {});
    }
    if (slot.tileEl && slot.tileEl.parentNode) slot.tileEl.remove();
    previewWallSlots = previewWallSlots.filter(function (s) { return s !== slot; });
    updatePreviewWallCount();
    ensurePreviewEmptyHint();
}

function closeAllPreviewWall() {
    previewWallSlots.slice().forEach(closePreviewWallSlot);
}

function addPreviewWallTile(spec) {
    spec = spec || {};
    const key = spec.key;
    if (!key || !spec.streamId) return;
    const existing = findPreviewWallSlot(key);
    if (existing) {
        ensurePreviewPage();
        flashPreviewTile(existing);
        return;
    }
    if (previewWallSlots.length >= PREVIEW_WALL_MAX) {
        showMessage(t('preview.maxSlots'), 'error');
        return;
    }
    ensurePreviewPage();
    const grid = document.getElementById('previewWallGrid');
    if (!grid) return;
    const empty = grid.querySelector('.preview-wall-empty');
    if (empty) empty.remove();

    const tile = document.createElement('div');
    tile.className = 'preview-wall-tile';
    tile.setAttribute('data-preview-key', key);
    const title = spec.name || spec.streamId || '';
    tile.innerHTML =
        '<div class="preview-wall-head">' +
            '<span class="preview-wall-title" title="' + escapeHtml(title) + '">' + escapeHtml(title) + '</span>' +
            '<button type="button" class="preview-wall-close" title="' + escapeHtml(t('common.close')) + '" aria-label="' + escapeHtml(t('common.close')) + '">×</button>' +
        '</div>' +
        '<video playsinline muted></video>' +
        '<div class="preview-wall-status">' + escapeHtml(t('preview.connecting')) + '</div>';
    const video = tile.querySelector('video');
    const statusEl = tile.querySelector('.preview-wall-status');
    const slot = {
        key: key,
        kind: spec.kind || 'stream',
        name: title,
        streamId: spec.streamId,
        app: spec.app || '',
        gbPreview: spec.gbPreview || null,
        handle: null,
        videoEl: video,
        tileEl: tile
    };
    tile.querySelector('.preview-wall-close').addEventListener('click', function (e) {
        e.stopPropagation();
        closePreviewWallSlot(slot);
    });
    grid.appendChild(tile);
    previewWallSlots.push(slot);
    updatePreviewWallCount();
    slot.handle = startWebrtcPlay(video, spec.streamId, {
        app: spec.app || '',
        onPlaying: function () {
            if (statusEl) statusEl.style.display = 'none';
        },
        onError: function (msg) {
            if (statusEl) {
                statusEl.style.display = '';
                statusEl.textContent = msg || t('preview.playFailed');
            }
        }
    });
}

function startPreviewWallStream(streamId, name) {
    streamId = String(streamId || '').trim();
    if (!streamId) {
        showMessage(t('preview.needId'), 'error');
        return;
    }
    addPreviewWallTile({
        key: previewWallKeyStream(streamId),
        kind: 'stream',
        name: name || streamId,
        streamId: streamId,
        app: ''
    });
}

async function startPreviewWallGb(deviceId, channelId, name) {
    deviceId = String(deviceId || '').trim();
    channelId = String(channelId || '').trim();
    if (!deviceId || !channelId) {
        showMessage(t('preview.needDevCh'), 'error');
        return;
    }
    const key = previewWallKeyGb(deviceId, channelId);
    const existing = findPreviewWallSlot(key);
    if (existing) {
        ensurePreviewPage();
        flashPreviewTile(existing);
        return;
    }
    if (previewWallPending[key]) return;
    if (previewWallSlots.length >= PREVIEW_WALL_MAX) {
        showMessage(t('preview.maxSlots'), 'error');
        return;
    }
    previewWallPending[key] = true;
    showMessage(t('preview.inviting'), 'success');
    try {
        const r = await fetch('/api/gb28181/devices/' + encodeURIComponent(deviceId) +
            '/channels/' + encodeURIComponent(channelId) + '/preview', { method: 'POST' });
        const j = await fetchJsonOrThrow(r);
        if (!j.success) {
            showMessage(j.message || t('preview.playFail'), 'error');
            return;
        }
        const zlmStream = j.zlm_stream || '';
        if (zlmStream) {
            addPreviewWallTile({
                key: key,
                kind: 'gb',
                name: j.name || name || channelId,
                streamId: zlmStream,
                app: 'rtp',
                gbPreview: {
                    device_id: deviceId,
                    channel_id: channelId,
                    bye_on_close: !j.already_monitored
                }
            });
            return;
        }
        if (j.already_monitored && j.stream_id) {
            addPreviewWallTile({
                key: key,
                kind: 'gb',
                name: j.name || name || channelId,
                streamId: j.stream_id,
                app: '',
                gbPreview: { device_id: deviceId, channel_id: channelId, bye_on_close: false }
            });
            return;
        }
        showMessage(t('preview.noMedia'), 'error');
    } catch (e) {
        showMessage(t('preview.playFail') + ': ' + (e.message || e), 'error');
    } finally {
        delete previewWallPending[key];
    }
}

function previewNavTypeGroupHtml(kind, title, innerHtml, count) {
    const open = previewNavExpand[kind] !== false;
    return '<div class="preview-nav-group' + (open ? ' open' : '') + '" data-group="' + kind + '">' +
        '<button type="button" class="preview-nav-type">' +
            '<span class="preview-nav-caret">' + (open ? '▼' : '▶') + '</span>' +
            escapeHtml(title) +
            ' <span style="color:#868e96;font-weight:400">(' + count + ')</span>' +
        '</button>' +
        '<div class="preview-nav-children">' + innerHtml + '</div>' +
    '</div>';
}

function previewNavLeafHtml(key, label, offline) {
    return '<button type="button" class="preview-nav-leaf' + (offline ? ' offline' : '') +
        '" data-preview-key="' + escapeHtml(key) + '"' +
        (offline ? ' data-offline="1" title="' + escapeHtml(t('preview.offlineTitle')) + '"' : ' title="' + escapeHtml(t('preview.dblclick')) + '"') + '>' +
        '<span class="preview-nav-dot" aria-hidden="true"></span>' +
        '<span class="preview-nav-name">' + escapeHtml(label) + '</span>' +
        '</button>';
}

function renderPreviewNavTree(data) {
    const root = document.getElementById('previewNavTree');
    if (!root) return;
    data = data || {};
    const streams = Array.isArray(data.streams) ? data.streams : [];
    const devices = Array.isArray(data.devices) ? data.devices : [];
    const rtsp = streams.filter(function (s) { return normalizeAccessMethodClient(s) === 'rtsp_url'; });
    const onvif = streams.filter(function (s) { return normalizeAccessMethodClient(s) === 'onvif'; });
    previewNavLeafIndex = {};

    function registerStreamLeaf(stream) {
        const id = String(stream.id || '').trim();
        if (!id) return '';
        const key = previewWallKeyStream(id);
        const offline = !streamIsOnline(stream.status);
        previewNavLeafIndex[key] = {
            kind: 'stream',
            streamId: id,
            name: stream.name || id,
            offline: offline
        };
        return previewNavLeafHtml(key, stream.name || id, offline);
    }

    const rtspInner = rtsp.map(registerStreamLeaf).filter(Boolean).join('')
        || '<div class="preview-nav-empty">' + t('common.none') + '</div>';
    const onvifInner = onvif.map(registerStreamLeaf).filter(Boolean).join('')
        || '<div class="preview-nav-empty">' + t('common.none') + '</div>';

    const gbInner = devices.map(function (d) {
        const did = String(d.sip_user || d.device_id || '').trim();
        if (!did) return '';
        let chs = Array.isArray(d.channels) ? d.channels.slice() : [];
        if (!chs.length && d.channel_id) {
            chs = [{
                channel_id: d.channel_id,
                alias: d.name || d.channel_id,
                status: d.status || 'offline'
            }];
        }
        if (typeof normalizeGbChannelsClient === 'function') {
            chs = normalizeGbChannelsClient(chs);
        }
        const dOpen = previewNavDevExpand[did] === true
            || (previewNavDevExpand[did] !== false && chs.length > 0 && chs.length <= 6);
        const dOffline = String(d.status || '').toLowerCase() !== 'online';
        const chHtml = chs.map(function (ch) {
            const cid = String(ch.channel_id || '').trim();
            if (!cid) return '';
            const key = previewWallKeyGb(did, cid);
            const label = ch.alias || ch.name || cid;
            const offline = dOffline || String(ch.status || '').toLowerCase() === 'offline';
            previewNavLeafIndex[key] = {
                kind: 'gb',
                deviceId: did,
                channelId: cid,
                name: label,
                offline: offline
            };
            return previewNavLeafHtml(key, label, offline);
        }).filter(Boolean).join('') || '<div class="preview-nav-empty">' + t('preview.noChannels') + '</div>';
        return '<div class="preview-nav-group' + (dOpen ? ' open' : '') + '" data-device="' + escapeHtml(did) + '">' +
            '<button type="button" class="preview-nav-device' + (dOffline ? ' offline' : '') + '">' +
                '<span class="preview-nav-caret">' + (dOpen ? '▼' : '▶') + '</span>' +
                '<span class="preview-nav-dot" aria-hidden="true"></span>' +
                '<span class="preview-nav-name">' + escapeHtml(d.name || did) + '</span>' +
                '<span class="preview-nav-count">(' + chs.length + ')</span>' +
            '</button>' +
            '<div class="preview-nav-children">' + chHtml + '</div>' +
        '</div>';
    }).filter(Boolean).join('') || '<div class="preview-nav-empty">' + t('preview.noDevices') + '</div>';

    root.innerHTML =
        previewNavTypeGroupHtml('rtsp_url', t('access.method.rtsp_url'), rtspInner, rtsp.length) +
        previewNavTypeGroupHtml('onvif', t('access.method.onvif'), onvifInner, onvif.length) +
        previewNavTypeGroupHtml('gb28181', t('access.method.gb28181'), gbInner, devices.length);

    root.querySelectorAll('.preview-nav-type, .preview-nav-device').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            const group = this.closest('.preview-nav-group');
            if (!group) return;
            group.classList.toggle('open');
            const caret = this.querySelector('.preview-nav-caret');
            if (caret) caret.textContent = group.classList.contains('open') ? '▼' : '▶';
            const g = group.getAttribute('data-group');
            if (g) previewNavExpand[g] = group.classList.contains('open');
            const did = group.getAttribute('data-device');
            if (did) previewNavDevExpand[did] = group.classList.contains('open');
        });
    });
    root.querySelectorAll('.preview-nav-leaf[data-preview-key]').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
        });
        btn.addEventListener('dblclick', function (e) {
            e.preventDefault();
            e.stopPropagation();
            const key = this.getAttribute('data-preview-key') || '';
            const spec = previewNavLeafIndex[key];
            if (!spec) return;
            if (spec.offline || this.classList.contains('offline')) {
                showMessage(t('preview.offlineNoPreview', { name: spec.name || t('preview.thisChannel') }), 'error');
                return;
            }
            if (spec.kind === 'gb') startPreviewWallGb(spec.deviceId, spec.channelId, spec.name);
            else startPreviewWallStream(spec.streamId, spec.name);
        });
    });
    syncPreviewNavPlaying();
}

async function refreshPreviewNavTree() {
    const root = document.getElementById('previewNavTree');
    if (!root) return;
    try {
        const [streamsRes, gbRes] = await Promise.all([
            fetch('/api/streams'),
            fetch('/api/gb28181/devices').catch(function () { return null; })
        ]);
        const streams = await streamsRes.json();
        let devices = [];
        if (gbRes && gbRes.ok) {
            try {
                const gj = await gbRes.json();
                devices = (gj && gj.devices) || [];
            } catch (e) { devices = []; }
        }
        renderPreviewNavTree({
            streams: Array.isArray(streams) ? streams : [],
            devices: devices
        });
    } catch (e) {
        root.innerHTML = '<div class="preview-nav-empty">' + t('preview.loadFail') + '</div>';
    }
}

function schedulePreviewNavRefresh() {
    if (previewNavRefreshTimer) clearTimeout(previewNavRefreshTimer);
    previewNavRefreshTimer = setTimeout(function () {
        previewNavRefreshTimer = null;
        refreshPreviewNavTree();
    }, 200);
}

document.getElementById('previewWallClearBtn')?.addEventListener('click', function () {
    closeAllPreviewWall();
});

function resolveNavPageKey(pageKey, opts) {
    opts = opts || {};
    if (pageKey === 'video') pageKey = 'direct';
    if (ACCESS_TABS[pageKey]) {
        opts.tab = pageKey;
        pageKey = 'access';
    }
    if (pageKey === 'access' && opts.tab && ACCESS_TABS[opts.tab]) {
        currentAccessTab = opts.tab;
    }
    return pageKey;
}

/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* common.js */

function escapeHtml(text) {
    if (text == null || text === undefined) return '';
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

function streamIsOnline(status) {
    const s = String(status || '').trim();
    return s === 'online' || s === '在线';
}

let streamPreviewPc = null;
let streamPreviewHandle = null;
let streamPreviewStreamId = null;
let streamPreviewApp = '';
let streamPreviewName = '';
let gbPreviewSession = null;
let gbTalkPc = null;
let gbTalkMic = null;
let gbTalkActive = false;
let gbTalkBusy = false;
let gbPtzRepeatTimer = null;
let gbPtzActiveAction = '';
let gbPtzKeysDown = {};
let gbPtzKeyBound = false;
let detectionConfigTargetItem = null;
let detectionModalDraft = null;
let detectionFaceRecogDraft = null;
let detectionPlateRecogDraft = null;
let detectionFatigueDraft = null;

function defaultFaceRecogConfig() {
    return {
        trigger_types: ['known', 'unknown'],
        threshold: null,
        min_duration_sec: null,
        watchlist: [],
        rotate: null,
        genderage_enabled: false
    };
}

function defaultPlateRecogConfig() {
    return {
        trigger_types: ['known', 'unknown'],
        min_duration_sec: null,
        ocr_min_conf: null
    };
}

function defaultFatigueConfig() {
    return {
        preset: 'unlimited',
        pull_mode: 'always',
        pull_interval_sec: 0,
        window_mode: 'duration',
        window_duration_sec: 30,
        window_frames: 240,
        sample_fps: 8,
        ear_close: 0.18,
        perclos_pct: 0.40,
        yawn_count: 2,
        nod_deg: 22,
        observe_sec: 4,
        min_face_px: 80,
        alert_hold_sec: 2,
        cooldown_sec: 45,
        night_mode: false,
        bitrate_kbps: 800
    };
}

function normalizeFatigueConfigClient(raw) {
    const base = defaultFatigueConfig();
    if (!raw || typeof raw !== 'object') return base;
    Object.keys(base).forEach(function (k) {
        if (raw[k] != null && raw[k] !== '') base[k] = raw[k];
    });
    return base;
}

function fatigueTrafficText(cfg) {
    const fps = Math.max(1, parseFloat(cfg.sample_fps) || 8);
    let dur = parseFloat(cfg.window_duration_sec) || 30;
    if (cfg.window_mode === 'frames') {
        dur = (parseInt(cfg.window_frames, 10) || 40) / fps;
    }
    const pull = parseFloat(cfg.pull_interval_sec) || 0;
    const kbps = parseFloat(cfg.bitrate_kbps) || 800;
    let mbh;
    if (cfg.pull_mode === 'burst') {
        const cycle = dur + pull;
        mbh = (kbps * dur * (3600 / Math.max(cycle, 1))) / 8 / 1024;
    } else {
        mbh = (kbps * 3600) / 8 / 1024;
    }
    return t('policy.fatigueTraffic', { mbh: mbh.toFixed(1), kbps: kbps });
}

function normalizeFaceRecogConfigClient(raw) {
    const base = defaultFaceRecogConfig();
    if (!raw || typeof raw !== 'object') return base;
    const triggers = [];
    (raw.trigger_types || []).forEach(t => {
        const k = String(t).toLowerCase();
        if ((k === 'known' || k === 'unknown') && !triggers.includes(k)) triggers.push(k);
    });
    if (triggers.length) base.trigger_types = triggers;
    if (raw.threshold != null && raw.threshold !== '') base.threshold = raw.threshold;
    if (raw.min_duration_sec != null && raw.min_duration_sec !== '') base.min_duration_sec = raw.min_duration_sec;
    if (raw.rotate != null && raw.rotate !== '') base.rotate = parseInt(raw.rotate, 10);
    if (raw.genderage_enabled != null) {
        const v = raw.genderage_enabled;
        base.genderage_enabled = (v === true || v === 1 || v === '1' || String(v).toLowerCase() === 'true');
    }
    return base;
}

function normalizePlateRecogConfigClient(raw) {
    const base = defaultPlateRecogConfig();
    if (!raw || typeof raw !== 'object') return base;
    const triggers = [];
    (raw.trigger_types || []).forEach(t => {
        const k = String(t).toLowerCase();
        if ((k === 'known' || k === 'unknown') && !triggers.includes(k)) triggers.push(k);
    });
    if (triggers.length) base.trigger_types = triggers;
    if (raw.min_duration_sec != null && raw.min_duration_sec !== '') base.min_duration_sec = raw.min_duration_sec;
    if (raw.ocr_min_conf != null && raw.ocr_min_conf !== '') base.ocr_min_conf = raw.ocr_min_conf;
    return base;
}

function updateDetectionModalExtraClass() {
    const modal = document.getElementById('detectionConfigModal');
    if (!modal) return;
    const shown = ['faceRecogConfigPanel', 'plateRecogConfigPanel', 'fatigueConfigPanel'].some(function (id) {
        const el = document.getElementById(id);
        return el && el.style.display === 'block';
    });
    modal.classList.toggle('has-extra-panel', shown);
}

function syncFaceRecogPanelFromDraft() {
    const panel = document.getElementById('faceRecogConfigPanel');
    if (!panel || !detectionFaceRecogDraft) return;
    const on = !!(detectionModalDraft && detectionModalDraft.face_recognition);
    panel.style.display = on ? 'block' : 'none';
    updateDetectionModalExtraClass();
    if (!on) return;
    const tt = detectionFaceRecogDraft.trigger_types || [];
    document.getElementById('frTriggerKnown').checked = tt.includes('known');
    document.getElementById('frTriggerUnknown').checked = tt.includes('unknown');
    const gaEl = document.getElementById('frGenderAge');
    if (gaEl) gaEl.checked = !!detectionFaceRecogDraft.genderage_enabled;
    document.getElementById('frThreshold').value = detectionFaceRecogDraft.threshold != null ? String(detectionFaceRecogDraft.threshold) : '';
    document.getElementById('frMinDuration').value = detectionFaceRecogDraft.min_duration_sec != null ? String(detectionFaceRecogDraft.min_duration_sec) : '';
    const rotSel = document.getElementById('frRotate');
    if (rotSel) rotSel.value = detectionFaceRecogDraft.rotate != null ? String(detectionFaceRecogDraft.rotate) : '';
}

function syncPlateRecogPanelFromDraft() {
    const panel = document.getElementById('plateRecogConfigPanel');
    if (!panel || !detectionPlateRecogDraft) return;
    const on = !!(detectionModalDraft && detectionModalDraft.plate_recognition);
    panel.style.display = on ? 'block' : 'none';
    updateDetectionModalExtraClass();
    if (!on) return;
    const tt = detectionPlateRecogDraft.trigger_types || [];
    document.getElementById('prTriggerKnown').checked = tt.includes('known');
    document.getElementById('prTriggerUnknown').checked = tt.includes('unknown');
    document.getElementById('prOcrMinConf').value = detectionPlateRecogDraft.ocr_min_conf != null ? String(detectionPlateRecogDraft.ocr_min_conf) : '';
    document.getElementById('prMinDuration').value = detectionPlateRecogDraft.min_duration_sec != null ? String(detectionPlateRecogDraft.min_duration_sec) : '';
}

function syncFatiguePanelFromDraft() {
    const panel = document.getElementById('fatigueConfigPanel');
    if (!panel || !detectionFatigueDraft) return;
    const on = !!(detectionModalDraft && detectionModalDraft.fatigue_driving);
    panel.style.display = on ? 'block' : 'none';
    updateDetectionModalExtraClass();
    if (!on) return;
    const d = detectionFatigueDraft;
    const set = function (id, v) {
        const el = document.getElementById(id);
        if (el) el.value = v == null ? '' : String(v);
    };
    if (document.getElementById('fgPullMode')) document.getElementById('fgPullMode').value = d.pull_mode || 'always';
    set('fgPullInterval', d.pull_interval_sec);
    if (document.getElementById('fgWindowMode')) document.getElementById('fgWindowMode').value = d.window_mode || 'duration';
    set('fgWindowSec', d.window_duration_sec);
    set('fgWindowFrames', d.window_frames);
    set('fgSampleFps', d.sample_fps);
    set('fgEarClose', d.ear_close);
    set('fgPerclos', d.perclos_pct);
    set('fgYawn', d.yawn_count);
    set('fgObserve', d.observe_sec);
    set('fgMinFace', d.min_face_px);
    set('fgNodDeg', d.nod_deg);
    set('fgCooldown', d.cooldown_sec);
    set('fgBitrate', d.bitrate_kbps);
    const night = document.getElementById('fgNight');
    if (night) night.checked = !!d.night_mode;
    const hint = document.getElementById('fatigueTrafficHint');
    if (hint) hint.textContent = fatigueTrafficText(d);
    const gate = document.getElementById('fatigueGateHint');
    const st = detectionConfigTargetItem && detectionConfigTargetItem._dms_status;
    if (gate && st) {
        const ok = st.supported === true;
        const pending = st.supported == null;
        gate.style.color = ok ? '#2b8a3e' : (pending ? '#6c757d' : '#c92a2a');
        gate.textContent = (st.reason_zh || '') +
            (st.max_face_px ? t('policy.facePx', { px: st.max_face_px }) : '');
    }
}

function readFatiguePanelToDraft() {
    if (!detectionFatigueDraft) detectionFatigueDraft = defaultFatigueConfig();
    const num = function (id) {
        const el = document.getElementById(id);
        if (!el) return null;
        const t = el.value.trim();
        if (t === '') return null;
        const n = parseFloat(t);
        return Number.isFinite(n) ? n : null;
    };
    const d = detectionFatigueDraft;
    d.preset = 'custom';
    const pm = document.getElementById('fgPullMode');
    if (pm) d.pull_mode = pm.value;
    const wm = document.getElementById('fgWindowMode');
    if (wm) d.window_mode = wm.value;
    const pi = num('fgPullInterval'); if (pi != null) d.pull_interval_sec = pi;
    const ws = num('fgWindowSec'); if (ws != null) d.window_duration_sec = ws;
    const wf = num('fgWindowFrames'); if (wf != null) d.window_frames = wf;
    const sf = num('fgSampleFps'); if (sf != null) d.sample_fps = sf;
    const ec = num('fgEarClose'); if (ec != null) d.ear_close = ec;
    const pc = num('fgPerclos'); if (pc != null) d.perclos_pct = pc;
    const yc = num('fgYawn'); if (yc != null) d.yawn_count = yc;
    const ob = num('fgObserve'); if (ob != null) d.observe_sec = ob;
    const mf = num('fgMinFace'); if (mf != null) d.min_face_px = mf;
    const nd = num('fgNodDeg'); if (nd != null) d.nod_deg = nd;
    const cd = num('fgCooldown'); if (cd != null) d.cooldown_sec = cd;
    const br = num('fgBitrate'); if (br != null) d.bitrate_kbps = br;
    const night = document.getElementById('fgNight');
    d.night_mode = !!(night && night.checked);
    const hint = document.getElementById('fatigueTrafficHint');
    if (hint) hint.textContent = fatigueTrafficText(d);
}

function readFaceRecogPanelToDraft() {
    if (!detectionFaceRecogDraft) detectionFaceRecogDraft = defaultFaceRecogConfig();
    const triggers = [];
    if (document.getElementById('frTriggerKnown').checked) triggers.push('known');
    if (document.getElementById('frTriggerUnknown').checked) triggers.push('unknown');
    if (triggers.length) detectionFaceRecogDraft.trigger_types = triggers;
    const gaEl = document.getElementById('frGenderAge');
    detectionFaceRecogDraft.genderage_enabled = !!(gaEl && gaEl.checked);
    const thr = document.getElementById('frThreshold').value.trim();
    detectionFaceRecogDraft.threshold = thr ? parseFloat(thr) : null;
    const dur = document.getElementById('frMinDuration').value.trim();
    detectionFaceRecogDraft.min_duration_sec = dur ? parseFloat(dur) : null;
    const rot = document.getElementById('frRotate').value.trim();
    detectionFaceRecogDraft.rotate = rot ? parseInt(rot, 10) : null;
}

function readPlateRecogPanelToDraft() {
    if (!detectionPlateRecogDraft) detectionPlateRecogDraft = defaultPlateRecogConfig();
    const triggers = [];
    if (document.getElementById('prTriggerKnown').checked) triggers.push('known');
    if (document.getElementById('prTriggerUnknown').checked) triggers.push('unknown');
    if (triggers.length) detectionPlateRecogDraft.trigger_types = triggers;
    const oc = document.getElementById('prOcrMinConf').value.trim();
    detectionPlateRecogDraft.ocr_min_conf = oc ? parseFloat(oc) : null;
    const dur = document.getElementById('prMinDuration').value.trim();
    detectionPlateRecogDraft.min_duration_sec = dur ? parseFloat(dur) : null;
}

function waitIceGatheringComplete(pc, timeoutMs) {
    return new Promise(function (resolve) {
        if (pc.iceGatheringState === 'complete') {
            resolve();
            return;
        }
        var t = setTimeout(function () { resolve(); }, timeoutMs || 2500);
        pc.addEventListener('icegatheringstatechange', function onIce() {
            if (pc.iceGatheringState === 'complete') {
                clearTimeout(t);
                pc.removeEventListener('icegatheringstatechange', onIce);
                resolve();
            }
        });
    });
}

function stopStreamPreviewPipeline() {
    if (streamPreviewHandle) {
        try { streamPreviewHandle.stop(); } catch (e) { /* ignore */ }
        streamPreviewHandle = null;
        streamPreviewPc = null;
        return;
    }
    if (streamPreviewPc) {
        try {
            if (streamPreviewPc._visionaiIceTimer) {
                clearTimeout(streamPreviewPc._visionaiIceTimer);
            }
            streamPreviewPc.close();
        } catch (e) { /* ignore */ }
        streamPreviewPc = null;
    }
    const vid = document.getElementById('streamPreviewVideo');
    if (vid) {
        vid.pause();
        vid.removeAttribute('src');
        if (vid.srcObject) vid.srcObject = null;
        vid.load();
    }
}

function startWebrtcPlay(videoEl, streamId, opts) {
    opts = opts || {};
    const handle = { pc: null, stopped: false, iceTimer: null };
    handle.stop = function () {
        handle.stopped = true;
        if (handle.iceTimer) {
            clearTimeout(handle.iceTimer);
            handle.iceTimer = null;
        }
        if (handle.pc) {
            try { handle.pc.close(); } catch (e) { /* ignore */ }
            handle.pc = null;
        }
        if (videoEl) {
            try { videoEl.pause(); } catch (e) { /* ignore */ }
            videoEl.removeAttribute('src');
            if (videoEl.srcObject) videoEl.srcObject = null;
            try { videoEl.load(); } catch (e) { /* ignore */ }
        }
    };
    if (!videoEl || !streamId) return handle;
    videoEl.muted = true;
    const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });
    handle.pc = pc;
    let gotTrack = false;
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });
    pc.ontrack = function (ev) {
        if (handle.stopped) return;
        gotTrack = true;
        if (typeof opts.onPlaying === 'function') opts.onPlaying();
        if (ev.streams && ev.streams[0]) {
            videoEl.srcObject = ev.streams[0];
        } else {
            const ms = videoEl.srcObject instanceof MediaStream ? videoEl.srcObject : new MediaStream();
            ms.addTrack(ev.track);
            videoEl.srcObject = ms;
        }
        videoEl.play().then(function () {
            videoEl.muted = false;
            return videoEl.play().catch(function () { videoEl.muted = true; });
        }).catch(function () {});
    };
    pc.onconnectionstatechange = function () {
        if (handle.stopped) return;
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
            if (typeof opts.onError === 'function') opts.onError(t('msg.webrtcIce'));
            else showMessage(t('msg.webrtcIce'), 'error');
        }
    };
    const app = opts.app || '';
    pc.createOffer()
        .then(function (offer) { return pc.setLocalDescription(offer); })
        .then(function () { return waitIceGatheringComplete(pc); })
        .then(function () {
            if (handle.stopped) return { skipped: true };
            const webrtcBody = {
                stream_id: streamId,
                sdp: pc.localDescription.sdp,
                type: 'offer',
            };
            if (app === 'rtp') {
                webrtcBody.app = 'rtp';
                webrtcBody.stream = streamId;
            }
            const postWebrtc = function () {
                return fetch('/api/zlm/webrtc/play', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(webrtcBody),
                });
            };
            if (app !== 'rtp') return postWebrtc();
            const retry = function (left) {
                return postWebrtc().then(function (r) {
                    return r.json().then(function (data) {
                        if (r.ok && data && data.success) {
                            return { ok: true, data: data, _done: true };
                        }
                        const msg = (data && data.message) || '';
                        if (left > 0 && msg.indexOf('国标媒体未上线') >= 0) {
                            return new Promise(function (resolve) {
                                setTimeout(function () { resolve(retry(left - 1)); }, 1500);
                            });
                        }
                        return { ok: r.ok, data: data, _done: true };
                    });
                });
            };
            return retry(4);
        })
        .then(function (r) {
            if (!r || r.skipped || handle.stopped) return null;
            if (r && r._done) return { ok: r.ok, data: r.data };
            return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        })
        .then(function (res) {
            if (!res || handle.stopped) return;
            if (!res.data || !res.data.success || !res.data.sdp) {
                const msg = (res.data && res.data.message) || 'ZLM WebRTC 协商失败（请确认 ZLM 已启用）';
                if (typeof opts.onError === 'function') opts.onError(msg);
                else showMessage(msg, 'error');
                return;
            }
            return pc.setRemoteDescription({ type: 'answer', sdp: res.data.sdp }).then(function () {
                handle.iceTimer = setTimeout(function () {
                    if (!gotTrack && !handle.stopped) {
                        const msg = 'ZLM WebRTC 未收到媒体。请确认 zlmediakit 运行且 directProxy=0';
                        if (typeof opts.onError === 'function') opts.onError(msg);
                        else showMessage(msg, 'error');
                    }
                }, 8000);
            });
        })
        .catch(function (err) {
            if (handle.stopped) return;
            console.warn(err);
            const msg = (err && err.message) ? String(err.message) : 'ZLM WebRTC 预览失败';
            if (typeof opts.onError === 'function') opts.onError(msg);
            else showMessage(t('msg.webrtcFail', { err: msg }), 'error');
        });
    return handle;
}

function rebuildStreamPreview() {
    const sid = streamPreviewStreamId;
    if (!sid) return;
    const vid = document.getElementById('streamPreviewVideo');
    if (!vid) return;
    stopStreamPreviewPipeline();
    const handle = startWebrtcPlay(vid, sid, { app: streamPreviewApp });
    streamPreviewPc = handle.pc;
    streamPreviewHandle = handle;
}

function openStreamPreview(streamId, streamName, opts) {
    opts = opts || {};
    if (!streamId) {
        showMessage(t('msg.needStreamId'), 'error');
        return;
    }
    const modal = document.getElementById('streamPreviewModal');
    if (!modal) {
        showMessage(t('msg.previewMissing'), 'error');
        return;
    }
    const titleEl = document.getElementById('streamPreviewTitle');
    if (titleEl) {
        titleEl.textContent = streamName ? t('msg.previewTitle', { name: streamName }) : t('msg.streamPreview');
    }
    streamPreviewStreamId = streamId;
    streamPreviewApp = opts.app || '';
    streamPreviewName = streamName || '';
    gbPreviewSession = opts.gbPreview || null;
    setGbTalkBtnVisible(!!gbPreviewSession);
    setGbPtzPadVisible(!!gbPreviewSession);
    rebuildStreamPreview();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
}

function previewSnapshotBasename() {
    const raw = streamPreviewName || streamPreviewStreamId || 'preview';
    const cleaned = String(raw).replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, '_').replace(/_+/g, '_');
    return (cleaned.slice(0, 80) || 'preview');
}

function previewSnapshotStamp() {
    const d = new Date();
    const p = function (n) { return String(n).padStart(2, '0'); };
    return String(d.getFullYear()) + p(d.getMonth() + 1) + p(d.getDate())
        + '_' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
}

function captureStreamPreview() {
    const vid = document.getElementById('streamPreviewVideo');
    if (!vid || vid.readyState < 2 || !vid.videoWidth || !vid.videoHeight) {
        showMessage(t('msg.snapNotReady'), 'error');
        return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = vid.videoWidth;
    canvas.height = vid.videoHeight;
    let ctx;
    try {
        ctx = canvas.getContext('2d');
        ctx.drawImage(vid, 0, 0, canvas.width, canvas.height);
    } catch (e) {
        showMessage(t('msg.snapReadFail'), 'error');
        return;
    }
    const filename = previewSnapshotBasename() + '_' + previewSnapshotStamp() + '.jpg';
    const fail = function () { showMessage(t('msg.snapSaveFail'), 'error'); };
    try {
        canvas.toBlob(function (blob) {
            if (!blob) {
                fail();
                return;
            }
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
            showMessage(t('msg.snapSaved', { name: filename }), 'success');
        }, 'image/jpeg', 0.92);
    } catch (e) {
        fail();
    }
}

function gbTalkStreamId(sess) {
    if (!sess || !sess.device_id || !sess.channel_id) return '';
    return String(sess.device_id) + '_' + String(sess.channel_id);
}

function setGbTalkBtnVisible(on) {
    const btn = document.getElementById('streamPreviewTalkBtn');
    if (!btn) return;
    if (on) btn.removeAttribute('hidden');
    else btn.setAttribute('hidden', '');
    if (!on) stopGbTalk(true);
}

function setGbTalkBtnState(active) {
    const btn = document.getElementById('streamPreviewTalkBtn');
    if (!btn) return;
    btn.classList.toggle('is-talking', !!active);
    btn.textContent = active ? t('msg.stopTalk') : t('msg.mic');
}

function stopGbTalkPush() {
    if (gbTalkPc) {
        try { gbTalkPc.close(); } catch (e) { /* ignore */ }
        gbTalkPc = null;
    }
    if (gbTalkMic) {
        gbTalkMic.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* ignore */ } });
        gbTalkMic = null;
    }
}

function stopGbTalk(silent) {
    const sess = gbPreviewSession;
    const was = gbTalkActive;
    gbTalkActive = false;
    gbTalkBusy = false;
    setGbTalkBtnState(false);
    stopGbTalkPush();
    if (!was || !sess || !sess.device_id || !sess.channel_id) {
        return Promise.resolve();
    }
    return fetch('/api/gb28181/devices/' + encodeURIComponent(sess.device_id) +
        '/channels/' + encodeURIComponent(sess.channel_id) + '/broadcast/stop', { method: 'POST' })
        .catch(function () {})
        .then(function () {
            if (!silent) showMessage(t('msg.talkStopped'), 'success');
        });
}

async function startGbTalk() {
    const sess = gbPreviewSession;
    if (!sess || !sess.device_id || !sess.channel_id) {
        showMessage(t('msg.talkGbOnly'), 'error');
        return;
    }
    if (gbTalkBusy) return;
    gbTalkBusy = true;
    setGbTalkBtnState(true);
    const streamId = gbTalkStreamId(sess) + '_' + Date.now();
    try {
        gbTalkMic = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                channelCount: 1
            },
            video: false
        });
        const pc = new RTCPeerConnection({ iceServers: [] });
        gbTalkPc = pc;
        gbTalkMic.getAudioTracks().forEach(function (t) { pc.addTrack(t, gbTalkMic); });
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitIceGatheringComplete(pc, 400);
        const r = await fetch('/api/zlm/webrtc/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                app: 'broadcast',
                stream: streamId,
                stream_id: streamId,
                sdp: pc.localDescription.sdp,
                type: 'offer'
            })
        });
        const j = await fetchJsonOrThrow(r);
        if (!j.success || !j.sdp) throw new Error(j.message || 'ZLM 推流协商失败');
        await pc.setRemoteDescription({ type: 'answer', sdp: j.sdp });
        const br = await fetch('/api/gb28181/devices/' + encodeURIComponent(sess.device_id) +
            '/channels/' + encodeURIComponent(sess.channel_id) + '/broadcast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ app: 'broadcast', stream: streamId })
            });
        const bj = await fetchJsonOrThrow(br);
        if (!bj.success) throw new Error(bj.message || 'Broadcast 失败');
        gbTalkActive = true;
        gbTalkBusy = false;
        showMessage(t('msg.talkOn'), 'success');
    } catch (e) {
        gbTalkBusy = false;
        gbTalkActive = false;
        setGbTalkBtnState(false);
        stopGbTalkPush();
        showMessage(t('msg.talkFail', { err: (e.message || e) }), 'error');
    }
}

async function toggleGbTalk() {
    if (gbTalkActive || gbTalkBusy) await stopGbTalk(false);
    else await startGbTalk();
}

function gbPtzSpeed() {
    const el = document.getElementById('gbPtzSpeed');
    const n = el ? parseInt(el.value, 10) : 4;
    return Number.isFinite(n) ? n : 4;
}

function gbPtzPayload(action) {
    return { action: action, speed: gbPtzSpeed() };
}

function gbPtzSend(action, silent) {
    const sess = gbPreviewSession;
    if (!sess || !sess.device_id || !sess.channel_id || !action) return;
    fetch('/api/gb28181/devices/' + encodeURIComponent(sess.device_id) +
        '/channels/' + encodeURIComponent(sess.channel_id) + '/ptz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(gbPtzPayload(action))
        })
        .then(function (r) { return fetchJsonOrThrow(r); })
        .then(function (j) {
            if (!j.success && !silent) showMessage(j.message || t('msg.ptzFail'), 'error');
        })
        .catch(function (e) {
            if (!silent) showMessage(t('msg.ptzFail') + ': ' + (e.message || e), 'error');
        });
}

function gbPtzHoldStop() {
    if (gbPtzRepeatTimer) {
        clearInterval(gbPtzRepeatTimer);
        gbPtzRepeatTimer = null;
    }
    if (gbPtzActiveAction && gbPtzActiveAction !== 'stop') {
        gbPtzSend('stop');
    }
    gbPtzActiveAction = '';
}

function gbPtzHoldStart(action) {
    if (!action) return;
    if (action === 'stop') {
        gbPtzHoldStop();
        gbPtzSend('stop');
        return;
    }
    if (gbPtzActiveAction === action && gbPtzRepeatTimer) return;
    gbPtzHoldStop();
    gbPtzActiveAction = action;
    gbPtzSend(action);
    gbPtzRepeatTimer = setInterval(function () { gbPtzSend(action); }, 320);
}

function gbPtzActionFromKeys() {
    const u = !!gbPtzKeysDown.ArrowUp;
    const d = !!gbPtzKeysDown.ArrowDown;
    const l = !!gbPtzKeysDown.ArrowLeft;
    const r = !!gbPtzKeysDown.ArrowRight;
    if (u && l) return 'upleft';
    if (u && r) return 'upright';
    if (d && l) return 'downleft';
    if (d && r) return 'downright';
    if (u) return 'up';
    if (d) return 'down';
    if (l) return 'left';
    if (r) return 'right';
    if (gbPtzKeysDown.zoom_in) return 'zoom_in';
    if (gbPtzKeysDown.zoom_out) return 'zoom_out';
    return '';
}

function gbPtzOnKeyDown(e) {
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
    if (!gbPreviewSession) return;
    let key = e.key;
    if (key === '+' || key === '=') key = 'zoom_in';
    if (key === '-' || key === '_') key = 'zoom_out';
    const map = {
        ArrowUp: 1, ArrowDown: 1, ArrowLeft: 1, ArrowRight: 1,
        zoom_in: 1, zoom_out: 1
    };
    if (!map[key]) return;
    e.preventDefault();
    if (gbPtzKeysDown[key]) return;
    gbPtzKeysDown[key] = true;
    gbPtzHoldStart(gbPtzActionFromKeys());
}

function gbPtzOnKeyUp(e) {
    let key = e.key;
    if (key === '+' || key === '=') key = 'zoom_in';
    if (key === '-' || key === '_') key = 'zoom_out';
    if (!gbPtzKeysDown[key]) return;
    delete gbPtzKeysDown[key];
    const next = gbPtzActionFromKeys();
    if (next) gbPtzHoldStart(next);
    else gbPtzHoldStop();
}

function setGbPtzPadVisible(on) {
    const modal = document.getElementById('streamPreviewModal');
    const pad = document.getElementById('gbPtzPad');
    if (modal) modal.classList.toggle('has-gb-ptz', !!on);
    if (pad) {
        if (on) pad.removeAttribute('hidden');
        else pad.setAttribute('hidden', '');
    }
    if (on && !gbPtzKeyBound) {
        window.addEventListener('keydown', gbPtzOnKeyDown);
        window.addEventListener('keyup', gbPtzOnKeyUp);
        gbPtzKeyBound = true;
    }
    if (!on) {
        gbPtzHoldStop();
        gbPtzKeysDown = {};
        if (gbPtzKeyBound) {
            window.removeEventListener('keydown', gbPtzOnKeyDown);
            window.removeEventListener('keyup', gbPtzOnKeyUp);
            gbPtzKeyBound = false;
        }
    }
}

function releaseGbPreview() {
    const sess = gbPreviewSession;
    gbPreviewSession = null;
    if (!sess || !sess.bye_on_close || !sess.device_id || !sess.channel_id) return;
    fetch('/api/gb28181/devices/' + encodeURIComponent(sess.device_id) +
        '/channels/' + encodeURIComponent(sess.channel_id) + '/bye', { method: 'POST' })
        .catch(function () {});
}

function closeStreamPreview() {
    gbPtzHoldStop();
    if (gbPreviewSession) gbPtzSend('stop', true);
    stopGbTalk(true);
    setGbTalkBtnVisible(false);
    setGbPtzPadVisible(false);
    stopStreamPreviewPipeline();
    streamPreviewStreamId = null;
    streamPreviewApp = '';
    streamPreviewName = '';
    releaseGbPreview();
    const modal = document.getElementById('streamPreviewModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
}

function safeCloseModalsForNav() {
    try {
        gbPtzHoldStop();
        if (gbPreviewSession) gbPtzSend('stop', true);
        stopGbTalk(true);
        setGbTalkBtnVisible(false);
        setGbPtzPadVisible(false);
    } catch (err) { /* ignore */ }
    try {
        stopStreamPreviewPipeline();
    } catch (err) {
        console.warn('stopStreamPreviewPipeline', err);
    }
    streamPreviewStreamId = null;
    streamPreviewApp = '';
    streamPreviewName = '';
    releaseGbPreview();
    const spm = document.getElementById('streamPreviewModal');
    if (spm) {
        spm.classList.remove('show');
        spm.setAttribute('aria-hidden', 'true');
    }
    const dcm = document.getElementById('detectionConfigModal');
    if (dcm) {
        dcm.classList.remove('show');
        dcm.setAttribute('aria-hidden', 'true');
    }
    detectionConfigTargetItem = null;
    detectionModalDraft = null;
    const im = document.getElementById('imageModal');
    if (im) {
        im.style.display = 'none';
    }
}

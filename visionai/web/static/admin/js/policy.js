/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* policy.js */

async function loadDetectionCatalog() {
    try {
        const response = await fetch('/api/detection-catalog');
        detectionCatalog = await response.json();
        window.detectionCatalog = detectionCatalog;
        const el = document.getElementById('detectionCapabilityCount');
        if (el && Array.isArray(detectionCatalog)) {
            el.textContent = String(detectionCatalog.length);
        }
        fillAlertFilterTypeOptions();
    } catch (e) {
        console.error(e);
        detectionCatalog = [];
    }
}

function fillAlertFilterTypeOptions() {
    const sel = document.getElementById('alertFilterType');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">' + t('alerts.allTypes') + '</option>';
    if (detectionCatalog && detectionCatalog.length) {
        detectionCatalog.forEach(item => {
            const o = document.createElement('option');
            o.value = item.name_zh;
            o.textContent = catalogLabel(item);
            sel.appendChild(o);
        });
    }
    if (cur && [...sel.options].some(o => o.value === cur)) {
        sel.value = cur;
    }
}

async function ensureAlertFilterStreamsSelect() {
    const sel = document.getElementById('alertFilterStream');
    if (!sel) return;
    const cur = sel.value;
    try {
        const r = await fetch('/api/streams');
        const streams = await r.json();
        sel.innerHTML = '<option value="">' + t('alerts.allVideos') + '</option>';
        (streams || []).forEach(s => {
            if (!s.id) return;
            const o = document.createElement('option');
            o.value = s.id;
            o.textContent = s.name || s.id;
            sel.appendChild(o);
        });
        if (cur && [...sel.options].some(o => o.value === cur)) {
            sel.value = cur;
        }
    } catch (e) {
        console.error(e);
    }
}

function buildAlertsQueryParams(page) {
    const offset = (page - 1) * itemsPerPage;
    const params = new URLSearchParams();
    params.set('limit', String(itemsPerPage));
    params.set('offset', String(offset));
    const st = document.getElementById('alertFilterStart');
    const en = document.getElementById('alertFilterEnd');
    const sid = document.getElementById('alertFilterStream');
    const tp = document.getElementById('alertFilterType');
    if (st && st.value) params.set('start', st.value);
    if (en && en.value) params.set('end', en.value);
    if (sid && sid.value) params.set('stream_id', sid.value);
    if (tp && tp.value) params.set('detection_type', tp.value);
    return params;
}

function updateStreamDetectionSummary(streamItem) {
    const summaryEl = streamItem.querySelector('.stream-detection-summary');
    if (!summaryEl || !streamItem._detections) return;
    const d = streamItem._detections;
    const enabled = [];
    detectionCatalog.forEach(item => {
        if (d[item.key]) {
            enabled.push(`${catalogLabel(item)}${item.class_id !== null && item.class_id !== undefined ? ' (#' + item.class_id + ')' : ''}`);
        }
    });
    const total = detectionCatalog.length;
    const n = enabled.length;
    if (!n) {
        summaryEl.innerHTML = '<strong style="color:#c92a2a;">' + t('policy.noTypes') + '</strong>';
        return;
    }
    let extra = '';
    if (d.fatigue_driving && streamItem._dms_status) {
        const st = streamItem._dms_status;
        const col = st.supported === true ? '#2b8a3e' : (st.supported == null ? '#868e96' : '#c92a2a');
        extra = `<br><span style="color:${col}">${t('policy.fatigueGate', { reason: escapeHtml(st.reason_zh || t('common.loading')) })}</span>`;
    }
    summaryEl.innerHTML = `<strong>${t('policy.enabledN', { n: n, total: total })}</strong>${t('policy.supported')}` +
        `：<span style="color:#212529">${enabled.slice(0, 12).join('、')}${enabled.length > 12 ? '…' : ''}</span>` + extra;
}

function renderDetectionModalList(filterText) {
    const list = document.getElementById('detectionConfigList');
    if (!list || !detectionModalDraft) return;
    const q = (filterText || '').trim().toLowerCase();
    list.innerHTML = '';
    const groups = [
        { id: 'coco', title: t('policy.groupCoco'), match: (it) => it.source === 'coco' },
        { id: 'builtin', title: t('policy.groupBuiltin'), match: (it) => it.source === 'builtin' },
        { id: 'specialist', title: t('policy.groupSpec'), match: (it) => it.source === 'specialist' },
    ];
    const appendItem = (item) => {
        const hay = (item.name_zh + ' ' + item.name_en + ' ' + item.key).toLowerCase();
        if (q && !hay.includes(q)) return;
        const row = document.createElement('div');
        row.className = 'config-modal-item';
        const checked = !!detectionModalDraft[item.key];
        const isSpec = item.source === 'specialist';
        const delBtn = isSpec && item.deletable
            ? `<button type="button" class="btn-specialist-delete" data-specialist-key="${item.key}" title="${escapeHtml(t('policy.delSpec'))}" style="margin-right:8px;padding:4px 8px;font-size:12px;">${t('common.delete')}</button>`
            : '';
        const mainName = catalogLabel(item);
        const otherName = (window.VisionAI && VisionAI.i18n.getLocale() === 'en')
            ? (item.name_zh || '')
            : (item.name_en || '');
        row.innerHTML = `
            <div style="flex:1;min-width:0;">
                <div class="switch-name">${escapeHtml(mainName)}${isSpec ? ' <span style="background:#e7f5ff;color:#1971c2;padding:1px 6px;border-radius:4px;font-size:11px;">' + t('policy.specTag') + '</span>' : ''} <span style="color:#868e96;font-weight:400;">/ ${escapeHtml(otherName)}</span></div>
                <div class="detection-key-hint">${isSpec ? ((item.origin === 'imported') ? t('policy.imported') : t('policy.trained')) : t('policy.sysDetect')} · ${t('policy.keyHint', { key: item.key })}${item.class_id !== null && item.class_id !== undefined ? ' · COCO #' + item.class_id : ''}</div>
            </div>
            ${delBtn}
            <label class="switch" style="flex-shrink:0;">
                <input type="checkbox" data-detection-key="${item.key}" class="detection-modal-toggle" ${checked ? 'checked' : ''}>
                <span class="slider"></span>
            </label>
        `;
        list.appendChild(row);
    };
    groups.forEach((g) => {
        const items = detectionCatalog.filter(g.match);
        if (!items.length) return;
        const anyVisible = items.some((item) => {
            const hay = (item.name_zh + ' ' + item.name_en + ' ' + item.key).toLowerCase();
            return !q || hay.includes(q);
        });
        if (!anyVisible) return;
        const head = document.createElement('div');
        head.style.cssText = 'padding:10px 4px 4px;font-size:12px;font-weight:600;color:#495057;border-bottom:1px solid #e9ecef;margin-top:8px;';
        head.textContent = g.title;
        list.appendChild(head);
        items.forEach(appendItem);
    });
    list.querySelectorAll('.btn-specialist-delete').forEach(btn => {
        btn.addEventListener('click', async function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            const key = this.getAttribute('data-specialist-key');
            if (!key) return;
            if (!window.confirm(t('policy.delSpecConfirm', { key: key }))) return;
            try {
                const resp = await fetch('/api/training/specialists/' + encodeURIComponent(key), {
                    method: 'DELETE',
                    credentials: 'same-origin',
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    alert(data.message || t('policy.delSpecFail'));
                    return;
                }
                if (detectionModalDraft) delete detectionModalDraft[key];
                await loadDetectionCatalog();
                renderDetectionModalList(document.getElementById('detectionConfigSearch').value);
            } catch (e) {
                alert(t('policy.delSpecFail') + ': ' + e);
            }
        });
    });
    list.querySelectorAll('.detection-modal-toggle').forEach(cb => {
        cb.addEventListener('change', function() {
            const key = this.getAttribute('data-detection-key');
            if (key && detectionModalDraft) {
                detectionModalDraft[key] = this.checked;
                if (key === 'face_recognition') syncFaceRecogPanelFromDraft();
                if (key === 'plate_recognition') syncPlateRecogPanelFromDraft();
                if (key === 'fatigue_driving') syncFatiguePanelFromDraft();
            }
        });
    });
    syncFaceRecogPanelFromDraft();
    syncPlateRecogPanelFromDraft();
    syncFatiguePanelFromDraft();
}

function openDetectionConfig(button) {
    const streamItem = button.closest('.stream-item');
    if (!streamItem || !streamItem._detections) return;
    detectionConfigTargetItem = streamItem;
    detectionModalDraft = JSON.parse(JSON.stringify(streamItem._detections));
    detectionFaceRecogDraft = JSON.parse(JSON.stringify(streamItem._face_recognition_config || defaultFaceRecogConfig()));
    detectionPlateRecogDraft = JSON.parse(JSON.stringify(streamItem._plate_recognition_config || defaultPlateRecogConfig()));
    detectionFatigueDraft = JSON.parse(JSON.stringify(streamItem._fatigue_driving_config || defaultFatigueConfig()));
    document.getElementById('detectionConfigSearch').value = '';
    renderDetectionModalList('');
    document.getElementById('detectionConfigModal').classList.add('show');
    document.getElementById('detectionConfigModal').setAttribute('aria-hidden', 'false');
}

function closeDetectionConfigModal() {
    const el = document.getElementById('detectionConfigModal');
    if (el) {
        el.classList.remove('show');
        el.setAttribute('aria-hidden', 'true');
    }
    detectionConfigTargetItem = null;
    detectionModalDraft = null;
    detectionFaceRecogDraft = null;
    detectionPlateRecogDraft = null;
    detectionFatigueDraft = null;
}

// 获取配置
async function fetchConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        configRefreshInterval = (config.auto_refresh_interval || 20) * 1000;
        if (config.timezone) appTimezone = String(config.timezone);
    } catch (error) {
        console.error('获取配置失败:', error);
    }
}

var intrusionZoneEdit = null;

function defaultIntrusionZone() {
    return { regions: [], schedule_all: true, schedule: null };
}

function normalizeIntrusionZoneClient(raw) {
    const z = raw && typeof raw === 'object' ? raw : {};
    const regions = [];
    (Array.isArray(z.regions) ? z.regions : []).forEach(function (reg) {
        const pts = [];
        const src = reg && Array.isArray(reg.points) ? reg.points : [];
        src.forEach(function (p) {
            if (!Array.isArray(p) || p.length < 2) return;
            const x = Number(p[0]);
            const y = Number(p[1]);
            if (!Number.isFinite(x) || !Number.isFinite(y)) return;
            if (x < 0 || x > 1 || y < 0 || y > 1) return;
            pts.push([Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000]);
        });
        if (pts.length >= 3 && regions.length < 8) regions.push({ points: pts.slice(0, 32) });
    });
    let scheduleAll = z.schedule_all !== false;
    let schedule = null;
    if (!scheduleAll && Array.isArray(z.schedule) && z.schedule.length === 7) {
        schedule = z.schedule.map(function (row) {
            if (!Array.isArray(row) || row.length !== 24) return null;
            return row.map(function (v) { return !!v; });
        });
        if (schedule.some(function (row) { return !row; })) {
            scheduleAll = true;
            schedule = null;
        }
    } else if (!scheduleAll) {
        scheduleAll = true;
    }
    return { regions: regions, schedule_all: scheduleAll, schedule: schedule };
}

function blankSchedule(on) {
    const rows = [];
    for (let d = 0; d < 7; d++) {
        const row = [];
        for (let h = 0; h < 24; h++) row.push(!!on);
        rows.push(row);
    }
    return rows;
}

function updateStreamZoneSummary(streamItem) {
    if (!streamItem) return;
    const el = streamItem.querySelector('.stream-zone-summary');
    if (!el) return;
    const z = streamItem._intrusion_zone || defaultIntrusionZone();
    const n = (z.regions || []).length;
    if (!n) {
        el.textContent = t('policy.zoneNone');
        return;
    }
    el.textContent = t('policy.zoneN', { n: n }) + (z.schedule_all === false ? t('policy.zoneTimed') : '');
}

function drawIntrusionZone() {
    const canvas = document.getElementById('intrusionZoneCanvas');
    const edit = intrusionZoneEdit;
    if (!canvas || !edit) return;
    const ctx = canvas.getContext('2d');
    const img = edit.img;
    const w = img && img.naturalWidth ? img.naturalWidth : 960;
    const h = img && img.naturalHeight ? img.naturalHeight : 540;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    ctx.clearRect(0, 0, w, h);
    if (img) ctx.drawImage(img, 0, 0, w, h);
    else {
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(0, 0, w, h);
    }
    function strokePoly(pts, stroke, fill, close) {
        if (!pts || !pts.length) return;
        ctx.beginPath();
        ctx.moveTo(pts[0][0] * w, pts[0][1] * h);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * w, pts[i][1] * h);
        if (close) ctx.closePath();
        if (fill && close) {
            ctx.fillStyle = fill;
            ctx.fill();
        }
        ctx.strokeStyle = stroke;
        ctx.lineWidth = Math.max(2, w / 400);
        ctx.stroke();
    }
    (edit.regions || []).forEach(function (reg) {
        strokePoly(reg.points, '#22c55e', 'rgba(34,197,94,0.28)', true);
    });
    strokePoly(edit.draft, '#facc15', null, false);
}

function renderIntrusionRegionList() {
    const box = document.getElementById('intrusionZoneRegionList');
    const edit = intrusionZoneEdit;
    if (!box || !edit) return;
    box.innerHTML = '';
    (edit.regions || []).forEach(function (reg, idx) {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin:4px 0;';
        const label = document.createElement('span');
        label.textContent = t('policy.zoneRegion', { n: idx + 1 }) + ' · ' + (reg.points || []).length;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-delete';
        btn.style.padding = '4px 8px';
        btn.textContent = t('policy.zoneDel');
        btn.addEventListener('click', function () {
            edit.regions.splice(idx, 1);
            renderIntrusionRegionList();
            drawIntrusionZone();
        });
        row.appendChild(label);
        row.appendChild(btn);
        box.appendChild(row);
    });
}

function renderIntrusionSchedule() {
    const wrap = document.getElementById('intrusionZoneSchedWrap');
    const host = document.getElementById('intrusionZoneSched');
    const edit = intrusionZoneEdit;
    if (!wrap || !host || !edit) return;
    wrap.style.display = edit.schedule_all ? 'none' : 'block';
    if (edit.schedule_all) return;
    if (!edit.schedule) edit.schedule = blankSchedule(true);
    const table = document.createElement('table');
    const head = document.createElement('tr');
    head.appendChild(document.createElement('th'));
    for (let h = 0; h < 24; h++) {
        const th = document.createElement('th');
        th.textContent = String(h);
        head.appendChild(th);
    }
    table.appendChild(head);
    for (let d = 0; d < 7; d++) {
        const tr = document.createElement('tr');
        const th = document.createElement('th');
        th.textContent = t('policy.wd' + d);
        tr.appendChild(th);
        for (let h = 0; h < 24; h++) {
            const td = document.createElement('td');
            const input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = !!(edit.schedule[d] && edit.schedule[d][h]);
            input.addEventListener('change', function () {
                edit.schedule[d][h] = input.checked;
            });
            td.appendChild(input);
            tr.appendChild(td);
        }
        table.appendChild(tr);
    }
    host.innerHTML = '';
    host.appendChild(table);
}

function closeIntrusionZone() {
    const el = document.getElementById('intrusionZoneModal');
    if (el) {
        el.classList.remove('show');
        el.setAttribute('aria-hidden', 'true');
    }
    if (intrusionZoneEdit && intrusionZoneEdit.blobUrl) {
        URL.revokeObjectURL(intrusionZoneEdit.blobUrl);
    }
    intrusionZoneEdit = null;
}

function openIntrusionZone(btn) {
    const streamItem = btn && btn.closest ? btn.closest('.stream-item') : null;
    if (!streamItem) return;
    const z = normalizeIntrusionZoneClient(streamItem._intrusion_zone);
    intrusionZoneEdit = {
        streamItem: streamItem,
        regions: JSON.parse(JSON.stringify(z.regions || [])),
        draft: [],
        schedule_all: z.schedule_all !== false,
        schedule: z.schedule ? JSON.parse(JSON.stringify(z.schedule)) : null,
        img: null,
        blobUrl: ''
    };
    const all = document.getElementById('intrusionZoneAllHours');
    if (all) all.checked = intrusionZoneEdit.schedule_all;
    const msg = document.getElementById('intrusionZoneFrameMsg');
    if (msg) {
        msg.style.display = 'none';
        msg.textContent = '';
    }
    renderIntrusionRegionList();
    renderIntrusionSchedule();
    drawIntrusionZone();
    const modal = document.getElementById('intrusionZoneModal');
    if (modal) {
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }
    const id = streamItem.dataset.id || '';
    if (!id) return;
    fetch('/api/streams/' + encodeURIComponent(id) + '/preview-frame', { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('frame');
            return r.blob();
        })
        .then(function (blob) {
            if (!intrusionZoneEdit || intrusionZoneEdit.streamItem !== streamItem) return;
            const img = new Image();
            const url = URL.createObjectURL(blob);
            intrusionZoneEdit.blobUrl = url;
            img.onload = function () {
                if (!intrusionZoneEdit) return;
                intrusionZoneEdit.img = img;
                drawIntrusionZone();
            };
            img.src = url;
        })
        .catch(function () {
            if (msg) {
                msg.textContent = t('policy.zoneFrameFail');
                msg.style.display = 'block';
            }
        });
}

function applyIntrusionZone() {
    const edit = intrusionZoneEdit;
    if (!edit || !edit.streamItem) return;
    if (edit.draft && edit.draft.length) {
        if (edit.draft.length < 3) {
            if (typeof showMessage === 'function') showMessage(t('policy.zoneNeed3'), 'error');
            return;
        }
        edit.regions.push({ points: edit.draft.slice() });
        edit.draft = [];
    }
    edit.streamItem._intrusion_zone = {
        regions: edit.regions.slice(0, 8),
        schedule_all: !!edit.schedule_all,
        schedule: edit.schedule_all ? null : edit.schedule
    };
    updateStreamZoneSummary(edit.streamItem);
    closeIntrusionZone();
}

document.getElementById('intrusionZoneCloseBtn')?.addEventListener('click', closeIntrusionZone);
document.getElementById('intrusionZoneCancel')?.addEventListener('click', closeIntrusionZone);
document.getElementById('intrusionZoneApply')?.addEventListener('click', applyIntrusionZone);
document.getElementById('intrusionZoneClosePoly')?.addEventListener('click', function () {
    const edit = intrusionZoneEdit;
    if (!edit) return;
    if (edit.draft.length < 3) {
        if (typeof showMessage === 'function') showMessage(t('policy.zoneNeed3'), 'error');
        return;
    }
    if (edit.regions.length >= 8) return;
    edit.regions.push({ points: edit.draft.slice() });
    edit.draft = [];
    renderIntrusionRegionList();
    drawIntrusionZone();
});
document.getElementById('intrusionZoneUndo')?.addEventListener('click', function () {
    const edit = intrusionZoneEdit;
    if (!edit || !edit.draft.length) return;
    edit.draft.pop();
    drawIntrusionZone();
});
document.getElementById('intrusionZoneClear')?.addEventListener('click', function () {
    const edit = intrusionZoneEdit;
    if (!edit) return;
    edit.regions = [];
    edit.draft = [];
    renderIntrusionRegionList();
    drawIntrusionZone();
});
document.getElementById('intrusionZoneAllHours')?.addEventListener('change', function (ev) {
    const edit = intrusionZoneEdit;
    if (!edit) return;
    edit.schedule_all = !!ev.target.checked;
    if (!edit.schedule_all && !edit.schedule) edit.schedule = blankSchedule(true);
    renderIntrusionSchedule();
});
document.getElementById('intrusionZoneWorkday')?.addEventListener('click', function () {
    const edit = intrusionZoneEdit;
    if (!edit) return;
    edit.schedule = blankSchedule(false);
    for (let d = 0; d < 5; d++) {
        for (let h = 8; h < 18; h++) edit.schedule[d][h] = true;
    }
    renderIntrusionSchedule();
});
document.getElementById('intrusionZoneCanvas')?.addEventListener('click', function (ev) {
    const edit = intrusionZoneEdit;
    const canvas = ev.currentTarget;
    if (!edit || !canvas) return;
    if ((edit.regions || []).length >= 8 && !(edit.draft || []).length) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
    if (edit.draft.length >= 32) return;
    edit.draft.push([Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000]);
    drawIntrusionZone();
});

function formatAlertTime(tsRaw) {
    const time = new Date(tsRaw || '');
    if (Number.isNaN(time.getTime())) return String(tsRaw || '');
    try {
        const loc = (window.VisionAI && VisionAI.i18n.getLocale() === 'en') ? 'en-US' : 'zh-CN';
        return time.toLocaleString(loc, { hour12: false, timeZone: appTimezone });
    } catch (e) {
        const loc = (window.VisionAI && VisionAI.i18n.getLocale() === 'en') ? 'en-US' : 'zh-CN';
        return time.toLocaleString(loc, { hour12: false });
    }
}

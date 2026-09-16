/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* policy.js */

async function loadDetectionCatalog() {
    try {
        const response = await fetch('/api/detection-catalog');
        detectionCatalog = await response.json();
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
    sel.innerHTML = '<option value="">全部类型</option>';
    if (detectionCatalog && detectionCatalog.length) {
        detectionCatalog.forEach(item => {
            const o = document.createElement('option');
            o.value = item.name_zh;
            o.textContent = item.name_zh + ' / ' + item.name_en;
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
        sel.innerHTML = '<option value="">全部视频</option>';
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
            enabled.push(`${item.name_zh}${item.class_id !== null && item.class_id !== undefined ? ' (#' + item.class_id + ')' : ''}`);
        }
    });
    const total = detectionCatalog.length;
    const n = enabled.length;
    if (!n) {
        summaryEl.innerHTML = '<strong style="color:#c92a2a;">尚未勾选检测类型，拉流在线也不会产生告警。</strong>请点「算法配置」勾选后保存。';
        return;
    }
    let extra = '';
    if (d.fatigue_driving && streamItem._dms_status) {
        const st = streamItem._dms_status;
        const col = st.supported === true ? '#2b8a3e' : (st.supported == null ? '#868e96' : '#c92a2a');
        extra = `<br><span style="color:${col}">疲劳驾驶准入：${escapeHtml(st.reason_zh || '评估中')}</span>`;
    }
    summaryEl.innerHTML = `<strong>本流已开启 ${n}/${total} 项</strong>（系统均支持）` +
        `：<span style="color:#212529">${enabled.slice(0, 12).join('、')}${enabled.length > 12 ? '…' : ''}</span>` + extra;
}

function renderDetectionModalList(filterText) {
    const list = document.getElementById('detectionConfigList');
    if (!list || !detectionModalDraft) return;
    const q = (filterText || '').trim().toLowerCase();
    list.innerHTML = '';
    const groups = [
        { id: 'coco', title: 'COCO 80 类', match: (it) => it.source === 'coco' },
        { id: 'builtin', title: '内置扩展', match: (it) => it.source === 'builtin' },
        { id: 'specialist', title: '专模（自训 / 导入）', match: (it) => it.source === 'specialist' },
    ];
    const appendItem = (item) => {
        const hay = (item.name_zh + ' ' + item.name_en + ' ' + item.key).toLowerCase();
        if (q && !hay.includes(q)) return;
        const row = document.createElement('div');
        row.className = 'config-modal-item';
        const checked = !!detectionModalDraft[item.key];
        const isSpec = item.source === 'specialist';
        const delBtn = isSpec && item.deletable
            ? `<button type="button" class="btn-specialist-delete" data-specialist-key="${item.key}" title="删除专模" style="margin-right:8px;padding:4px 8px;font-size:12px;">删除</button>`
            : '';
        row.innerHTML = `
            <div style="flex:1;min-width:0;">
                <div class="switch-name">${item.name_zh}${isSpec ? ' <span style="background:#e7f5ff;color:#1971c2;padding:1px 6px;border-radius:4px;font-size:11px;">专模</span>' : ''} <span style="color:#868e96;font-weight:400;">/ ${item.name_en}</span></div>
                <div class="detection-key-hint">${isSpec ? ((item.origin === 'imported') ? '导入专模' : '训练专模') : '系统支持检测'} · 键 ${item.key}${item.class_id !== null && item.class_id !== undefined ? ' · COCO #' + item.class_id : ''}</div>
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
            if (!window.confirm('确定删除专模「' + key + '」？权重将移除，各流检测配置中的该项也会被清除。')) return;
            try {
                const resp = await fetch('/api/training/specialists/' + encodeURIComponent(key), {
                    method: 'DELETE',
                    credentials: 'same-origin',
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    alert(data.message || '删除失败');
                    return;
                }
                if (detectionModalDraft) delete detectionModalDraft[key];
                await loadDetectionCatalog();
                renderDetectionModalList(document.getElementById('detectionConfigSearch').value);
            } catch (e) {
                alert('删除失败: ' + e);
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

function formatAlertTime(tsRaw) {
    const time = new Date(tsRaw || '');
    if (Number.isNaN(time.getTime())) return String(tsRaw || '');
    try {
        return time.toLocaleString('zh-CN', { hour12: false, timeZone: appTimezone });
    } catch (e) {
        return time.toLocaleString('zh-CN', { hour12: false });
    }
}

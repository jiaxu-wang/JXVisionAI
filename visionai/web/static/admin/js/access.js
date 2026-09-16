/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* access.js */

async function fetchAllStreams() {
    const response = await fetch('/api/streams');
    return await response.json();
}

async function refreshZlmStatusCache() {
    try {
        const zlmRes = await fetch('/api/zlm/status');
        if (zlmRes.ok) window._zlmStatusCache = await zlmRes.json();
    } catch (e) { /* ignore */ }
}

function zlmPlayInfoForStream(sid) {
    const zlm = window._zlmStatusCache;
    if (!zlm || !zlm.streams || !sid) return null;
    return zlm.streams.find(function (s) { return s.id === sid; }) || null;
}

function accessPlayButtonsHtml(sid, stream) {
    const zs = zlmPlayInfoForStream(sid);
    const playHls = zs && zs.play && zs.play.hls ? zs.play.hls : '';
    const copyBtn = playHls
        ? `<button type="button" class="btn-preview btn-copy-zlm" data-url="${escapeHtml(playHls)}" style="padding:8px 12px;">复制 HLS</button>`
        : '';
    const online = stream && stream.status === '在线';
    let prev;
    if (!sid) {
        prev = `<button type="button" class="btn-preview" disabled style="padding:8px 12px;" title="请先保存该连接">预览</button>`;
    } else if (!online) {
        prev = `<button type="button" class="btn-preview" disabled style="padding:8px 12px;" title="设备离线，无法预览">预览</button>`;
    } else {
        prev = `<button type="button" class="btn-preview" data-access-preview style="padding:8px 12px;">预览</button>`;
    }
    return copyBtn + prev;
}

function accessAnalyzeHtml(stream) {
    const sid = stream && stream.id;
    if (!sid) return '';
    if (isAnalysisJoined(stream)) {
        return '<span class="status status-online">已接入分析</span>' +
            '<button type="button" class="btn-filter-apply" data-goto-policy style="padding:8px 12px;">检测配置</button>';
    }
    return '<button type="button" class="btn-save" data-join-analyze style="padding:8px 12px;">接入AI分析</button>';
}

function bindAccessAnalyzeButtons(root, stream) {
    const sid = stream && stream.id;
    if (!sid || !root) return;
    root.querySelector('[data-join-analyze]')?.addEventListener('click', async function () {
        const r = await apiPatchStream(sid, { analyze: true });
        showMessage(r.success ? '已接入分析，请勾选检测类型并保存' : (r.message || '失败'), r.success ? 'success' : 'error');
        if (r.success) gotoPolicyForStream(sid);
    });
    root.querySelector('[data-goto-policy]')?.addEventListener('click', function () {
        goToPage('policy', { streamId: sid });
    });
}

function bindAccessPlayButtons(root, stream) {
    const sid = stream && stream.id;
    const name = (stream && stream.name) || sid || '';
    const prev = root.querySelector('[data-access-preview]');
    if (prev && sid) {
        prev.addEventListener('click', function () {
            openStreamPreview(sid, name);
        });
    }
    const cBtn = root.querySelector('.btn-copy-zlm');
    if (cBtn) {
        cBtn.addEventListener('click', async function () {
            const u = this.getAttribute('data-url') || '';
            try {
                await navigator.clipboard.writeText(u);
                showMessage('已复制 HLS 地址', 'success');
            } catch (e) {
                prompt('复制 HLS 地址', u);
            }
        });
    }
}

async function loadDirectStreams() {
    try {
        await refreshZlmStatusCache();
        const streams = await fetchAllStreams();
        const container = document.getElementById('directStreamContainer');
        if (!container) return;
        container.innerHTML = '';
        const direct = streams.filter(s => DIRECT_METHODS[normalizeAccessMethodClient(s)]);
        if (!direct.length) {
            container.innerHTML = '<p style="color:#6c757d;padding:12px 0;">暂无 RTSP 直连流，可点击下方添加。</p>';
        }
        direct.forEach((stream) => {
            addDirectStreamItem(stream);
        });
        schedulePreviewNavRefresh();
    } catch (error) {
        showMessage('加载 RTSP 直连流失败', 'error');
    }
}

async function loadOnvifStreams() {
    try {
        await refreshZlmStatusCache();
        const streams = await fetchAllStreams();
        const container = document.getElementById('onvifStreamContainer');
        if (!container) return;
        container.innerHTML = '';
        const list = streams.filter(s => normalizeAccessMethodClient(s) === 'onvif');
        if (!list.length) {
            container.innerHTML = '<p style="color:#6c757d;padding:8px 0;">暂无 ONVIF 接入流。请使用上方「ONVIF 发现 / 手动探测」。</p>';
            schedulePreviewNavRefresh();
            return;
        }
        list.forEach((stream) => addOnvifManageItem(container, stream));
        schedulePreviewNavRefresh();
    } catch (error) {
        showMessage('加载 ONVIF 流失败', 'error');
    }
}

async function loadGb28181Streams() {
    try {
        await loadGb28181Platform();
        await loadGb28181Devices();
    } catch (error) {
        /* ignore */
    }
}

async function loadPolicyStreams() {
    try {
        const streams = await fetchAllStreams();
        const container = document.getElementById('policyStreamContainer');
        if (!container) return;
        container.innerHTML = '';
        const joined = streams.filter(isAnalysisJoined);
        if (!joined.length) {
            container.innerHTML = '<p style="color:#6c757d;padding:12px 0;">请先在「设备接入」中将设备接入平台。RTSP/ONVIF 点「接入AI分析」；国标打开「通道」后按通道点「接入分析」。</p>';
            return;
        }
        joined.forEach((stream) => addPolicyStreamItem(stream));
        await refreshSmtpHintForStreamForm();
    } catch (error) {
        showMessage('加载检测配置失败', 'error');
    }
}

// 兼容旧调用名
async function loadStreams() {
    return loadDirectStreams();
}

async function refreshSmtpHintForStreamForm() {
    try {
        const r = await fetch('/api/config');
        const cfg = await r.json();
        const ready = cfg.smtp && cfg.smtp.ready;
        const text = ready
            ? '全局 SMTP 已就绪：告警将按上方向外发（频率与截图间隔 save_interval 一致）。'
            : '提示：请先在服务器配置 SMTP（smtp_alert_enabled、smtp_host、smtp_from 等，见 config.example.ini），否则仅填写邮箱不会发信。';
        document.querySelectorAll('.stream-smtp-hint').forEach(el => {
            el.style.display = 'block';
            el.textContent = text;
            el.style.color = ready ? '#155724' : '#856404';
        });
    } catch (e) {
        /* ignore */
    }
}

async function apiPatchStream(streamId, body) {
    const res = await fetch('/api/streams/' + encodeURIComponent(streamId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    });
    return res.json();
}

async function apiDeleteStream(streamId) {
    const res = await fetch('/api/streams/' + encodeURIComponent(streamId), {
        method: 'DELETE'
    });
    return res.json();
}

function addOnvifManageItem(container, stream) {
    const streamItem = document.createElement('div');
    streamItem.className = 'stream-item';
    const sid = stream.id || '';
    if (sid) streamItem.dataset.id = sid;
    const statusClass = stream.status === '在线' ? 'status-online' : 'status-offline';
    const ov = stream.onvif || {};
    const metaBits = [
        ov.manufacturer, ov.model, ov.host ? (ov.host + ':' + (ov.port || 80)) : '',
        ov.profile_token ? ('Profile ' + ov.profile_token) : ''
    ].filter(Boolean).join(' · ');
    streamItem._talk_supported = !!stream.talk_supported;
    streamItem.innerHTML = `
        <div class="stream-inputs">
            <input type="text" class="stream-name" value="${String(stream.name || '').replace(/"/g, '&quot;')}" placeholder="流名称" style="min-width:140px;">
            <span class="access-badge">ONVIF</span>
            <span class="status ${statusClass}">${escapeHtml(stream.status || '未知')}</span>
            ${accessPlayButtonsHtml(sid, stream)}
            <button type="button" class="btn-save" data-save-name style="padding:8px 12px;">保存名称</button>
            <button type="button" class="btn-filter-apply" data-refresh-rtsp style="padding:8px 12px;" title="需重新输入设备密码">刷新 RTSP</button>
            ${sid ? `<button type="button" class="btn-talk stream-talk-btn" style="padding:8px 12px;">${stream.talk_supported ? '对讲' : '探测对讲'}</button>` : ''}
            ${accessAnalyzeHtml(stream)}
            <button type="button" class="btn-delete" data-del-stream style="padding:8px 12px;">删除</button>
        </div>
        <p style="color:#6c757d;font-size:13px;word-break:break-all;margin:0 0 6px 0;">${escapeHtml(stream.url || '')}</p>
        ${metaBits ? `<p style="color:#94a3b8;font-size:12px;margin:0;">${escapeHtml(metaBits)}</p>` : ''}
    `;
    container.appendChild(streamItem);
    bindAccessPlayButtons(streamItem, stream);
    bindAccessAnalyzeButtons(streamItem, stream);
    streamItem.querySelector('[data-save-name]')?.addEventListener('click', async function () {
        const name = streamItem.querySelector('.stream-name')?.value.trim();
        if (!name || !sid) return;
        const r = await apiPatchStream(sid, { name });
        showMessage(r.success ? '名称已保存' : (r.message || '失败'), r.success ? 'success' : 'error');
        if (r.success) await loadOnvifStreams();
    });
    streamItem.querySelector('[data-refresh-rtsp]')?.addEventListener('click', async function () {
        if (!sid) return;
        const username = prompt('ONVIF 用户名', 'admin') || '';
        const password = prompt('ONVIF 密码（仅用于本次刷新，不会落库）', '') || '';
        if (!password) {
            showMessage('已取消刷新', 'error');
            return;
        }
        try {
            const res = await fetch('/api/onvif/refresh-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stream_id: sid,
                    username,
                    password,
                    probe_talk: true
                })
            });
            const data = await res.json();
            showMessage(data.success ? 'RTSP 已刷新' : (data.message || '失败'), data.success ? 'success' : 'error');
            if (data.success) await loadOnvifStreams();
        } catch (e) {
            showMessage('刷新失败: ' + e, 'error');
        }
    });
    streamItem.querySelector('.stream-talk-btn')?.addEventListener('click', function () {
        openTalkModal(sid, stream.name || sid, !!stream.talk_supported);
    });
    streamItem.querySelector('[data-del-stream]')?.addEventListener('click', async function () {
        if (!sid || !confirm('确定删除该 ONVIF 流？')) return;
        const r = await apiDeleteStream(sid);
        showMessage(r.success ? '已删除' : (r.message || '失败'), r.success ? 'success' : 'error');
        if (r.success) await loadOnvifStreams();
    });
}

function inferDirectAccessMethod(url) {
    return 'rtsp_url';
}

function addDirectStreamItem(stream) {
    const container = document.getElementById('directStreamContainer');
    if (!container) return;
    if (container.querySelector('p') && !container.querySelector('.stream-item')) {
        container.innerHTML = '';
    }
    const streamItem = document.createElement('div');
    streamItem.className = 'stream-item';
    const name = (stream && stream.name) || '';
    const url = (stream && stream.url) || '';
    const status = (stream && stream.status) || '未知';
    const id = (stream && stream.id) || null;
    const statusClass = status === '在线' ? 'status-online' : 'status-offline';
    const method = stream ? normalizeAccessMethodClient(stream) : 'rtsp_url';
    streamItem.dataset.accessMethod = DIRECT_METHODS[method] ? method : 'rtsp_url';
    streamItem._onvif = null;
    streamItem._detections = stream && stream.detections
        ? normalizeDetectionsClient(stream.detections)
        : null;
    streamItem._face_recognition_config = stream
        ? normalizeFaceRecogConfigClient(stream.face_recognition_config)
        : null;
    streamItem._plate_recognition_config = stream
        ? normalizePlateRecogConfigClient(stream.plate_recognition_config)
        : null;
    streamItem._fatigue_driving_config = stream
        ? normalizeFatigueConfigClient(stream.fatigue_driving_config)
        : null;
    streamItem._dms_status = stream ? (stream.dms_status || null) : null;
    streamItem._alert_emails = (stream && stream.alert_emails) || [];
    streamItem._alert_email_enabled = !stream || stream.alert_email_enabled !== false;
    streamItem._alert_webhook_urls = (stream && stream.alert_webhook_urls) || [];
    streamItem._alert_webhook_enabled = !!(stream && stream.alert_webhook_enabled);
    streamItem._enabled = !stream || stream.enabled !== false;
    if (id) streamItem.dataset.id = id;
    streamItem.innerHTML = `
        <div class="stream-inputs">
            <input type="text" placeholder="流名称" value="${String(name).replace(/"/g, '&quot;')}" class="stream-name">
            <input type="text" placeholder="rtsp:// 或 rtsps://" value="${String(url).replace(/"/g, '&quot;')}" class="stream-url">
            <span class="access-badge">RTSP</span>
            <span class="status ${statusClass}">${escapeHtml(status)}</span>
            ${accessPlayButtonsHtml(id, stream)}
            ${accessAnalyzeHtml(stream)}
            <button type="button" class="btn-delete" data-del-direct style="padding:8px 12px;">删除</button>
        </div>
    `;
    container.appendChild(streamItem);
    bindAccessPlayButtons(streamItem, stream || {});
    bindAccessAnalyzeButtons(streamItem, stream || {});
    streamItem.querySelector('[data-del-direct]')?.addEventListener('click', async function () {
        if (id) {
            if (!confirm('确定删除该 RTSP 直连流？')) return;
            const r = await apiDeleteStream(id);
            showMessage(r.success ? '已删除' : (r.message || '失败'), r.success ? 'success' : 'error');
            if (r.success) await loadDirectStreams();
        } else {
            streamItem.remove();
        }
    });
}

function addStreamItem() {
    // 直连页「添加」：空行
    addDirectStreamItem(null);
}

function addPolicyStreamItem(stream) {
    const container = document.getElementById('policyStreamContainer');
    if (!container) return;
    const streamItem = document.createElement('div');
    streamItem.className = 'stream-item';
    const id = stream.id || '';
    const enabled = stream.enabled !== false;
    const enabledClass = enabled ? 'btn-save' : 'btn-restart';
    const enabledText = enabled ? '暂停检测' : '启用检测';
    streamItem._detections = normalizeDetectionsClient(stream.detections);
    streamItem._face_recognition_config = normalizeFaceRecogConfigClient(stream.face_recognition_config);
    streamItem._plate_recognition_config = normalizePlateRecogConfigClient(stream.plate_recognition_config);
    streamItem._fatigue_driving_config = normalizeFatigueConfigClient(stream.fatigue_driving_config);
    streamItem._dms_status = stream.dms_status || null;
    streamItem._access_method = normalizeAccessMethodClient(stream);
    streamItem._url = stream.url || '';
    streamItem._name = stream.name || '';
    streamItem._onvif = stream.onvif || null;
    streamItem._talk_supported = !!stream.talk_supported;
    streamItem._talk_protocol = stream.talk_protocol || '';
    streamItem._talk_codec = stream.talk_codec || '';
    streamItem._talk_detail = stream.talk_detail || '';
    streamItem._gb28181 = stream.gb28181 || null;
    if (id) streamItem.dataset.id = id;
    streamItem.dataset.enabled = enabled ? 'true' : 'false';
    const alertEmailEnabled = stream.alert_email_enabled !== false;
    const alertWebhookEnabled = stream.alert_webhook_enabled === true;
    streamItem.innerHTML = `
        <div class="stream-inputs">
            <strong style="min-width:120px;">${escapeHtml(stream.name || '')}</strong>
            <span class="access-badge">${escapeHtml(accessLabelForStream(stream))}</span>
            <button type="button" class="btn-save stream-detection-config-btn" onclick="openDetectionConfig(this)" style="padding: 8px 14px;">算法配置</button>
            <button type="button" class="${enabledClass}" onclick="toggleStreamEnabled(this)" style="padding: 8px 12px;">${enabledText}</button>
            <button type="button" class="btn-filter-apply" style="padding:8px 12px;" data-goto-access="${escapeHtml(id)}">接入配置</button>
            ${id ? '<button type="button" class="btn-delete" data-del-policy style="padding:8px 12px;">删除</button>' : ''}
        </div>
        <p style="color:#6c757d;font-size:12px;word-break:break-all;margin:0 0 8px 0;">${escapeHtml(stream.url || '')}</p>
        <div class="stream-detection-row">
            <div style="flex:1;min-width:220px;">
                <span class="badge-supported">系统支持 · COCO 80类 + 内置扩展 + 专模（自训/导入） + 人脸/车牌识别</span>
                <div class="stream-detection-summary"></div>
            </div>
        </div>
        <div class="stream-alert-emails-row" style="margin-top: 12px;">
            <label class="stream-alert-email-enable-row">
                <input type="checkbox" class="stream-alert-email-enabled" ${alertEmailEnabled ? 'checked' : ''}>
                <span>启用邮件告警</span>
            </label>
            <label style="display: block; font-size: 13px; color: #495057; margin-bottom: 4px;">告警外发邮箱（多个用逗号、分号或换行）</label>
            <textarea class="stream-alert-emails" rows="2" placeholder="例：ops@example.com&#10;duty@example.com" style="width: 100%; max-width: 720px; padding: 8px; border-radius: 6px; border: 1px solid #ced4da; font-family: inherit; font-size: 14px; resize: vertical;"></textarea>
            <p class="stream-smtp-hint" style="font-size: 12px; margin: 6px 0 0 0; display: none;"></p>
        </div>
        <div class="stream-alert-webhooks-row" style="margin-top: 12px;">
            <label class="stream-alert-email-enable-row">
                <input type="checkbox" class="stream-alert-webhook-enabled" ${alertWebhookEnabled ? 'checked' : ''}>
                <span>启用告警 Webhook</span>
            </label>
            <label style="display: block; font-size: 13px; color: #495057; margin-bottom: 4px;">回调 URL（多个用逗号、分号或换行；仅 http/https）</label>
            <textarea class="stream-alert-webhooks" rows="2" placeholder="例：https://api.example.com/hooks/visionai&#10;https://backup.example.com/alert" style="width: 100%; max-width: 720px; padding: 8px; border-radius: 6px; border: 1px solid #ced4da; font-family: inherit; font-size: 14px; resize: vertical;"></textarea>
            <p style="font-size: 12px; margin: 6px 0 0 0; color: #6c757d;">告警写入 Redis 后向每个 URL 依次 POST JSON（频率与截图间隔 save_interval 一致）。</p>
        </div>
    `;
    container.appendChild(streamItem);
    const ta = streamItem.querySelector('.stream-alert-emails');
    if (ta) {
        let em = stream.alert_emails;
        if (typeof em === 'string') ta.value = em;
        else if (Array.isArray(em) && em.length) ta.value = em.join('\n');
        else ta.value = '';
    }
    const taWh = streamItem.querySelector('.stream-alert-webhooks');
    if (taWh) {
        let wh = stream.alert_webhook_urls;
        if (typeof wh === 'string') taWh.value = wh;
        else if (Array.isArray(wh) && wh.length) taWh.value = wh.join('\n');
        else taWh.value = '';
    }
    updateStreamDetectionSummary(streamItem);
    const gotoBtn = streamItem.querySelector('[data-goto-access]');
    if (gotoBtn && id) {
        gotoBtn.addEventListener('click', function () {
            goToPage(accessPageForStream(stream), { streamId: id });
        });
    }
    const delBtn = streamItem.querySelector('[data-del-policy]');
    if (delBtn && id) {
        delBtn.addEventListener('click', function () {
            deletePolicyStream(streamItem, stream);
        });
    }
}

function policyDeleteConfirmMessage(stream) {
    const name = (stream && stream.name) ? String(stream.name) : '该路视频';
    const method = normalizeAccessMethodClient(stream || {});
    if (method === 'gb28181') {
        return '确定从检测列表删除「' + name + '」？删除后将停止分析。国标 SIP 账号仍保留，可再次「接入分析」。';
    }
    return '确定退出「' + name + '」的 AI 分析？设备仍保留在接入列表，可再次「接入AI分析」。';
}

async function deletePolicyStream(streamItem, stream) {
    const id = (stream && stream.id) || (streamItem && streamItem.dataset.id) || '';
    if (!id) return;
    if (!confirm(policyDeleteConfirmMessage(stream))) return;
    try {
        const method = normalizeAccessMethodClient(stream || {});
        let r;
        if (method === 'gb28181') {
            r = await apiDeleteStream(id);
        } else {
            r = await apiPatchStream(id, { analyze: false });
        }
        if (r.success) {
            showMessage(method === 'gb28181'
                ? '已从检测列表删除，该路视频不再分析'
                : '已退出分析，设备仍在接入列表', 'success');
            await loadPolicyStreams();
        } else {
            showMessage(r.message || '操作失败', 'error');
        }
    } catch (error) {
        showMessage('操作失败: ' + error.message, 'error');
    }
}

// 切换流启用状态
function toggleStreamEnabled(button) {
    const streamItem = button.closest('.stream-item');
    const currentEnabled = streamItem.dataset.enabled === 'true';
    const newEnabled = !currentEnabled;
    
    // 更新数据集
    streamItem.dataset.enabled = newEnabled;
    
    // 更新按钮样式
    button.className = newEnabled ? 'btn-save' : 'btn-restart';
    button.textContent = newEnabled ? '暂停' : '启用';
}

async function postStreamsMerged(streams) {
    const response = await fetch('/api/streams', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(streams)
    });
    return response.json();
}

// 保存直连接入（合并保留 ONVIF / 国标流及策略字段）
async function saveStreams() {
    const container = document.getElementById('directStreamContainer');
    if (!container) return;
    const streamItems = container.querySelectorAll('.stream-item');
    const edited = [];
    let schemeError = '';
    streamItems.forEach(item => {
        const nameInput = item.querySelector('.stream-name');
        const urlInput = item.querySelector('.stream-url');
        if (!nameInput || !urlInput) return;
        const name = nameInput.value.trim();
        const url = urlInput.value.trim();
        if (!name || !url) return;
        const low = url.toLowerCase();
        if (!low.startsWith('rtsp://') && !low.startsWith('rtsps://')) {
            schemeError = '地址必须以 rtsp:// 或 rtsps:// 开头：' + name;
            return;
        }
        const accessMethod = 'rtsp_url';
        const streamData = {
            name,
            url,
            access_method: accessMethod,
            detections: item._detections
                ? JSON.parse(JSON.stringify(item._detections))
                : defaultAllOffDetections(),
            alert_emails: Array.isArray(item._alert_emails) ? item._alert_emails : [],
            alert_email_enabled: item._alert_email_enabled !== false,
            alert_webhook_urls: Array.isArray(item._alert_webhook_urls) ? item._alert_webhook_urls : [],
            alert_webhook_enabled: !!item._alert_webhook_enabled,
            enabled: item._enabled !== false,
            analyze: false
        };
        if (item.dataset.id) streamData.id = item.dataset.id;
        if (item._face_recognition_config) {
            streamData.face_recognition_config = JSON.parse(JSON.stringify(item._face_recognition_config));
        }
        if (item._plate_recognition_config) {
            streamData.plate_recognition_config = JSON.parse(JSON.stringify(item._plate_recognition_config));
        }
        if (item._fatigue_driving_config) {
            streamData.fatigue_driving_config = JSON.parse(JSON.stringify(item._fatigue_driving_config));
        }
        edited.push(streamData);
    });
    if (schemeError) {
        showMessage(schemeError, 'error');
        return;
    }

    try {
        const all = await fetchAllStreams();
        const keep = all.filter(s => !DIRECT_METHODS[normalizeAccessMethodClient(s)]);
        // 已有直连流：用页面编辑覆盖；策略字段优先保留 Redis 中的（若页面缓存了则用页面的）
        const byId = {};
        all.forEach(s => { if (s.id) byId[s.id] = s; });
        const mergedDirect = edited.map(ed => {
            const prev = ed.id ? byId[ed.id] : null;
            if (!prev) return ed;
            return {
                ...prev,
                name: ed.name,
                url: ed.url,
                access_method: ed.access_method
            };
        });
        const streams = [...keep, ...mergedDirect];
        if (streams.length === 0) {
            showMessage('请至少保留一路视频流（RTSP 直连或其它接入）', 'error');
            return;
        }
        const result = await postStreamsMerged(streams);
        if (result.success) {
            showMessage('RTSP 直连已保存；修改地址后需重启服务生效', 'success');
            await loadDirectStreams();
        } else {
            showMessage('保存失败: ' + result.message, 'error');
        }
    } catch (error) {
        showMessage('保存失败: ' + error.message, 'error');
    }
}

// 保存检测配置策略（不改接入 URL）
async function savePolicyStreams() {
    const container = document.getElementById('policyStreamContainer');
    if (!container) return;
    const items = container.querySelectorAll('.stream-item');
    const policyById = {};
    items.forEach(item => {
        const id = item.dataset.id;
        if (!id) return;
        const taMail = item.querySelector('.stream-alert-emails');
        const rawMail = taMail ? taMail.value.trim() : '';
        const taWh = item.querySelector('.stream-alert-webhooks');
        const rawWh = taWh ? taWh.value.trim() : '';
        const mailSw = item.querySelector('.stream-alert-email-enabled');
        const whSw = item.querySelector('.stream-alert-webhook-enabled');
        policyById[id] = {
            detections: item._detections
                ? JSON.parse(JSON.stringify(item._detections))
                : defaultAllOffDetections(),
            alert_emails: rawMail
                ? rawMail.split(/[\s,;，]+/).map(s => s.trim()).filter(Boolean)
                : [],
            alert_email_enabled: !!(mailSw && mailSw.checked),
            alert_webhook_urls: rawWh
                ? rawWh.split(/[\s,;，]+/).map(s => s.trim()).filter(Boolean)
                : [],
            alert_webhook_enabled: !!(whSw && whSw.checked),
            enabled: item.dataset.enabled === 'true',
            face_recognition_config: item._face_recognition_config
                ? JSON.parse(JSON.stringify(item._face_recognition_config))
                : undefined,
            plate_recognition_config: item._plate_recognition_config
                ? JSON.parse(JSON.stringify(item._plate_recognition_config))
                : undefined,
            fatigue_driving_config: item._fatigue_driving_config
                ? JSON.parse(JSON.stringify(item._fatigue_driving_config))
                : undefined
        };
    });
    try {
        const all = await fetchAllStreams();
        if (!all.length) {
            showMessage('暂无视频流', 'error');
            return;
        }
        const streams = all.map(s => {
            const pol = s.id ? policyById[s.id] : null;
            if (!pol) return s;
            return {
                ...s,
                detections: pol.detections,
                alert_emails: pol.alert_emails,
                alert_email_enabled: pol.alert_email_enabled,
                alert_webhook_urls: pol.alert_webhook_urls,
                alert_webhook_enabled: pol.alert_webhook_enabled,
                enabled: pol.enabled,
                face_recognition_config: pol.face_recognition_config || s.face_recognition_config,
                plate_recognition_config: pol.plate_recognition_config || s.plate_recognition_config,
                fatigue_driving_config: pol.fatigue_driving_config || s.fatigue_driving_config
            };
        });
        const result = await postStreamsMerged(streams);
        if (result.success) {
            showMessage('检测配置已保存（热更新，无需重启）', 'success');
            await loadPolicyStreams();
        } else {
            showMessage('保存失败: ' + result.message, 'error');
        }
    } catch (error) {
        showMessage('保存失败: ' + error.message, 'error');
    }
}

// 重启服务
async function restartService() {
    try {
        const response = await fetch('/api/restart', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('服务重启中...请稍候', 'success');
            setTimeout(() => {
                window.location.reload();
            }, 3000);
        } else {
            showMessage('重启服务失败: ' + result.message, 'error');
        }
    } catch (error) {
        showMessage('重启服务失败', 'error');
    }
}

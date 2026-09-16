/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* devices.js */

// 退出登录
function logout() {
    if (confirm('确定要退出登录吗？')) {
        window.location.href = '/logout';
    }
}

// ---- ONVIF 发现 ----
let onvifDevices = [];
let onvifSelectedIdx = -1;
let onvifProbeInfo = null;
let onvifProfiles = [];

function openOnvifModal() {
    const m = document.getElementById('onvifModal');
    if (!m) return;
    m.classList.add('show');
    m.setAttribute('aria-hidden', 'false');
    setOnvifMsg('');
}
function closeOnvifModal() {
    const m = document.getElementById('onvifModal');
    if (!m) return;
    m.classList.remove('show');
    m.setAttribute('aria-hidden', 'true');
}
function setOnvifMsg(text, kind) {
    const el = document.getElementById('onvifStatusMsg');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'onvif-msg' + (kind ? ' ' + kind : '');
}
function statusBadge(status) {
    const s = status || 'pending';
    const label = s === 'normal' ? '正常' : (s === 'failed' ? '失败' : '未验证');
    const cls = s === 'normal' ? 'normal' : (s === 'failed' ? 'failed' : 'pending');
    return `<span class="onvif-badge ${cls}">${label}</span>`;
}
function renderOnvifDevices() {
    const tb = document.getElementById('onvifDeviceTbody');
    if (!tb) return;
    if (!onvifDevices.length) {
        tb.innerHTML = '<tr><td colspan="4" style="color:#6c757d;text-align:center;">暂无设备</td></tr>';
        return;
    }
    tb.innerHTML = onvifDevices.map((d, i) => {
        const sel = i === onvifSelectedIdx ? 'selected' : '';
        return `<tr class="${sel}" data-idx="${i}" style="cursor:pointer;">
            <td><input type="radio" name="onvifDev" ${i === onvifSelectedIdx ? 'checked' : ''}></td>
            <td>${escapeHtml(d.name || d.host)}</td>
            <td>${escapeHtml(d.host)}:${escapeHtml(String(d.port || 80))}</td>
            <td>${statusBadge(d.status)}${d.error ? ' <span style="color:#c62828;font-size:12px;">' + escapeHtml(d.error) + '</span>' : ''}</td>
        </tr>`;
    }).join('');
    tb.querySelectorAll('tr[data-idx]').forEach(tr => {
        tr.addEventListener('click', () => {
            onvifSelectedIdx = parseInt(tr.getAttribute('data-idx'), 10);
            onvifProbeInfo = null;
            onvifProfiles = [];
            document.getElementById('onvifJoinPanel').style.display = 'none';
            renderOnvifDevices();
        });
    });
}
function selectedOnvifDevice() {
    if (onvifSelectedIdx < 0 || onvifSelectedIdx >= onvifDevices.length) return null;
    return onvifDevices[onvifSelectedIdx];
}
async function onvifScan() {
    setOnvifMsg('正在扫描局域网…');
    const timeout = parseFloat(document.getElementById('onvifScanTimeout')?.value || '5');
    try {
        const res = await fetch('/api/onvif/discover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timeout_sec: timeout })
        });
        const data = await res.json();
        if (!data.success) {
            setOnvifMsg(data.message || '扫描失败', 'error');
            return;
        }
        onvifDevices = (data.devices || []).map(d => ({ ...d, status: 'pending', error: '' }));
        onvifSelectedIdx = onvifDevices.length ? 0 : -1;
        onvifProbeInfo = null;
        onvifProfiles = [];
        document.getElementById('onvifJoinPanel').style.display = 'none';
        renderOnvifDevices();
        setOnvifMsg(onvifDevices.length ? `发现 ${onvifDevices.length} 台设备` : '未发现设备（可改用手动 IP；Docker 桥接网络可能扫不到）', onvifDevices.length ? 'ok' : '');
    } catch (e) {
        setOnvifMsg('扫描请求失败: ' + e, 'error');
    }
}
function onvifManualAdd() {
    const host = (document.getElementById('onvifManualHost')?.value || '').trim();
    const port = parseInt(document.getElementById('onvifManualPort')?.value || '80', 10) || 80;
    if (!host) {
        setOnvifMsg('请填写 IP / 主机名', 'error');
        return;
    }
    const key = `${host}:${port}`;
    const exists = onvifDevices.findIndex(d => `${d.host}:${d.port}` === key);
    if (exists >= 0) {
        onvifSelectedIdx = exists;
    } else {
        onvifDevices.push({
            host, port, name: host, endpoint: `http://${host}:${port}/onvif/device_service`,
            status: 'pending', error: '', scopes: []
        });
        onvifSelectedIdx = onvifDevices.length - 1;
    }
    onvifProbeInfo = null;
    onvifProfiles = [];
    document.getElementById('onvifJoinPanel').style.display = 'none';
    renderOnvifDevices();
    setOnvifMsg('已加入列表，请填写账号密码后检测', 'ok');
}
async function onvifProbeSelected() {
    const dev = selectedOnvifDevice();
    if (!dev) {
        setOnvifMsg('请先选择设备', 'error');
        return;
    }
    const username = document.getElementById('onvifUsername')?.value || '';
    const password = document.getElementById('onvifPassword')?.value || '';
    setOnvifMsg(`正在检测 ${dev.host}…`);
    document.getElementById('onvifJoinPanel').style.display = 'none';
    try {
        const res = await fetch('/api/onvif/probe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: dev.host,
                port: dev.port || 80,
                username,
                password
            })
        });
        const data = await res.json();
        if (!data.success && !data.ok) {
            dev.status = 'failed';
            dev.error = data.error || data.message || '探测失败';
            onvifProbeInfo = null;
            renderOnvifDevices();
            setOnvifMsg(dev.error, 'error');
            return;
        }
        dev.status = 'normal';
        dev.error = '';
        if (data.manufacturer || data.model) {
            dev.name = [data.manufacturer, data.model].filter(Boolean).join(' ') || dev.name;
        }
        onvifProbeInfo = data;
        renderOnvifDevices();
        const talkHint = document.getElementById('onvifTalkHint');
        if (talkHint) {
            if (data.talk_supported) {
                talkHint.innerHTML = `<span class="talk-badge yes">支持对讲</span> ${escapeHtml(data.talk_detail || data.talk_protocol || 'ONVIF RTSP Backchannel')}`;
                talkHint.style.color = '#00695c';
            } else {
                talkHint.innerHTML = `<span class="talk-badge no">未检测到对讲</span> ${escapeHtml(data.talk_detail || '设备可能未开放 Audio Backchannel（加入后仍可在设备接入页重新探测）')}`;
                talkHint.style.color = '#607d8b';
            }
        }
        setOnvifMsg('设备正常，正在加载码流 Profile…', 'ok');
        await onvifLoadProfiles();
    } catch (e) {
        setOnvifMsg('检测失败: ' + e, 'error');
    }
}
async function onvifLoadProfiles() {
    const dev = selectedOnvifDevice();
    if (!dev || dev.status !== 'normal') return;
    const username = document.getElementById('onvifUsername')?.value || '';
    const password = document.getElementById('onvifPassword')?.value || '';
    try {
        const res = await fetch('/api/onvif/profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: dev.host,
                port: dev.port || 80,
                username,
                password
            })
        });
        const data = await res.json();
        if (!data.success) {
            setOnvifMsg(data.message || '获取 Profile 失败', 'error');
            return;
        }
        onvifProfiles = data.profiles || [];
        const sel = document.getElementById('onvifProfileSelect');
        sel.innerHTML = onvifProfiles.map((p, i) => {
            const resLabel = (p.width && p.height) ? `${p.width}x${p.height}` : '';
            const enc = p.encoding || '';
            const label = [p.name || p.token, enc, resLabel].filter(Boolean).join(' · ');
            return `<option value="${i}">${escapeHtml(label)}</option>`;
        }).join('');
        const defaultName = (onvifProbeInfo && (onvifProbeInfo.manufacturer || onvifProbeInfo.model))
            ? [onvifProbeInfo.manufacturer, onvifProbeInfo.model].filter(Boolean).join(' ')
            : (dev.name || dev.host);
        document.getElementById('onvifStreamName').value = defaultName;
        document.getElementById('onvifJoinPanel').style.display = 'flex';
        const talkPart = (onvifProbeInfo && onvifProbeInfo.talk_supported)
            ? '；已检测到 ONVIF 对讲能力'
            : '；未检测到对讲（仍可加入监控）';
        setOnvifMsg(`设备正常，共 ${onvifProfiles.length} 路码流，选择后可加入监控` + talkPart, 'ok');
    } catch (e) {
        setOnvifMsg('加载 Profile 失败: ' + e, 'error');
    }
}
function hostFromRtsp(url) {
    try {
        const u = new URL(url.replace(/^rtsps:/i, 'https:').replace(/^rtsp:/i, 'http:'));
        return u.hostname;
    } catch (_) {
        return '';
    }
}
async function onvifAddToMonitor() {
    const dev = selectedOnvifDevice();
    if (!dev || dev.status !== 'normal') {
        setOnvifMsg('仅状态「正常」的设备可加入监控', 'error');
        return;
    }
    const idx = parseInt(document.getElementById('onvifProfileSelect')?.value || '0', 10);
    const prof = onvifProfiles[idx];
    if (!prof || !prof.rtsp_url) {
        setOnvifMsg('请选择有效的 Profile', 'error');
        return;
    }
    const name = (document.getElementById('onvifStreamName')?.value || '').trim();
    if (!name) {
        setOnvifMsg('请填写监控名称', 'error');
        return;
    }
    // 弱提示：同 host 可能已在监控中
    try {
        const existing = await (await fetch('/api/streams')).json();
        const host = hostFromRtsp(prof.rtsp_url) || dev.host;
        const dup = (existing || []).some(s => hostFromRtsp(s.url || '') === host);
        if (dup && !confirm(`监控列表中可能已有来自 ${host} 的流，仍要加入吗？`)) {
            return;
        }
    } catch (_) { /* ignore */ }

    setOnvifMsg('正在加入监控…');
    try {
        const res = await fetch('/api/onvif/add-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                rtsp_url: prof.rtsp_url,
                talk_supported: !!(onvifProbeInfo && onvifProbeInfo.talk_supported),
                talk_protocol: (onvifProbeInfo && onvifProbeInfo.talk_protocol) || '',
                talk_codec: (onvifProbeInfo && onvifProbeInfo.talk_codec) || '',
                talk_detail: (onvifProbeInfo && onvifProbeInfo.talk_detail) || '',
                onvif: {
                    host: dev.host,
                    port: dev.port || 80,
                    profile_token: prof.token || '',
                    manufacturer: (onvifProbeInfo && onvifProbeInfo.manufacturer) || '',
                    model: (onvifProbeInfo && onvifProbeInfo.model) || ''
                }
            })
        });
        const data = await res.json();
        if (!data.success) {
            setOnvifMsg(data.message || '加入失败', 'error');
            return;
        }
        setOnvifMsg(data.message || '已接入平台', 'ok');
        closeOnvifModal();
        if (typeof loadOnvifStreams === 'function') await loadOnvifStreams();
        if (typeof loadStatusData === 'function') await loadStatusData();
        goToPage('access', { tab: 'onvif', streamId: (data.stream && data.stream.id) || '' });
        alert((data.message || '已接入平台') + '：' + name);
    } catch (e) {
        setOnvifMsg('加入失败: ' + e, 'error');
    }
}

// 事件监听器
document.getElementById('addStreamBtn')?.addEventListener('click', () => {
    addStreamItem();
});

document.getElementById('saveStreamsBtn')?.addEventListener('click', saveStreams);
document.getElementById('savePolicyBtn')?.addEventListener('click', savePolicyStreams);

document.getElementById('restartBtn')?.addEventListener('click', restartService);

function updateGbPlatformSummary() {
    const el = document.getElementById('gbPlatformSummary');
    if (!el) return;
    const host = (document.getElementById('gbPublicHost')?.value || '').trim();
    const port = (document.getElementById('gbSipPort')?.value || '').trim();
    const proto = (document.getElementById('gbTransport')?.value || '').toUpperCase();
    const bits = [];
    if (host || port) bits.push((host || '—') + (port ? (':' + port) : ''));
    if (proto) bits.push(proto);
    el.textContent = bits.join(' · ');
}

function applyGbPlatformCollapsed(collapsed) {
    const btn = document.getElementById('gbPlatformCollapseBtn');
    const body = document.getElementById('gbPlatformCollapseBody');
    if (!btn || !body) return;
    const fold = !!collapsed;
    body.hidden = fold;
    btn.setAttribute('aria-expanded', fold ? 'false' : 'true');
    try {
        localStorage.setItem('visionai.gbPlatformCollapsed', fold ? '1' : '0');
    } catch (e) { /* ignore */ }
}

async function loadGb28181Platform() {
    try {
        const res = await fetch('/api/gb28181/platform');
        const data = await res.json();
        const p = (data && data.platform) || {};
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v == null ? '' : v; };
        const en = document.getElementById('gbEnabled');
        if (en) en.checked = !!p.enabled;
        set('gbServerId', p.server_id || '');
        set('gbDomain', p.domain || '');
        set('gbBindHost', p.bind_host || p.sip_host || '0.0.0.0');
        set('gbPublicHost', p.public_host || '');
        set('gbSipPort', p.public_port != null ? p.public_port : (p.bind_port != null ? p.bind_port : (p.sip_port != null ? p.sip_port : 15060)));
        set('gbTransport', p.transport || 'tcp');
        set('gbProtocolVersion', p.protocol_version || 'GB/T28181-2022');
        set('gbExpires', p.register_expires_sec != null ? p.register_expires_sec : 3600);
        set('gbKeepalive', p.keepalive_interval_sec != null ? p.keepalive_interval_sec : 60);
        set('gbKeepaliveMiss', p.keepalive_timeout_count != null ? p.keepalive_timeout_count : 3);
        set('gbMediaIp', p.media_ip || '');
        set('gbMediaPortRange', p.media_port_range || ((p.media_port != null ? p.media_port : 10000) + '-' + (p.media_port_end != null ? p.media_port_end : 10200)));
        updateGbPlatformSummary();
        const sipHint = document.getElementById('gbSipReadyHint');
        if (sipHint) {
            sipHint.textContent = data.sip_ready
                ? '信令进程在线，设备可按复制参数注册。'
                : '信令进程未运行：请启动 visionai-sip（compose 服务或 ./start.sh）。';
            sipHint.style.color = data.sip_ready ? '#155724' : '#856404';
        }
        const hint = document.getElementById('gbPlatformHint');
        if (hint) {
            hint.textContent = '「复制参数」同时给出上级平台与本机 SIP 用户/认证ID/通道编码，对照设备国标页填写。媒体 IP 不会写入复制清单。';
        }
    } catch (e) {
        /* ignore */
    }
}

async function saveGb28181Platform() {
    const body = {
        enabled: !!(document.getElementById('gbEnabled') && document.getElementById('gbEnabled').checked),
        server_id: document.getElementById('gbServerId')?.value.trim() || '',
        domain: document.getElementById('gbDomain')?.value.trim() || '',
        bind_host: document.getElementById('gbBindHost')?.value.trim() || '0.0.0.0',
        bind_port: parseInt(document.getElementById('gbSipPort')?.value || '15060', 10) || 15060,
        public_host: document.getElementById('gbPublicHost')?.value.trim() || '',
        public_port: parseInt(document.getElementById('gbSipPort')?.value || '15060', 10) || 15060,
        transport: document.getElementById('gbTransport')?.value || 'tcp',
        protocol_version: document.getElementById('gbProtocolVersion')?.value.trim() || 'GB/T28181-2022',
        register_expires_sec: parseInt(document.getElementById('gbExpires')?.value || '3600', 10) || 3600,
        keepalive_interval_sec: parseInt(document.getElementById('gbKeepalive')?.value || '60', 10) || 60,
        keepalive_timeout_count: parseInt(document.getElementById('gbKeepaliveMiss')?.value || '3', 10) || 3,
        password: '',
        device_password_mode: 'per_device',
        media_ip: document.getElementById('gbMediaIp')?.value.trim() || '',
        media_port_range: document.getElementById('gbMediaPortRange')?.value.trim() || '10000-10200',
    };
    try {
        const res = await fetch('/api/gb28181/platform', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        showMessage(data.success ? '平台参数已保存' : (data.message || '失败'), data.success ? 'success' : 'error');
        if (data.success) await loadGb28181Platform();
    } catch (e) {
        showMessage('保存失败: ' + e, 'error');
    }
}

function gbCameraCfgText(cfg, d, passwordOverride) {
    cfg = cfg || {};
    d = d || {};
    if (cfg.copy_text && passwordOverride == null) return cfg.copy_text;
    const channels = cfg.channels || d.channels || [];
    const chLines = channels.length
        ? channels.map(function (c, i) {
            const alias = c.alias || c.name || '';
            const cid = c.channel_id || '';
            return '通道号 ' + (c.index || (i + 1)) + ': ' + cid +
                (alias && alias !== cid ? '  别名: ' + alias : '');
        })
        : ['(未配置通道)'];
    return [
        '【上级平台】',
        '启用: 开',
        '协议版本: ' + (cfg.protocol_version || 'GB/T28181-2022'),
        '传输协议: ' + (cfg.sip_transport || 'TCP'),
        'SIP服务器ID: ' + (cfg.sip_server_id || ''),
        'SIP服务器域: ' + (cfg.sip_domain || ''),
        'SIP服务器地址: ' + (cfg.sip_server_host || ''),
        'SIP服务器端口: ' + (cfg.sip_server_port || ''),
        '',
        '【本机注册】',
        'SIP用户名: ' + (cfg.sip_user || d.sip_user || ''),
        'SIP用户认证ID: ' + (cfg.sip_auth_id || d.auth_id || ''),
        'SIP用户认证密码: ' + (passwordOverride != null ? passwordOverride : (cfg.sip_password || d.password || '')),
        '注册有效期: ' + (cfg.register_expires_sec || 3600),
        '心跳周期: ' + (cfg.keepalive_interval_sec || 60),
        '最大心跳超时次数: ' + (cfg.keepalive_timeout_count || 3),
        '',
        '【视频通道编码ID】'
    ].concat(chLines).concat([
        '',
        '【设备侧保持默认】',
        '本地SIP端口: 5060（设备本机监听，不是平台端口）',
        '28181码流索引: 主码流'
    ]).join('\n');
}

function gbSipRowEl(el) {
    return el && el.closest ? el.closest('tr[data-sip-row]') : null;
}

function gbDevTableHeadHtml() {
    return `<table class="gb-dev-table">
        <thead>
            <tr>
                <th class="gb-col-check"><input type="checkbox" id="gbDevCheckAll" title="全选"></th>
                <th class="gb-col-id">ID</th>
                <th>SIP用户</th>
                <th>SIP用户名/认证ID</th>
                <th>SIP用户密码</th>
                <th>状态</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody></tbody>
    </table>
    <p class="gb-draft-err" id="gbDraftErr" style="display:none;"></p>`;
}

function gbSipRowHtml(opts) {
    opts = opts || {};
    const isDraft = !!opts.draft;
    const did = opts.sip_user || '';
    const online = String(opts.status || '').toLowerCase() === 'online';
    const stLabel = isDraft ? '—' : (online ? '在线' : (String(opts.status || '') === 'unknown' ? '未知' : '离线'));
    const stClass = online ? 'status-online' : 'status-offline';
    const chCount = Number(opts.channel_count || 0) || 0;
    const rowId = opts.row_id != null ? String(opts.row_id) : (isDraft ? '—' : '');
    const monitoredCount = Number(opts.monitored_count || 0) || 0;
    const streamId = String(opts.monitor_stream_id || '');
    const actions = isDraft
        ? `<button type="button" class="btn-save" data-gb-save-create>保存</button>
           <button type="button" class="btn-restart" data-gb-cancel-create>取消</button>`
        : `<button type="button" class="btn-filter-apply" data-gb-channels>通道 (${chCount})</button>
           <button type="button" class="btn-save" data-gb-save-edit>保存</button>
           <button type="button" class="btn-filter-apply" data-copy-cfg>复制</button>
           <button type="button" class="btn-delete" data-del-sip>删除</button>`;
    const sipId = String(did || opts.auth_id || '');
    const stHtml = isDraft
        ? '—'
        : `<span class="status ${stClass}">${stLabel}</span>`;
    return `
        <tr class="${isDraft ? 'gb-dev-draft' : ''}" data-sip-row="1" data-sip-user="${escapeHtml(did)}" data-channel-id="${escapeHtml(String(opts.channel_id || ''))}" data-cfg="${opts.cfg_attr || ''}" data-copy-err="${escapeHtml(opts.copy_err || '')}" data-channel-count="${chCount}" data-monitored-count="${monitoredCount}" data-stream-id="${escapeHtml(streamId)}">
            <td class="gb-col-check"><input type="checkbox" class="gb-dev-check" ${isDraft ? 'disabled' : ''}></td>
            <td class="gb-col-id">${escapeHtml(rowId)}</td>
            <td><input type="text" class="gb-f-name" value="${String(opts.name || '').replace(/"/g, '&quot;')}" placeholder="SIP用户"></td>
            <td><input type="text" class="gb-f-sip gb-f-auth" value="${sipId.replace(/"/g, '&quot;')}" readonly title="自动分配，用户名与认证ID相同"></td>
            <td><input type="text" class="gb-f-password" value="${String(opts.password || '').replace(/"/g, '&quot;')}" placeholder="密码" autocomplete="off"></td>
            <td>${stHtml}</td>
            <td><div class="gb-sip-actions">${actions}</div></td>
        </tr>
    `;
}

let gbChannelModalDeviceId = '';
let gbChannelModalDevice = null;

function closeGbChannelModal() {
    const modal = document.getElementById('gbChannelModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
    gbChannelModalDeviceId = '';
    gbChannelModalDevice = null;
}

function gbChannelStatusLabel(st) {
    const s = String(st || '').toLowerCase();
    if (s === 'online') return { text: '在线', cls: 'status-online' };
    if (s === 'unknown') return { text: '未知', cls: 'status-offline' };
    return { text: '离线', cls: 'status-offline' };
}

function normalizeGbChannelsClient(channels) {
    const list = Array.isArray(channels) ? channels : [];
    const out = [];
    const seen = {};
    list.forEach(function (ch, i) {
        if (!ch) return;
        const cid = String(ch.channel_id || '').trim();
        if (!cid || seen[cid]) return;
        if (cid.length >= 13 && cid.substring(10, 13) === '137') return;
        seen[cid] = true;
        const alias = String(ch.alias || ch.name || '').trim() || cid;
        let index = parseInt(ch.index, 10);
        if (!Number.isFinite(index) || index < 1) index = i + 1;
        out.push({
            index: index,
            channel_id: cid,
            alias: alias,
            name: alias,
            status: String(ch.status || 'offline').toLowerCase(),
            monitored: !!ch.monitored,
            stream_id: String(ch.stream_id || '')
        });
    });
    out.sort(function (a, b) {
        return (a.index - b.index) || String(a.channel_id).localeCompare(String(b.channel_id));
    });
    out.forEach(function (ch, i) { ch.index = i + 1; });
    return out;
}

async function fetchGbDeviceById(deviceId) {
    const r = await fetch('/api/gb28181/devices');
    const j = await fetchJsonOrThrow(r);
    if (!j.success) throw new Error(j.message || '加载账号失败');
    const devices = j.devices || [];
    const found = devices.find(function (d) {
        return String(d.sip_user || d.device_id || '') === String(deviceId);
    });
    if (!found) throw new Error('账号不存在');
    // 兼容旧数据：仅有 channel_id 时合成一条通道
    if ((!found.channels || !found.channels.length) && found.channel_id) {
        found.channels = [{
            index: 1,
            channel_id: found.channel_id,
            alias: found.name || found.channel_id,
            status: found.status || 'offline'
        }];
    }
    found.channels = normalizeGbChannelsClient(found.channels || []);
    return found;
}

async function saveGbDeviceChannels(channels) {
    if (!gbChannelModalDevice) throw new Error('未加载账号');
    const d = gbChannelModalDevice;
    const normalized = normalizeGbChannelsClient(channels);
    const payload = {
        auto_allocate: false,
        sip_user: d.sip_user || gbChannelModalDeviceId,
        device_id: d.sip_user || gbChannelModalDeviceId,
        auth_id: d.auth_id || d.sip_user || gbChannelModalDeviceId,
        name: d.name || '',
        password: d.password || '',
        channels: normalized,
        channel_id: normalized.length ? normalized[0].channel_id : '',
        status: d.status || 'offline',
        source: 'provisioned'
    };
    const r = await fetch('/api/gb28181/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const j = await fetchJsonOrThrow(r);
    if (!j.success) throw new Error(j.message || '保存失败');
    gbChannelModalDevice = j.device || { ...d, channels: normalized };
    gbChannelModalDevice.channels = normalizeGbChannelsClient(
        (j.device && j.device.channels) || normalized
    );
    return gbChannelModalDevice.channels;
}

async function allocateNextChannelId() {
    // 优先专用接口；旧进程无该路由时回退 preview-ids
    try {
        const r = await fetch('/api/gb28181/preview-channel-id');
        if (r.status !== 404) {
            const j = await fetchJsonOrThrow(r);
            if (j.success && j.channel_id) return String(j.channel_id);
        }
    } catch (e) { /* fallback below */ }
    const r2 = await fetch('/api/gb28181/preview-ids');
    const j2 = await fetchJsonOrThrow(r2);
    if (!j2.success) throw new Error(j2.message || '无法分配通道编码');
    const cid = (j2.allocation && j2.allocation.channel_id) || '';
    if (!cid) throw new Error('无法分配通道编码');
    return String(cid);
}

function renderGbChannelRows(channels) {
    const tbody = document.getElementById('gbChannelTableBody');
    if (!tbody) return;
    const list = normalizeGbChannelsClient(channels);
    const devOnline = String((gbChannelModalDevice && gbChannelModalDevice.status) || '').toLowerCase() === 'online';
    if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:#94a3b8;padding:18px 10px;">暂无通道，点击「新增通道」添加。</td></tr>';
        return;
    }
    tbody.innerHTML = list.map(function (ch) {
        const st = gbChannelStatusLabel(ch.status);
        const cid = String(ch.channel_id || '');
        const alias = String(ch.alias || ch.name || '');
        const idx = ch.index != null ? ch.index : '';
        return `<tr data-channel-id="${escapeHtml(cid)}" data-stream-id="${escapeHtml(String(ch.stream_id || ''))}">
            <td><input type="number" class="gb-ch-index" min="1" value="${escapeHtml(String(idx))}" style="width:56px;"></td>
            <td><input type="text" class="gb-ch-id" value="${escapeHtml(cid)}"></td>
            <td><input type="text" class="gb-ch-alias" value="${escapeHtml(alias)}" placeholder="别名"></td>
            <td class="gb-ch-status"><span class="status ${st.cls}">${st.text}</span>${ch.monitored ? ' <span class="status status-online">已接入分析</span>' : ''}</td>
            <td><div class="gb-ch-actions">
                <button type="button" class="btn-preview" data-gb-ch-preview ${devOnline ? '' : 'disabled title="设备离线，无法点播"'}>预览</button>
                <button type="button" class="btn-save" data-gb-ch-save>保存</button>
                ${ch.monitored
                    ? `<button type="button" class="btn-save" data-gb-ch-policy>检测配置</button>`
                    : `<button type="button" class="btn-save" data-gb-ch-monitor ${devOnline ? '' : 'disabled title="设备离线，无法接入分析"'}>接入分析</button>`}
                <button type="button" class="btn-delete" data-gb-ch-del>删除</button>
            </div></td>
        </tr>`;
    }).join('');
    tbody.querySelectorAll('[data-gb-ch-save]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const tr = this.closest('tr');
            saveGbChannelRow(tr);
        });
    });
    tbody.querySelectorAll('[data-gb-ch-del]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const tr = this.closest('tr');
            deleteGbChannelRow(tr);
        });
    });
    tbody.querySelectorAll('[data-gb-ch-monitor]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const tr = this.closest('tr');
            joinGbChannelMonitor(tr);
        });
    });
    tbody.querySelectorAll('[data-gb-ch-policy]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const tr = this.closest('tr');
            const sid = tr && tr.getAttribute('data-stream-id');
            if (sid) {
                closeGbChannelModal();
                goToPage('policy', { streamId: sid });
            } else {
                showMessage('未找到对应检测配置', 'error');
            }
        });
    });
    tbody.querySelectorAll('[data-gb-ch-preview]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const tr = this.closest('tr');
            const cid = tr && (tr.querySelector('.gb-ch-id')?.value.trim() || tr.getAttribute('data-channel-id') || '');
            startGbChannelPreview(gbChannelModalDeviceId, cid);
        });
    });
}

async function startGbChannelPreview(deviceId, channelId) {
    deviceId = (deviceId || '').trim();
    channelId = (channelId || '').trim();
    if (!deviceId || !channelId) {
        showMessage('缺少设备或通道', 'error');
        return;
    }
    showMessage('正在点播…', 'success');
    try {
        const r = await fetch('/api/gb28181/devices/' + encodeURIComponent(deviceId) +
            '/channels/' + encodeURIComponent(channelId) + '/preview', { method: 'POST' });
        const j = await fetchJsonOrThrow(r);
        if (!j.success) {
            showMessage(j.message || '点播失败', 'error');
            return;
        }
        if (j.media_online === false) {
            showMessage(j.message || 'Invite 已发送，媒体尚未上线', 'error');
        }
        const zlmStream = j.zlm_stream || '';
        if (zlmStream) {
            openStreamPreview(zlmStream, j.name || channelId, {
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
            openStreamPreview(j.stream_id, j.name || channelId, {
                gbPreview: { device_id: deviceId, channel_id: channelId, bye_on_close: false }
            });
            return;
        }
        showMessage('未返回媒体流', 'error');
    } catch (e) {
        showMessage('点播失败: ' + (e.message || e), 'error');
    }
}

async function postGbJoinMonitor(deviceId, channelId) {
    deviceId = (deviceId || '').trim();
    channelId = (channelId || '').trim();
    if (!deviceId || !channelId) {
        showMessage('缺少设备或通道', 'error');
        return null;
    }
    showMessage('正在接入分析…', 'success');
    const r = await fetch('/api/gb28181/devices/' + encodeURIComponent(deviceId) +
        '/channels/' + encodeURIComponent(channelId) + '/monitor', { method: 'POST' });
    const j = await fetchJsonOrThrow(r);
    if (j.success && gbPreviewSession &&
        gbPreviewSession.device_id === deviceId &&
        gbPreviewSession.channel_id === channelId) {
        gbPreviewSession.bye_on_close = false;
    }
    return j;
}

function gotoPolicyForStream(streamId) {
    const sid = String(streamId || '');
    if (!sid) return;
    closeGbChannelModal();
    goToPage('policy', { streamId: sid, openDetection: true });
}

async function joinGbChannelMonitor(tr) {
    if (!tr || !gbChannelModalDeviceId) return;
    const channel_id = tr.querySelector('.gb-ch-id')?.value.trim() || tr.getAttribute('data-channel-id') || '';
    try {
        const j = await postGbJoinMonitor(gbChannelModalDeviceId, channel_id);
        if (!j) return;
        showMessage(j.success ? (j.message || '已接入分析') : (j.message || '失败'), j.success ? 'success' : 'error');
        const sid = (j.stream && j.stream.id) || '';
        if (j.success && sid) gotoPolicyForStream(sid);
    } catch (e) {
        showMessage('接入分析失败: ' + (e.message || e), 'error');
    }
}

async function loadGbChannelModalList() {
    if (!gbChannelModalDeviceId) return;
    const tbody = document.getElementById('gbChannelTableBody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="color:#94a3b8;padding:18px 10px;">加载中…</td></tr>';
    try {
        const d = await fetchGbDeviceById(gbChannelModalDeviceId);
        gbChannelModalDevice = d;
        const sub = document.getElementById('gbChannelModalSub');
        if (sub) {
            sub.textContent = 'SIP 用户: ' + (d.sip_user || gbChannelModalDeviceId) +
                (d.name ? '　·　' + d.name : '');
        }
        renderGbChannelRows(d.channels || []);
    } catch (e) {
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="5" style="color:#c62828;padding:18px 10px;">' +
                escapeHtml(String(e.message || e)) + '</td></tr>';
        }
    }
}

async function openGbChannelModal(deviceId, deviceName) {
    gbChannelModalDeviceId = deviceId || '';
    gbChannelModalDevice = null;
    if (!gbChannelModalDeviceId) return;
    const modal = document.getElementById('gbChannelModal');
    const title = document.getElementById('gbChannelModalTitle');
    if (title) title.textContent = '通道配置' + (deviceName ? ' · ' + deviceName : '');
    if (modal) {
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }
    await loadGbChannelModalList();
}

async function addGbChannel() {
    if (!gbChannelModalDeviceId) return;
    const alias = window.prompt('通道别名（可留空）', '') || '';
    try {
        if (!gbChannelModalDevice) {
            gbChannelModalDevice = await fetchGbDeviceById(gbChannelModalDeviceId);
        }
        const cid = await allocateNextChannelId();
        const channels = normalizeGbChannelsClient(gbChannelModalDevice.channels || []);
        channels.push({
            index: channels.length + 1,
            channel_id: cid,
            alias: alias.trim() || ('通道' + (channels.length + 1)),
            status: 'offline'
        });
        const saved = await saveGbDeviceChannels(channels);
        showMessage('已新增通道', 'success');
        renderGbChannelRows(saved);
        await loadGb28181Devices();
    } catch (e) {
        showMessage('新增失败: ' + (e.message || e), 'error');
    }
}

async function saveGbChannelRow(tr) {
    if (!tr || !gbChannelModalDeviceId) return;
    const oldId = tr.getAttribute('data-channel-id') || '';
    const channel_id = tr.querySelector('.gb-ch-id')?.value.trim() || '';
    const alias = tr.querySelector('.gb-ch-alias')?.value.trim() || '';
    const indexRaw = tr.querySelector('.gb-ch-index')?.value;
    const index = parseInt(indexRaw, 10);
    if (!channel_id) {
        showMessage('通道 ID 不能为空', 'error');
        return;
    }
    try {
        if (!gbChannelModalDevice) {
            gbChannelModalDevice = await fetchGbDeviceById(gbChannelModalDeviceId);
        }
        const channels = normalizeGbChannelsClient(gbChannelModalDevice.channels || []);
        let found = false;
        for (let i = 0; i < channels.length; i++) {
            if (channels[i].channel_id !== oldId) continue;
            found = true;
            if (channel_id !== oldId && channels.some(function (c) { return c.channel_id === channel_id; })) {
                throw new Error('通道 ID 已存在');
            }
            channels[i].channel_id = channel_id;
            channels[i].alias = alias || channel_id;
            channels[i].name = channels[i].alias;
            if (Number.isFinite(index)) channels[i].index = index;
            break;
        }
        if (!found) throw new Error('通道不存在');
        const saved = await saveGbDeviceChannels(channels);
        showMessage('通道已保存', 'success');
        renderGbChannelRows(saved);
        await loadGb28181Devices();
    } catch (e) {
        showMessage('保存失败: ' + (e.message || e), 'error');
    }
}

async function deleteGbChannelRow(tr) {
    if (!tr || !gbChannelModalDeviceId) return;
    const cid = tr.getAttribute('data-channel-id') || '';
    if (!cid || !confirm('确定删除通道 ' + cid + '？')) return;
    try {
        if (!gbChannelModalDevice) {
            gbChannelModalDevice = await fetchGbDeviceById(gbChannelModalDeviceId);
        }
        const channels = normalizeGbChannelsClient(gbChannelModalDevice.channels || [])
            .filter(function (c) { return c.channel_id !== cid; });
        const saved = await saveGbDeviceChannels(channels);
        showMessage('通道已删除', 'success');
        renderGbChannelRows(saved);
        await loadGb28181Devices();
    } catch (e) {
        showMessage('删除失败: ' + (e.message || e), 'error');
    }
}

function bindGbSipListActions(box) {
    box.querySelectorAll('[data-copy-cfg]').forEach(btn => {
        btn.addEventListener('click', async function () {
            const card = gbSipRowEl(this);
            const err = (card && card.getAttribute('data-copy-err')) || '';
            if (err) {
                showMessage(err, 'error');
                return;
            }
            let text = '';
            try {
                text = decodeURIComponent((card && card.getAttribute('data-cfg')) || '');
            } catch (e) { text = ''; }
            if (!text) {
                showMessage('无可复制参数', 'error');
                return;
            }
            try {
                await navigator.clipboard.writeText(text);
                showMessage('已复制设备端国标参数', 'success');
            } catch (e) {
                prompt('复制以下参数到摄像机', text);
            }
        });
    });
    box.querySelectorAll('[data-del-sip]').forEach(btn => {
        btn.addEventListener('click', async function () {
            const card = gbSipRowEl(this);
            const id = card && card.getAttribute('data-sip-user');
            if (!id || !confirm('确定删除整行 SIP 账号 ' + id + '？')) return;
            try {
                const r = await fetch('/api/gb28181/devices/' + encodeURIComponent(id), { method: 'DELETE' });
                const j = await fetchJsonOrThrow(r);
                showMessage(j.success ? '已删除' : (j.message || '失败'), j.success ? 'success' : 'error');
                if (j.success) await loadGb28181Devices();
            } catch (e) {
                showMessage('删除失败: ' + (e.message || e), 'error');
            }
        });
    });
    box.querySelectorAll('[data-gb-channels]').forEach(btn => {
        btn.addEventListener('click', function () {
            const card = gbSipRowEl(this);
            const id = card && card.getAttribute('data-sip-user');
            const name = card?.querySelector('.gb-f-name')?.value.trim() || '';
            if (id) openGbChannelModal(id, name);
        });
    });
    box.querySelectorAll('[data-gb-save-edit]').forEach(btn => {
        btn.addEventListener('click', async function () {
            const card = gbSipRowEl(this);
            const id = card && card.getAttribute('data-sip-user');
            if (!id || !card) return;
            const name = card.querySelector('.gb-f-name')?.value.trim() || '';
            const password = card.querySelector('.gb-f-password')?.value || '';
            if (!name) {
                showMessage('SIP用户不能为空', 'error');
                return;
            }
            try {
                const r = await fetch('/api/gb28181/devices/' + encodeURIComponent(id), {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, password })
                });
                const j = await fetchJsonOrThrow(r);
                showMessage(j.success ? '已保存修改' : (j.message || '失败'), j.success ? 'success' : 'error');
                if (j.success) await loadGb28181Devices();
            } catch (e) {
                showMessage('保存失败: ' + (e.message || e), 'error');
            }
        });
    });
}

function bindGbDevCheckAll(box) {
    const all = box.querySelector('#gbDevCheckAll');
    if (!all) return;
    all.addEventListener('change', function () {
        box.querySelectorAll('.gb-dev-check:not(:disabled)').forEach(function (cb) {
            cb.checked = all.checked;
        });
    });
}

let gbDeviceListCache = [];

function gbStatusFilterValue() {
    const el = document.getElementById('gbDeviceStatusFilter');
    return el ? String(el.value || '') : '';
}

function filterGbDeviceList(devices) {
    const f = gbStatusFilterValue();
    const list = devices || [];
    if (!f) return list;
    return list.filter(function (d) {
        const st = String((d && d.status) || 'offline').toLowerCase();
        return st === f;
    });
}

function renderGb28181DeviceList(devices, hintText) {
    const box = document.getElementById('gb28181DeviceList');
    const hintEl = document.getElementById('gbDeviceListHint');
    if (devices) gbDeviceListCache = devices;
    if (hintEl && hintText != null) hintEl.textContent = hintText || '';
    if (!box) return;
    const all = gbDeviceListCache || [];
    const list = filterGbDeviceList(all);
    box.innerHTML = gbDevTableHeadHtml();
    const tbody = box.querySelector('tbody');
    if (!all.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="color:#6c757d;padding:16px 12px;">暂无设备。点击「新建」添加一行。</td></tr>';
    } else if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="color:#6c757d;padding:16px 12px;">当前筛选下没有设备。</td></tr>';
    } else {
        tbody.innerHTML = list.map(function (d, i) {
            const did = d.sip_user || d.device_id || '';
            const cfg = d.camera_config || {};
            const copyErr = (cfg.copy_errors && cfg.copy_errors.length) ? cfg.copy_errors.join('；') : '';
            const cfgText = cfg.copy_ok ? gbCameraCfgText(cfg, d) : '';
            const chs = Array.isArray(d.channels) ? d.channels : [];
            const chCount = chs.length || (d.channel_count || 0);
            const firstCid = (chs[0] && chs[0].channel_id) || d.channel_id || '';
            return gbSipRowHtml({
                draft: false,
                row_id: i + 1,
                name: d.name || '',
                password: d.password || '',
                sip_user: did,
                auth_id: d.auth_id || did,
                status: d.status || 'offline',
                channel_count: chCount,
                channel_id: firstCid,
                monitored_count: d.monitored_count || 0,
                monitor_stream_id: d.monitor_stream_id || '',
                cfg_attr: encodeURIComponent(cfgText),
                copy_err: copyErr
            });
        }).join('');
    }
    bindGbSipListActions(box);
    bindGbDevCheckAll(box);
}

async function fetchJsonOrThrow(res) {
    const text = await res.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : {};
    } catch (e) {
        const snip = (text || '').replace(/\s+/g, ' ').slice(0, 120);
        throw new Error(
            '接口返回非 JSON（HTTP ' + res.status + '）。请重启 visionai-api 后硬刷新。' +
            (snip ? ' 片段: ' + snip : '')
        );
    }
    if (!res.ok && !(data && data.message)) {
        throw new Error('HTTP ' + res.status);
    }
    return data;
}

function gbDraftRow() {
    return document.querySelector('#gb28181DeviceList tr.gb-dev-draft');
}

async function refreshGb28181DraftIds(opts) {
    opts = opts || {};
    const draft = gbDraftRow();
    if (!draft) {
        if (opts.fromToolbar) showMessage('请先点「新建」', 'error');
        return;
    }
    const errEl = document.getElementById('gbDraftErr');
    try {
        const res = await fetch('/api/gb28181/preview-ids');
        const data = await fetchJsonOrThrow(res);
        if (!data.success) {
            if (errEl) {
                errEl.style.display = 'block';
                errEl.textContent = data.message || '无法分配编码';
            }
            return;
        }
        const a = data.allocation || {};
        const sip = draft.querySelector('.gb-f-sip');
        if (sip) sip.value = a.sip_user || a.auth_id || '';
        draft.setAttribute('data-sip-user', a.sip_user || '');
        if (errEl) {
            errEl.style.display = 'none';
            errEl.textContent = '';
        }
    } catch (e) {
        if (errEl) {
            errEl.style.display = 'block';
            errEl.textContent = String(e.message || e);
        }
    }
}

async function startGb28181CreateDraft() {
    const box = document.getElementById('gb28181DeviceList');
    if (!box) return;
    if (!box.querySelector('table.gb-dev-table')) {
        box.innerHTML = gbDevTableHeadHtml();
    }
    const tbody = box.querySelector('tbody');
    if (!tbody) return;
    if (gbDraftRow()) {
        gbDraftRow().querySelector('.gb-f-name')?.focus();
        return;
    }
    const empty = tbody.querySelector('td[colspan]');
    if (empty) empty.parentElement.remove();
    tbody.insertAdjacentHTML('afterbegin', gbSipRowHtml({
        draft: true,
        name: '',
        password: '',
        sip_user: '',
        auth_id: '',
        status: 'draft'
    }));
    const draft = gbDraftRow();
    draft.querySelector('[data-gb-cancel-create]')?.addEventListener('click', function () {
        draft.remove();
        if (!tbody.querySelector('tr[data-sip-row]')) {
            tbody.innerHTML = '<tr><td colspan="7" style="color:#6c757d;padding:16px 12px;">暂无设备。点击「新建」添加一行。</td></tr>';
        }
    });
    draft.querySelector('[data-gb-save-create]')?.addEventListener('click', saveGb28181CreateDraft);
    await refreshGb28181DraftIds();
    draft.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    draft.querySelector('.gb-f-name')?.focus();
}

async function saveGb28181CreateDraft() {
    const draft = gbDraftRow();
    if (!draft) return;
    const name = draft.querySelector('.gb-f-name')?.value.trim() || '';
    const password = draft.querySelector('.gb-f-password')?.value || '';
    if (!name) {
        showMessage('请填写 SIP用户', 'error');
        return;
    }
    if (!password) {
        showMessage('请填写密码', 'error');
        return;
    }
    try {
        const res = await fetch('/api/gb28181/devices', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                auto_allocate: true,
                password,
                name,
                channels: [],
                source: 'provisioned'
            })
        });
        const data = await fetchJsonOrThrow(res);
        if (!data.success) {
            showMessage(data.message || '失败', 'error');
            return;
        }
        const d = data.device || {};
        const text = gbCameraCfgText(data.camera_config, d, password);
        try {
            await navigator.clipboard.writeText(text);
            showMessage('已创建 ' + (d.sip_user || '') + '，请点「通道配置」添加通道；参数已复制', 'success');
        } catch (e) {
            showMessage('已创建 ' + (d.sip_user || '') + '，请点「通道配置」添加通道', 'success');
        }
        await loadGb28181Devices();
    } catch (e) {
        showMessage('创建失败: ' + (e.message || e), 'error');
    }
}

async function loadGb28181Devices() {
    const box = document.getElementById('gb28181DeviceList');
    if (!box) return;
    try {
        const res = await fetch('/api/gb28181/devices');
        const data = await fetchJsonOrThrow(res);
        renderGb28181DeviceList(data.devices || [], data.hint || '');
        schedulePreviewNavRefresh();
    } catch (e) {
        box.innerHTML = '<p style="color:#c62828;">加载账号失败: ' + escapeHtml(String(e.message || e)) + '</p>';
    }
}

async function refreshGb28181Status() {
    try {
        const res = await fetch('/api/gb28181/refresh-status', { method: 'POST' });
        const data = await fetchJsonOrThrow(res);
        if (!data.success) {
            showMessage(data.message || '刷新失败', 'error');
            return;
        }
        renderGb28181DeviceList(data.devices || [], data.message || '');
        schedulePreviewNavRefresh();
        showMessage(data.message || '已刷新', 'success');
    } catch (e) {
        showMessage('刷新失败: ' + (e.message || e), 'error');
    }
}

document.getElementById('gbSavePlatformBtn')?.addEventListener('click', saveGb28181Platform);
document.getElementById('gbPlatformCollapseBtn')?.addEventListener('click', function () {
    const body = document.getElementById('gbPlatformCollapseBody');
    applyGbPlatformCollapsed(!(body && body.hidden));
});
(function initGbPlatformCollapse() {
    let fold = true;
    try {
        const v = localStorage.getItem('visionai.gbPlatformCollapsed');
        if (v === '0') fold = false;
        if (v === '1') fold = true;
    } catch (e) { /* ignore */ }
    applyGbPlatformCollapsed(fold);
})();
document.getElementById('gbStartCreateBtn')?.addEventListener('click', startGb28181CreateDraft);
document.getElementById('gbRefreshDraftIdsBtn')?.addEventListener('click', function () {
    refreshGb28181DraftIds({ fromToolbar: true });
});
document.getElementById('gbRefreshStatusBtn')?.addEventListener('click', refreshGb28181Status);
document.getElementById('gbDeviceStatusFilter')?.addEventListener('change', function () {
    renderGb28181DeviceList();
});
document.getElementById('gbChannelModalCloseBtn')?.addEventListener('click', closeGbChannelModal);
document.getElementById('gbChannelModal')?.addEventListener('click', function (e) {
    if (e.target === this) closeGbChannelModal();
});
document.getElementById('gbChannelAddBtn')?.addEventListener('click', addGbChannel);
document.getElementById('gbChannelReloadBtn')?.addEventListener('click', loadGbChannelModalList);

document.querySelectorAll('.access-tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
        const tab = this.getAttribute('data-access-tab') || 'direct';
        showAccessTab(tab, function () {
            if (pendingHighlightStreamId) highlightStreamCard(pendingHighlightStreamId);
        });
    });
});

document.getElementById('onvifDiscoverBtn')?.addEventListener('click', openOnvifModal);
document.getElementById('onvifModalCloseBtn')?.addEventListener('click', closeOnvifModal);
document.getElementById('onvifScanBtn')?.addEventListener('click', onvifScan);
document.getElementById('onvifManualAddBtn')?.addEventListener('click', onvifManualAdd);
document.getElementById('onvifProbeBtn')?.addEventListener('click', onvifProbeSelected);
document.getElementById('onvifAddStreamBtn')?.addEventListener('click', onvifAddToMonitor);

// -------- 语音对讲（ONVIF RTSP Backchannel + 浏览器采麦 G.711）--------
let talkState = {
    streamId: null,
    streamName: '',
    sessionId: null,
    codec: 'PCMA',
    audioCtx: null,
    processor: null,
    mediaStream: null,
    sending: false,
    timer: null
};

function linearToPcmaSample(sample) {
    // ITU-T G.711 A-law
    const ALAW_MAX = 0xFFF;
    let pcm = sample | 0;
    let mask = 0x55;
    if (pcm >= 0) mask = 0xD5;
    else pcm = -pcm - 1; // ones' complement for negatives as common in ref impls
    if (pcm > ALAW_MAX) pcm = ALAW_MAX;
    let seg = 0;
    if (pcm >= 256) {
        let x = pcm >> 8;
        while (x) { seg++; x >>= 1; }
    }
    const aval = (seg << 4) | ((pcm >> (seg ? seg + 3 : 4)) & 0x0F);
    return (aval ^ mask) & 0xFF;
}
function linearToPcmuSample(sample) {
    // ITU-T G.711 µ-law
    const BIAS = 0x84;
    const CLIP = 32635;
    let pcm = sample | 0;
    let sign = (pcm < 0) ? 0x80 : 0;
    if (pcm < 0) pcm = -pcm;
    if (pcm > CLIP) pcm = CLIP;
    pcm = pcm + BIAS;
    let exp = 7;
    for (let eMask = 0x4000; (pcm & eMask) === 0 && exp > 0; exp--, eMask >>= 1) {}
    const mantissa = (pcm >> (exp + 3)) & 0x0F;
    return (~(sign | (exp << 4) | mantissa)) & 0xFF;
}
function encodeG711(float32, codec) {
    const out = new Uint8Array(float32.length);
    const isAlaw = String(codec || 'PCMA').toUpperCase() !== 'PCMU';
    for (let i = 0; i < float32.length; i++) {
        let s = Math.max(-1, Math.min(1, float32[i]));
        const pcm = (s < 0 ? s * 0x8000 : s * 0x7FFF) | 0;
        out[i] = isAlaw ? linearToPcmaSample(pcm) : linearToPcmuSample(pcm);
    }
    return out;
}
function downsampleTo8k(float32, srcRate) {
    if (srcRate === 8000) return float32;
    const ratio = srcRate / 8000;
    const newLen = Math.floor(float32.length / ratio);
    const out = new Float32Array(newLen);
    for (let i = 0; i < newLen; i++) {
        out[i] = float32[Math.floor(i * ratio)] || 0;
    }
    return out;
}
function setTalkUi(status, detail) {
    const st = document.getElementById('talkModalStatus');
    const det = document.getElementById('talkModalDetail');
    if (st) st.textContent = status || '';
    if (det && detail != null) det.textContent = detail;
    const startBtn = document.getElementById('talkStartBtn');
    const stopBtn = document.getElementById('talkStopBtn');
    if (startBtn) startBtn.disabled = !!talkState.sending;
    if (stopBtn) stopBtn.disabled = !talkState.sending;
    if (startBtn) {
        startBtn.classList.toggle('talking', !!talkState.sending);
        startBtn.textContent = talkState.sending ? '对讲中…' : '开始对讲';
    }
}
async function openTalkModal(streamId, streamName, knownSupported) {
    talkState.streamId = streamId;
    talkState.streamName = streamName || streamId;
    const modal = document.getElementById('talkModal');
    const nameEl = document.getElementById('talkModalStreamName');
    if (nameEl) nameEl.textContent = talkState.streamName;
    if (modal) {
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }
    setTalkUi(knownSupported ? '已标记支持对讲，可直接开始' : '正在自动探测 ONVIF Backchannel…', '');
    // 无论是否已标记，点开都先跑一次探测，避免「没反应」
    await talkReprobe(false);
}
async function closeTalkModal() {
    await talkStop(true);
    const modal = document.getElementById('talkModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
}
async function talkReprobe(silentFail) {
    if (!talkState.streamId) return;
    setTalkUi('正在探测 ONVIF RTSP Audio Backchannel…', '');
    try {
        const res = await fetch('/api/talk/probe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stream_id: talkState.streamId, persist: true })
        });
        const data = await res.json();
        if (!data.success) {
            setTalkUi('探测失败', data.message || '');
            return;
        }
        const ok = !!data.talk_supported;
        setTalkUi(
            ok ? '探测成功：支持对讲' : '探测结果：不支持 / 未开放 Backchannel',
            data.detail || data.error || data.sdp_summary || ''
        );
        const accessPage = document.getElementById('accessPage');
        if (accessPage && accessPage.style.display !== 'none') {
            if (currentAccessTab === 'onvif' && typeof loadOnvifStreams === 'function') {
                await loadOnvifStreams();
            } else if (currentAccessTab === 'direct' && typeof loadDirectStreams === 'function') {
                await loadDirectStreams();
            } else if (currentAccessTab === 'gb28181' && typeof loadGb28181Streams === 'function') {
                await loadGb28181Streams();
            }
        }
        if (typeof loadStatusData === 'function') await loadStatusData();
    } catch (e) {
        if (!silentFail) setTalkUi('探测异常', String(e));
    }
}
async function talkStart() {
    if (!talkState.streamId || talkState.sending) return;
    setTalkUi('正在建立对讲会话…', '');
    try {
        const res = await fetch('/api/talk/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stream_id: talkState.streamId })
        });
        const data = await res.json();
        if (!data.success) {
            setTalkUi('无法开始对讲', data.message || JSON.stringify(data.probe || {}));
            return;
        }
        talkState.sessionId = data.session_id;
        talkState.codec = data.codec || 'PCMA';
        talkState.sending = true;
        setTalkUi('对讲中：请对着麦克风说话', data.detail || '');
        await talkStartMic(talkState.codec);
    } catch (e) {
        setTalkUi('开始对讲失败', String(e));
        talkState.sending = false;
    }
}
async function talkStartMic(codec) {
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            echoCancellation: true,
            noiseSuppression: true,
            channelCount: 1
        },
        video: false
    });
    talkState.mediaStream = stream;
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    talkState.audioCtx = audioCtx;
    const source = audioCtx.createMediaStreamSource(stream);
    const bufferSize = 2048;
    const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    talkState.processor = processor;
    let pending = new Float32Array(0);
    processor.onaudioprocess = function(ev) {
        if (!talkState.sending || !talkState.sessionId) return;
        const input = ev.inputBuffer.getChannelData(0);
        const ds = downsampleTo8k(input, audioCtx.sampleRate);
        const merged = new Float32Array(pending.length + ds.length);
        merged.set(pending, 0);
        merged.set(ds, pending.length);
        // 约 40ms = 320 samples @8k，攒够再发
        const frame = 320;
        let offset = 0;
        const chunks = [];
        while (offset + frame <= merged.length) {
            chunks.push(encodeG711(merged.subarray(offset, offset + frame), codec));
            offset += frame;
        }
        pending = merged.subarray(offset);
        if (!chunks.length) return;
        let total = 0;
        chunks.forEach(c => { total += c.length; });
        const body = new Uint8Array(total);
        let o = 0;
        chunks.forEach(c => { body.set(c, o); o += c.length; });
        fetch('/api/talk/audio?session_id=' + encodeURIComponent(talkState.sessionId), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/octet-stream',
                'X-Talk-Session': talkState.sessionId
            },
            body: body,
            credentials: 'same-origin'
        }).catch(function() { /* 丢包忽略 */ });
    };
    const mute = audioCtx.createGain();
    mute.gain.value = 0;
    source.connect(processor);
    processor.connect(mute);
    mute.connect(audioCtx.destination);
}
async function talkStop(quiet) {
    talkState.sending = false;
    try {
        if (talkState.processor) {
            talkState.processor.disconnect();
            talkState.processor.onaudioprocess = null;
        }
    } catch (_) {}
    talkState.processor = null;
    try {
        if (talkState.mediaStream) {
            talkState.mediaStream.getTracks().forEach(t => t.stop());
        }
    } catch (_) {}
    talkState.mediaStream = null;
    try {
        if (talkState.audioCtx) await talkState.audioCtx.close();
    } catch (_) {}
    talkState.audioCtx = null;
    const sid = talkState.sessionId;
    const streamId = talkState.streamId;
    talkState.sessionId = null;
    if (sid || streamId) {
        try {
            await fetch('/api/talk/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sid || '', stream_id: streamId || '' })
            });
        } catch (_) {}
    }
    if (!quiet) setTalkUi('已结束对讲', '');
}

document.getElementById('talkModalCloseBtn')?.addEventListener('click', closeTalkModal);
document.getElementById('talkStartBtn')?.addEventListener('click', talkStart);
document.getElementById('talkStopBtn')?.addEventListener('click', function() { talkStop(false); });
document.getElementById('talkReprobeBtn')?.addEventListener('click', function() { talkReprobe(false); });
document.getElementById('talkModal')?.addEventListener('click', function(e) {
    if (e.target === this) closeTalkModal();
});

document.getElementById('onvifPassToggle')?.addEventListener('click', () => {
    const input = document.getElementById('onvifPassword');
    const btn = document.getElementById('onvifPassToggle');
    if (!input || !btn) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.textContent = show ? '🙈' : '👁';
    btn.title = show ? '隐藏密码' : '显示密码';
});


// 图片预览功能
const modal = document.getElementById('imageModal');
const modalImg = document.getElementById('modalImage');
const imageModalCloseBtn = document.getElementById('imageModalCloseBtn');

document.addEventListener('click', function(e) {
    if (e.target && e.target.classList.contains('alert-image')) {
        if (modal && modalImg) {
            modal.style.display = 'block';
            modalImg.src = e.target.src;
        }
    }
});

if (imageModalCloseBtn) {
    imageModalCloseBtn.onclick = function() {
        modal.style.display = 'none';
    };
}

window.addEventListener('click', function(e) {
    if (e.target === modal) {
        modal.style.display = 'none';
    }
    const cfg = document.getElementById('detectionConfigModal');
    if (e.target === cfg) {
        closeDetectionConfigModal();
    }
    const spm = document.getElementById('streamPreviewModal');
    if (e.target === spm) {
        closeStreamPreview();
    }
    const ov = document.getElementById('onvifModal');
    if (e.target === ov) {
        closeOnvifModal();
    }
});

document.getElementById('streamPreviewCloseBtn')?.addEventListener('click', closeStreamPreview);
document.getElementById('streamPreviewSnapshotBtn')?.addEventListener('click', captureStreamPreview);
document.getElementById('streamPreviewTalkBtn')?.addEventListener('click', toggleGbTalk);
(function bindGbPtzPad() {
    const pad = document.getElementById('gbPtzPad');
    if (!pad) return;
    const speed = document.getElementById('gbPtzSpeed');
    const speedVal = document.getElementById('gbPtzSpeedVal');
    if (speed && speedVal) {
        speed.addEventListener('input', function () { speedVal.textContent = String(gbPtzSpeed()); });
    }
    const stopHold = function () { gbPtzHoldStop(); };
    pad.addEventListener('mousedown', function (e) {
        const hold = e.target.closest('[data-gb-ptz-hold]');
        if (hold) {
            e.preventDefault();
            gbPtzHoldStart(hold.getAttribute('data-gb-ptz-hold'));
        }
    });
    pad.addEventListener('mouseup', stopHold);
    pad.addEventListener('mouseleave', stopHold);
    pad.addEventListener('touchstart', function (e) {
        const hold = e.target.closest('[data-gb-ptz-hold]');
        if (hold) {
            e.preventDefault();
            gbPtzHoldStart(hold.getAttribute('data-gb-ptz-hold'));
        }
    }, { passive: false });
    pad.addEventListener('touchend', stopHold);
    pad.addEventListener('touchcancel', stopHold);
    window.addEventListener('blur', stopHold);
})();
document.getElementById('detectionConfigModalCloseBtn')?.addEventListener('click', closeDetectionConfigModal);
document.getElementById('detectionConfigCancelBtn')?.addEventListener('click', closeDetectionConfigModal);
document.getElementById('detectionConfigSearch')?.addEventListener('input', function() {
    renderDetectionModalList(this.value);
});
document.getElementById('fatiguePresetUnlimited')?.addEventListener('click', function () {
    detectionFatigueDraft = Object.assign(defaultFatigueConfig(), {
        preset: 'unlimited', pull_mode: 'always', pull_interval_sec: 0,
        window_mode: 'duration', window_duration_sec: 30, window_frames: 240, sample_fps: 8
    });
    syncFatiguePanelFromDraft();
});
document.getElementById('fatiguePresetSim')?.addEventListener('click', function () {
    detectionFatigueDraft = Object.assign(defaultFatigueConfig(), {
        preset: 'sim', pull_mode: 'burst', pull_interval_sec: 45,
        window_mode: 'duration', window_duration_sec: 6, window_frames: 30, sample_fps: 5
    });
    syncFatiguePanelFromDraft();
});
['fgPullMode', 'fgWindowMode', 'fgPullInterval', 'fgWindowSec', 'fgWindowFrames', 'fgSampleFps'].forEach(function (id) {
    document.getElementById(id)?.addEventListener('change', function () {
        readFatiguePanelToDraft();
    });
});
document.getElementById('detectionConfigSaveBtn')?.addEventListener('click', function() {
    if (!detectionConfigTargetItem || !detectionModalDraft) {
        closeDetectionConfigModal();
        return;
    }
    detectionConfigTargetItem._detections = JSON.parse(JSON.stringify(detectionModalDraft));
    readFaceRecogPanelToDraft();
    detectionConfigTargetItem._face_recognition_config = JSON.parse(JSON.stringify(detectionFaceRecogDraft));
    readPlateRecogPanelToDraft();
    detectionConfigTargetItem._plate_recognition_config = JSON.parse(JSON.stringify(detectionPlateRecogDraft));
    readFatiguePanelToDraft();
    detectionConfigTargetItem._fatigue_driving_config = JSON.parse(JSON.stringify(detectionFatigueDraft));
    updateStreamDetectionSummary(detectionConfigTargetItem);
    showMessage('已写入本条算法配置（请再点「保存检测配置」生效；检测策略热更新，无需重启）', 'success');
    closeDetectionConfigModal();
});

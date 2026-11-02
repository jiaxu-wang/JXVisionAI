/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* alerts.js */

function startAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    autoRefreshInterval = setInterval(() => {
        // 检查是否在历史告警页面
        const alertsPage = document.getElementById('alertsPage');
        if (alertsPage && alertsPage.style.display !== 'none') {
            loadAlertsData(currentPage);
        }
    }, configRefreshInterval);
}

function syncAlertsPageSizeSelect() {
    const sel = document.getElementById('alertsPageSizeSelect');
    if (!sel) return;
    const v = String(itemsPerPage);
    if ([...sel.options].some(o => o.value === v)) {
        sel.value = v;
    } else {
        sel.value = '5';
        itemsPerPage = 5;
    }
}

// 加载告警数据
async function loadAlertsData(page = 1) {
    try {
        fillAlertFilterTypeOptions();
        await ensureAlertFilterStreamsSelect();
        const qs = buildAlertsQueryParams(page).toString();
        const response = await fetch('/api/detections?' + qs);
        const result = await response.json();
        
        if (result.success) {
            renderAlertsTable(result.data);
            renderPagination(result.total, page);
            currentPage = page;
        } else {
            showMessage(t('alerts.loadFail', { err: result.message }), 'error');
        }
    } catch (error) {
        showMessage(t('alerts.loadFail', { err: error.message }), 'error');
    }
}

// 渲染告警表格
function renderAlertsTable(detections) {
    const tableBody = document.getElementById('alertsTableBody');
    tableBody.innerHTML = '';
    
    if (detections.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #6c757d; padding: 30px;">' + t('alerts.empty') + '</td></tr>';
        return;
    }
    
    detections.forEach(detection => {
        const row = document.createElement('tr');
        
        const formattedTime = formatAlertTime(detection.timestamp);
        
        // 格式化检测类型（相同文案只显示一次）
        const types = Array.isArray(detection.detection_types)
            ? detection.detection_types
            : [];
        const detectionType = [...new Set(types.map(function (x) { return formatType(String(x)); }))].join(', ');
        
        // 统一走后端回源（对象存储或本地绝对路径均可）；避免前端误拼绝对路径
        let imageUrl = '';
        if (detection.id) {
            imageUrl = '/api/alert-image/' + encodeURIComponent(detection.id);
            if (detection.stream_id) {
                imageUrl += '?stream_id=' + encodeURIComponent(detection.stream_id);
            }
        } else if (detection.image_path) {
            const norm = String(detection.image_path).replace(/\\/g, '/');
            const marker = '/snapshots/';
            const idx = norm.lastIndexOf(marker);
            if (idx >= 0) {
                imageUrl =
                    '/snapshots/' +
                    norm
                        .slice(idx + marker.length)
                        .split('/')
                        .filter(Boolean)
                        .map(encodeURIComponent)
                        .join('/');
            }
        }
        const noImg = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MCIgaGVpZ2h0PSI2MCIgdmlld0JveD0iMCAwIDgwIDYwIj48cGF0aCBkPSJNMTAgMTBoNjB2NDBoLTYweiIvPjxwYXRoIGQ9Ik0zMCAzMGMwLTEwIDgtMjAgMTgtMjAgMTAgMCAxOCA4IDE4IDIwcy04IDIwLTE4IDIwLTE4LTgtMTgtMjB6IiBzdHJva2U9IiMyMTk2RjMiIGZpbGw9Im5vbmUiLz48L3N2Zz4=';
        const imgSrc = imageUrl || noImg;
        const hasClip = !!(detection.video_path || detection.video_object_key);
        const clipBtn = hasClip
            ? '<div><button type="button" class="btn-filter-apply alert-clip-btn" data-id="' + escapeHtml(detection.id || '') + '" data-stream-id="' + escapeHtml(detection.stream_id || '') + '">' + t('alerts.playClip') + '</button></div>'
            : '';
        
        row.innerHTML = `
            <td><input type="checkbox" class="alert-checkbox" value="${detection.id}" data-stream-id="${detection.stream_id || ''}"></td>
            <td>${formattedTime}</td>
            <td>${detection.stream_name}</td>
            <td>${detectionType}</td>
            <td><img src="${imgSrc}" class="alert-image" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MCIgaGVpZ2h0PSI2MCIgdmlld0JveD0iMCAwIDgwIDYwIj48cGF0aCBkPSJNMTAgMTBoNjB2NDBoLTYweiIvPjxwYXRoIGQ9Ik0zMCAzMGMwLTEwIDgtMjAgMTgtMjAgMTAgMCAxOCA4IDE4IDIwcy04IDIwLTE4IDIwLTE4LTgtMTgtMjB6IiBzdHJva2U9IiMyMTk2RjMiIGZpbGw9Im5vbmUiLz48L3N2Zz4='">${clipBtn}</td>
            <td><button class="btn-delete" onclick="deleteAlert('${detection.id}','${detection.stream_id || ''}')">${t('common.delete')}</button></td>
        `;
        tableBody.appendChild(row);
    });
    tableBody.querySelectorAll('.alert-clip-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            playAlertClip(btn.getAttribute('data-id'), btn.getAttribute('data-stream-id'));
        });
    });
}

var alertClipTimer = 0;

function closeAlertClip() {
    if (alertClipTimer) {
        clearTimeout(alertClipTimer);
        alertClipTimer = 0;
    }
    const modal = document.getElementById('alertClipModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
}

function playAlertClip(id, streamId) {
    if (!id) return;
    const modal = document.getElementById('alertClipModal');
    const canvas = document.getElementById('alertClipCanvas');
    const msg = document.getElementById('alertClipMsg');
    if (!modal || !canvas) return;
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    if (msg) msg.textContent = t('alerts.clipLoading');
    let url = '/api/alert-clip/' + encodeURIComponent(id);
    if (streamId) url += '?stream_id=' + encodeURIComponent(streamId);
    fetch(url, { credentials: 'same-origin' })
        .then(function (r) {
            if (!r.ok) throw new Error('clip');
            return r.arrayBuffer();
        })
        .then(function (buf) {
            const parsed = parseAlertClip(buf);
            if (!parsed || !parsed.frames.length) throw new Error('clip');
            if (msg) msg.textContent = t('alerts.clipHint');
            drawAlertClip(canvas, parsed.frames, parsed.fps);
        })
        .catch(function () {
            if (msg) msg.textContent = t('alerts.clipFail');
        });
}

function parseAlertClip(buf) {
    const bytes = new Uint8Array(buf);
    const magic = [74, 86, 67, 76, 73, 80, 49];
    if (bytes.length < 13) return null;
    for (let i = 0; i < magic.length; i++) {
        if (bytes[i] !== magic[i]) return null;
    }
    const view = new DataView(buf);
    const fps = view.getFloat32(7, true) || 4;
    const count = view.getUint16(11, true);
    let off = 13;
    const frames = [];
    for (let i = 0; i < count; i++) {
        if (off + 4 > bytes.length) return null;
        const n = view.getUint32(off, true);
        off += 4;
        if (off + n > bytes.length) return null;
        frames.push(bytes.slice(off, off + n));
        off += n;
    }
    return { fps: fps, frames: frames };
}

function drawAlertClip(canvas, frames, fps) {
    if (alertClipTimer) clearTimeout(alertClipTimer);
    const ctx = canvas.getContext('2d');
    let index = 0;
    const wait = Math.max(40, Math.round(1000 / (fps || 4)));
    function step() {
        const blob = new Blob([frames[index]], { type: 'image/jpeg' });
        const img = new Image();
        const url = URL.createObjectURL(blob);
        img.onload = function () {
            canvas.width = img.naturalWidth || 640;
            canvas.height = img.naturalHeight || 360;
            ctx.drawImage(img, 0, 0);
            URL.revokeObjectURL(url);
            index = (index + 1) % frames.length;
            alertClipTimer = setTimeout(step, wait);
        };
        img.onerror = function () {
            URL.revokeObjectURL(url);
        };
        img.src = url;
    }
    step();
}

document.getElementById('alertClipClose')?.addEventListener('click', closeAlertClip);

// 渲染分页
function renderPagination(total, currentPage) {
    const pagination = document.getElementById('pagination');
    const totalPages = Math.ceil(total / itemsPerPage);
    
    let html = '';
    
    // 上一页
    html += `<button onclick="loadAlertsData(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>${t('alerts.prev')}</button>`;
    
    // 页码
    if (totalPages <= 5) {
        // 总页数小于等于5时，显示所有页码
        for (let i = 1; i <= totalPages; i++) {
            html += `<button onclick="loadAlertsData(${i})" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
        }
    } else {
        // 显示第1页
        html += `<button onclick="loadAlertsData(1)" class="${1 === currentPage ? 'active' : ''}">1</button>`;
        
        // 前两页
        if (currentPage > 4) {
            html += `<span>...</span>`;
        }
        
        // 当前页附近的页码（前2页到后2页）
        for (let i = Math.max(2, currentPage - 2); i <= Math.min(totalPages - 1, currentPage + 2); i++) {
            html += `<button onclick="loadAlertsData(${i})" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
        }
        
        // 后两页
        if (currentPage < totalPages - 3) {
            html += `<span>...</span>`;
        }
        
        // 最后一页
        html += `<button onclick="loadAlertsData(${totalPages})" class="${totalPages === currentPage ? 'active' : ''}">${totalPages}</button>`;
    }
    
    // 页码输入和跳转
    html += `
        <span style="margin-left: 10px; display: flex; align-items: center; gap: 5px;">
            <input type="number" id="pageInput" min="1" max="${totalPages}" value="${currentPage}" style="width: 60px; padding: 6px; border: 1px solid #ced4da; border-radius: 4px; text-align: center;">
            <button onclick="jumpToPage()" style="padding: 6px 12px; border: 1px solid #ced4da; background: white; border-radius: 4px; cursor: pointer;">${t('alerts.jump')}</button>
        </span>
    `;
    
    // 下一页
    html += `<button onclick="loadAlertsData(${currentPage + 1})" ${currentPage === totalPages || totalPages === 0 ? 'disabled' : ''}>${t('alerts.next')}</button>`;
    
    pagination.innerHTML = html;
}

// 跳转到指定页码
function jumpToPage() {
    const pageInput = document.getElementById('pageInput');
    const page = parseInt(pageInput.value);
    const totalPages = parseInt(pageInput.max);
    
    if (page >= 1 && page <= totalPages) {
        loadAlertsData(page);
    } else {
        showMessage(t('alerts.pageRange'), 'error');
    }
}

// 删除告警
async function deleteAlert(id, streamId) {
    if (confirm(t('alerts.delOne'))) {
        try {
            const qs = streamId ? ('?stream_id=' + encodeURIComponent(streamId)) : '';
            const response = await fetch(`/api/detections/${encodeURIComponent(id)}${qs}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            
            if (result.success) {
                showMessage(t('alerts.deleted'), 'success');
                loadAlertsData(currentPage);
            } else {
                showMessage(t('alerts.delFail', { err: result.message }), 'error');
            }
        } catch (error) {
            showMessage(t('alerts.delFail', { err: error.message }), 'error');
        }
    }
}

// 全选/取消全选
document.getElementById('selectAll')?.addEventListener('change', function() {
    const checkboxes = document.querySelectorAll('.alert-checkbox');
    checkboxes.forEach(checkbox => {
        checkbox.checked = this.checked;
    });
});

document.getElementById('alertFilterApply')?.addEventListener('click', function() {
    loadAlertsData(1);
});
document.getElementById('alertFilterReset')?.addEventListener('click', function() {
    document.getElementById('alertFilterStart').value = '';
    document.getElementById('alertFilterEnd').value = '';
    document.getElementById('alertFilterStream').value = '';
    document.getElementById('alertFilterType').value = '';
    loadAlertsData(1);
});

// 删除选中的告警
document.getElementById('alertsPageSizeSelect')?.addEventListener('change', function() {
    const n = parseInt(this.value, 10);
    if (!ALERTS_PAGE_SIZE_OPTIONS.includes(n)) {
        this.value = '5';
        itemsPerPage = 5;
    } else {
        itemsPerPage = n;
    }
    loadAlertsData(1);
});

document.getElementById('deleteSelectedBtn')?.addEventListener('click', async function() {
    const selectedCheckboxes = document.querySelectorAll('.alert-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        showMessage(t('alerts.selectFirst'), 'error');
        return;
    }
    
    if (confirm(t('alerts.delN', { n: selectedCheckboxes.length }))) {
        try {
            const items = Array.from(selectedCheckboxes).map(cb => ({
                id: cb.value,
                stream_id: cb.getAttribute('data-stream-id') || ''
            }));
            const response = await fetch('/api/detections/batch', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ items: items })
            });
            const result = await response.json();
            
            if (result.success) {
                showMessage(result.message, 'success');
                loadAlertsData(currentPage);
            } else {
                showMessage(t('alerts.delFail', { err: result.message }), 'error');
            }
        } catch (error) {
            showMessage(t('alerts.delFail', { err: error.message }), 'error');
        }
    }
});

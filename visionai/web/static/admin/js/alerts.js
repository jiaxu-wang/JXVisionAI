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
        
        row.innerHTML = `
            <td><input type="checkbox" class="alert-checkbox" value="${detection.id}"></td>
            <td>${formattedTime}</td>
            <td>${detection.stream_name}</td>
            <td>${detectionType}</td>
            <td><img src="${imgSrc}" class="alert-image" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MCIgaGVpZ2h0PSI2MCIgdmlld0JveD0iMCAwIDgwIDYwIj48cGF0aCBkPSJNMTAgMTBoNjB2NDBoLTYweiIvPjxwYXRoIGQ9Ik0zMCAzMGMwLTEwIDgtMjAgMTgtMjAgMTAgMCAxOCA4IDE4IDIwcy04IDIwLTE4IDIwLTE4LTgtMTgtMjB6IiBzdHJva2U9IiMyMTk2RjMiIGZpbGw9Im5vbmUiLz48L3N2Zz4='"></td>
            <td><button class="btn-delete" onclick="deleteAlert('${detection.id}')">${t('common.delete')}</button></td>
        `;
        tableBody.appendChild(row);
    });
}

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
async function deleteAlert(id) {
    if (confirm(t('alerts.delOne'))) {
        try {
            const response = await fetch(`/api/detections/${id}`, {
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
            const ids = Array.from(selectedCheckboxes).map(cb => cb.value);
            const response = await fetch('/api/detections/batch', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ ids: ids })
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

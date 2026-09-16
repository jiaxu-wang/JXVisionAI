/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* settings.js */

// 显示消息
let settingsFormDirty = false;

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function renderSettingsMeta(meta) {
    const el = document.getElementById('settingsMeta');
    if (!el || !meta) return;
    const parts = [
        '路径: ' + (meta.path || ''),
        meta.mtime ? ('最后修改: ' + meta.mtime) : '',
        meta.priority || '',
    ];
    if (meta.env_config_override) {
        parts.push('环境变量 VISIONAI_CONFIG=' + meta.env_config_override);
    }
    el.textContent = parts.filter(Boolean).join(' · ');
}

const TIMEZONE_OPTIONS = [
    'Asia/Shanghai',
    'Asia/Hong_Kong',
    'Asia/Tokyo',
    'Asia/Singapore',
    'Asia/Kolkata',
    'Europe/London',
    'Europe/Berlin',
    'Europe/Paris',
    'Europe/Moscow',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Sao_Paulo',
    'Australia/Sydney',
    'Pacific/Auckland',
    'UTC',
];

function renderConfigFieldInput(field) {
    const key = field.key;
    const val = field.value == null ? '' : String(field.value);
    const type = field.type || 'text';
    if (field.readonly || !field.editable) {
        return '<div class="config-field-readonly">' + escapeHtml(val) + '</div>';
    }
    if (type === 'bool') {
        const checked = ['true', '1', 'yes', 'on'].includes(val.toLowerCase());
        return '<label><input type="checkbox" class="cfg-input" data-cfg-key="' + escapeHtml(key) + '" ' + (checked ? 'checked' : '') + '> 启用</label>';
    }
    if (type === 'timezone' || key === 'timezone') {
        const opts = TIMEZONE_OPTIONS.slice();
        if (val && opts.indexOf(val) < 0) opts.unshift(val);
        const optionsHtml = opts.map(function (z) {
            return '<option value="' + escapeHtml(z) + '"' + (z === val ? ' selected' : '') + '>' + escapeHtml(z) + '</option>';
        }).join('');
        return (
            '<select class="config-field-input cfg-input" data-cfg-key="' + escapeHtml(key) + '">' +
            optionsHtml +
            '</select>'
        );
    }
    const inputType = (type === 'password') ? 'password' : ((type === 'int' || type === 'float') ? 'text' : 'text');
    return '<input type="' + inputType + '" class="config-field-input cfg-input" data-cfg-key="' + escapeHtml(key) + '" value="' + escapeHtml(val) + '">';
}

function renderConfigUnits(units) {
    const wrap = document.getElementById('configUnitsWrap');
    if (!wrap) return;
    if (!units || !units.length) {
        wrap.textContent = '无配置项';
        return;
    }
    wrap.innerHTML = units.map(function (unit) {
        const editableFields = (unit.fields || []).filter(function (field) {
            return field.editable !== false && !field.readonly;
        });
        if (!editableFields.length) {
            return '';
        }
        const fieldsHtml = editableFields.map(function (field) {
            let badge = '';
            if (field.commented_only) {
                badge = '<span class="config-field-badge">ini 中已注释</span>';
            }
            const commentHtml = field.comment
                ? '<div class="config-field-comment">' + escapeHtml(field.comment) + '</div>'
                : '';
            return (
                '<div class="config-field-row">' +
                '<div class="config-field-label">' + escapeHtml(field.label || field.key) + badge + '</div>' +
                '<div class="config-field-body">' + commentHtml + renderConfigFieldInput(field) + '</div>' +
                '</div>'
            );
        }).join('');
        const desc = unit.description
            ? '<p class="config-unit-desc">' + escapeHtml(unit.description) + '</p>'
            : '';
        return (
            '<section class="config-unit-card" data-unit-id="' + escapeHtml(unit.id || '') + '">' +
            '<h3>' + escapeHtml(unit.title || '') + '</h3>' + desc + fieldsHtml +
            '</section>'
        );
    }).filter(Boolean).join('');
    wrap.querySelectorAll('.cfg-input').forEach(function (el) {
        el.addEventListener('change', function () { settingsFormDirty = true; });
        el.addEventListener('input', function () { settingsFormDirty = true; });
    });
    settingsFormDirty = false;
}

function collectConfigUpdates() {
    const updates = {};
    document.querySelectorAll('.cfg-input').forEach(function (el) {
        const key = el.getAttribute('data-cfg-key');
        if (!key) return;
        if (el.type === 'checkbox') {
            updates[key] = el.checked ? 'true' : 'false';
        } else {
            updates[key] = el.value;
        }
    });
    return updates;
}

async function reloadSystemSettings() {
    if (settingsFormDirty && !confirm('有未保存的修改，重新加载将丢弃，是否继续？')) {
        return;
    }
    await loadSystemSettings();
}

async function loadSystemSettings() {
    const wrap = document.getElementById('configUnitsWrap');
    if (wrap) wrap.textContent = '加载中…';
    try {
        const res = await fetch('/api/system/config');
        const data = await res.json();
        if (!data.success) {
            showMessage(data.message || '加载配置失败', 'error');
            if (wrap) wrap.textContent = '加载失败';
            return;
        }
        renderSettingsMeta(data.meta);
        renderConfigUnits(data.units || []);
    } catch (err) {
        showMessage('加载配置失败: ' + err, 'error');
        if (wrap) wrap.textContent = '加载失败';
    }
}

async function saveSystemConfig() {
    if (settingsFormDirty === false) {
        showMessage('没有修改需要保存', 'success');
        return;
    }
    const btn = document.getElementById('saveConfigIniBtn');
    if (btn) btn.disabled = true;
    try {
        const updates = collectConfigUpdates();
        const res = await fetch('/api/system/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates: updates }),
        });
        const data = await res.json();
        if (!data.success) {
            showMessage(data.message || '保存失败', 'error');
            return;
        }
        settingsFormDirty = false;
        showMessage(data.message || '保存成功', 'success');
        await loadSystemSettings();
    } catch (err) {
        showMessage('保存失败: ' + err, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function restartJXVisionAIService() {
    if (!confirm('确定重启 JXVisionAI 服务？重启期间检测与页面会短暂中断。')) {
        return;
    }
    try {
        const res = await fetch('/api/restart', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showMessage('服务正在重启，约 10～20 秒后请刷新页面', 'success');
            setTimeout(function () { window.location.reload(); }, 12000);
        } else {
            showMessage(data.message || '重启失败', 'error');
        }
    } catch (err) {
        showMessage('重启请求失败: ' + err, 'error');
    }
}

function showMessage(text, type) {
    const message = document.getElementById('message');
    if (!message) {
        return;
    }
    message.textContent = text;
    message.className = `message ${type}`;
    message.style.display = 'block';
    
    setTimeout(() => {
        message.style.display = 'none';
    }, 5000);
}

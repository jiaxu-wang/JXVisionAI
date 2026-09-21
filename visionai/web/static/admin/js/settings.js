/* JXVisionAI admin — extracted from templates/admin.html; classic globals, load order matters. */
/* settings.js */

let settingsFormDirty = false;
let lastSettingsUnits = null;
let lastSettingsMeta = null;

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function settingsLocale() {
    if (typeof getLocale === 'function') return getLocale();
    if (window.VisionAI && VisionAI.i18n && typeof VisionAI.i18n.getLocale === 'function') {
        return VisionAI.i18n.getLocale();
    }
    return 'zh';
}

function localeText(obj, zhKey, enKey) {
    if (!obj) return '';
    if (settingsLocale() === 'en') return obj[enKey] || obj[zhKey] || '';
    return obj[zhKey] || obj[enKey] || '';
}

function settingsApiMessage(data, fallbackKey) {
    const m = data && data.message;
    const map = {
        '已保存到 config.ini，请重启服务后全配置生效': 'settings.savedRestart',
        '缺少 updates 对象': 'settings.missingUpdates',
        '提交的配置项无效': 'settings.invalidUpdates',
        'config.ini 不存在或为空': 'settings.emptyIni',
        '没有可保存的配置项': 'settings.noSaveItems',
    };
    if (m && map[m]) return t(map[m]);
    if (m) return m;
    return t(fallbackKey);
}

function renderSettingsMeta(meta) {
    const el = document.getElementById('settingsMeta');
    if (!el) return;
    if (!meta) {
        el.textContent = '';
        return;
    }
    const parts = [
        t('settings.metaPath') + ': ' + (meta.path || ''),
        meta.mtime ? (t('settings.metaMtime') + ': ' + meta.mtime) : '',
        localeText(meta, 'priority', 'priority_en') || t('settings.metaPriority'),
    ];
    if (meta.env_config_override) {
        parts.push(t('settings.metaEnv') + '=' + meta.env_config_override);
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
        const shown = localeText(field, 'value', 'value_en') || val;
        return '<div class="config-field-readonly">' + escapeHtml(shown) + '</div>';
    }
    if (type === 'bool') {
        const checked = ['true', '1', 'yes', 'on'].includes(val.toLowerCase());
        return '<label><input type="checkbox" class="cfg-input" data-cfg-key="' + escapeHtml(key) + '" ' + (checked ? 'checked' : '') + '> ' + escapeHtml(t('settings.enable')) + '</label>';
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
        wrap.textContent = t('settings.empty');
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
                badge = '<span class="config-field-badge">' + escapeHtml(t('settings.commentedOnly')) + '</span>';
            }
            const comment = localeText(field, 'comment', 'comment_en');
            const commentHtml = comment
                ? '<div class="config-field-comment">' + escapeHtml(comment) + '</div>'
                : '';
            const label = localeText(field, 'label', 'label_en') || field.key;
            return (
                '<div class="config-field-row">' +
                '<div class="config-field-label">' + escapeHtml(label) + badge + '</div>' +
                '<div class="config-field-body">' + commentHtml + renderConfigFieldInput(field) + '</div>' +
                '</div>'
            );
        }).join('');
        const desc = localeText(unit, 'description', 'description_en');
        const descHtml = desc
            ? '<p class="config-unit-desc">' + escapeHtml(desc) + '</p>'
            : '';
        return (
            '<section class="config-unit-card" data-unit-id="' + escapeHtml(unit.id || '') + '">' +
            '<h3>' + escapeHtml(localeText(unit, 'title', 'title_en')) + '</h3>' + descHtml + fieldsHtml +
            '</section>'
        );
    }).filter(Boolean).join('');
    wrap.querySelectorAll('.cfg-input').forEach(function (el) {
        el.addEventListener('change', function () { settingsFormDirty = true; });
        el.addEventListener('input', function () { settingsFormDirty = true; });
    });
    settingsFormDirty = false;
}

function applyCollectedUpdates(updates) {
    if (!updates) return;
    document.querySelectorAll('.cfg-input').forEach(function (el) {
        const key = el.getAttribute('data-cfg-key');
        if (!key || !Object.prototype.hasOwnProperty.call(updates, key)) return;
        if (el.type === 'checkbox') {
            el.checked = updates[key] === 'true';
        } else {
            el.value = updates[key];
        }
    });
}

function rerenderSystemSettingsKeepValues() {
    if (!lastSettingsUnits) return;
    const updates = collectConfigUpdates();
    const dirty = settingsFormDirty;
    renderSettingsMeta(lastSettingsMeta);
    renderConfigUnits(lastSettingsUnits);
    applyCollectedUpdates(updates);
    settingsFormDirty = dirty;
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
    if (settingsFormDirty && !confirm(t('settings.dirtyReload'))) {
        return;
    }
    await loadSystemSettings();
}

async function loadSystemSettings() {
    const wrap = document.getElementById('configUnitsWrap');
    if (wrap) wrap.textContent = t('settings.loading');
    try {
        const res = await fetch('/api/system/config');
        const data = await res.json();
        if (!data.success) {
            showMessage(settingsApiMessage(data, 'settings.loadCfgFail'), 'error');
            if (wrap) wrap.textContent = t('settings.loadFail');
            return;
        }
        lastSettingsMeta = data.meta || null;
        lastSettingsUnits = data.units || [];
        renderSettingsMeta(lastSettingsMeta);
        renderConfigUnits(lastSettingsUnits);
    } catch (err) {
        showMessage(t('settings.loadCfgFail') + ': ' + err, 'error');
        if (wrap) wrap.textContent = t('settings.loadFail');
    }
}

async function saveSystemConfig() {
    if (settingsFormDirty === false) {
        showMessage(t('settings.noChanges'), 'success');
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
            showMessage(settingsApiMessage(data, 'settings.saveFail'), 'error');
            return;
        }
        settingsFormDirty = false;
        showMessage(settingsApiMessage(data, 'settings.savedRestart'), 'success');
        await loadSystemSettings();
    } catch (err) {
        showMessage(t('settings.saveFail') + ': ' + err, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function restartJXVisionAIService() {
    if (!confirm(t('settings.restartConfirm'))) {
        return;
    }
    try {
        const res = await fetch('/api/restart', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showMessage(t('settings.restarting'), 'success');
            setTimeout(function () { window.location.reload(); }, 12000);
        } else {
            showMessage(settingsApiMessage(data, 'settings.restartFail'), 'error');
        }
    } catch (err) {
        showMessage(t('settings.restartReqFail') + ': ' + err, 'error');
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

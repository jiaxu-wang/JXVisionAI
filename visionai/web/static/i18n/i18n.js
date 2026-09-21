/* JXVisionAI i18n：界面语言与协议字段分离。detection_types 仍存中文。 */
(function (global) {
    var STORAGE = "visionai.locale";
    var catalogs = { zh: {}, en: {} };
    var locale = "zh";
    var readyPromise = null;

    function getPath(obj, path) {
        if (!obj || !path) return undefined;
        var cur = obj;
        var parts = String(path).split(".");
        for (var i = 0; i < parts.length; i++) {
            if (cur == null || typeof cur !== "object") return undefined;
            cur = cur[parts[i]];
        }
        return cur;
    }

    function interpolate(s, vars) {
        if (!vars) return String(s);
        return String(s).replace(/\{(\w+)\}/g, function (_, k) {
            return vars[k] != null ? String(vars[k]) : "{" + k + "}";
        });
    }

    function t(key, vars) {
        var v = getPath(catalogs[locale] || {}, key);
        if (v == null || v === "") v = getPath(catalogs.zh || {}, key);
        if (v == null) v = key;
        return interpolate(v, vars);
    }

    function getLocale() {
        return locale === "en" ? "en" : "zh";
    }

    function catalogLabel(item) {
        if (!item) return "";
        if (getLocale() === "en") return item.name_en || item.name_zh || item.key || "";
        return item.name_zh || item.name_en || item.key || "";
    }

    function formatType(zhLabel) {
        var s = String(zhLabel || "");
        if (!s || getLocale() !== "en") return s;
        var cat = global.detectionCatalog;
        if (Array.isArray(cat)) {
            var best = null;
            for (var i = 0; i < cat.length; i++) {
                var zh = cat[i] && cat[i].name_zh;
                if (!zh) continue;
                if (s === zh) return cat[i].name_en || s;
                if (s.indexOf(zh) === 0 && (!best || zh.length > best.zh.length)) {
                    best = { zh: zh, en: cat[i].name_en || zh };
                }
            }
            if (best) return best.en + s.slice(best.zh.length);
        }
        var map = getPath(catalogs.en || {}, "typesMap") || {};
        if (map[s]) return map[s];
        return s;
    }

    function formatStreamStatus(status) {
        var s = String(status || "");
        var low = s.toLowerCase();
        if (s === "在线" || low === "online") return t("common.online");
        if (s === "离线" || low === "offline") return t("common.offline");
        if (s === "未知" || low === "unknown") return t("common.unknown");
        return s;
    }

    function applyI18n(root) {
        root = root || document;
        if (!root.querySelectorAll) return;
        root.querySelectorAll("[data-i18n]").forEach(function (el) {
            var key = el.getAttribute("data-i18n");
            if (!key) return;
            var attr = el.getAttribute("data-i18n-attr");
            var html = el.hasAttribute("data-i18n-html");
            var val = t(key);
            if (attr) el.setAttribute(attr, val);
            else if (html) el.innerHTML = val;
            else el.textContent = val;
        });
        root.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
            el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
        });
        root.querySelectorAll("[data-i18n-title]").forEach(function (el) {
            el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
        });
        root.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
            el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
        });
        if (document.documentElement) {
            document.documentElement.lang = getLocale() === "en" ? "en" : "zh-CN";
        }
        document.querySelectorAll(".lang-switch [data-locale]").forEach(function (btn) {
            btn.classList.toggle("active", btn.getAttribute("data-locale") === getLocale());
        });
    }

    function notifyLocaleChange() {
        if (typeof global.__visionaiOnLocaleChange === "function") {
            try {
                global.__visionaiOnLocaleChange(getLocale());
            } catch (e) { /* ignore */ }
        }
    }

    function hasStoredLocale() {
        try {
            var stored = localStorage.getItem(STORAGE);
            return stored === "en" || stored === "zh";
        } catch (e) {
            return false;
        }
    }

    function readDefaultLocale() {
        var d = global.__VISIONAI_DEFAULT_LOCALE__;
        if (d === "en" || d === "zh") return d;
        return "zh";
    }

    function setLocale(next) {
        locale = next === "en" ? "en" : "zh";
        try {
            localStorage.setItem(STORAGE, locale);
        } catch (e) { /* ignore */ }
        applyI18n(document);
        notifyLocaleChange();
    }

    function mountLangSwitch(el) {
        if (!el) return;
        el.classList.add("lang-switch");
        el.innerHTML =
            '<button type="button" data-locale="zh">中文</button>' +
            '<span class="lang-switch-sep">|</span>' +
            '<button type="button" data-locale="en">EN</button>';
        el.addEventListener("click", function (e) {
            var b = e.target && e.target.closest ? e.target.closest("button[data-locale]") : null;
            if (!b) return;
            setLocale(b.getAttribute("data-locale"));
        });
        el.querySelectorAll("[data-locale]").forEach(function (btn) {
            btn.classList.toggle("active", btn.getAttribute("data-locale") === getLocale());
        });
    }

    function loadCatalogs() {
        var prefix = "/static/i18n/";
        var ver = "14";
        readyPromise = Promise.all([
            fetch(prefix + "zh.json?v=" + ver).then(function (r) { return r.json(); }),
            fetch(prefix + "en.json?v=" + ver).then(function (r) { return r.json(); }),
        ]).then(function (pair) {
            catalogs.zh = pair[0] || {};
            catalogs.en = pair[1] || {};
            applyI18n(document);
            return getLocale();
        }).catch(function () {
            applyI18n(document);
            return getLocale();
        });
        return readyPromise;
    }

    try {
        var stored = localStorage.getItem(STORAGE);
        if (stored === "en" || stored === "zh") locale = stored;
        else locale = readDefaultLocale();
    } catch (e) {
        locale = readDefaultLocale();
    }
    if (document.documentElement) {
        document.documentElement.lang = getLocale() === "en" ? "en" : "zh-CN";
    }

    global.t = t;
    global.formatType = formatType;
    global.formatStreamStatus = formatStreamStatus;
    global.catalogLabel = catalogLabel;
    global.VisionAI = global.VisionAI || {};
    global.VisionAI.i18n = {
        t: t,
        setLocale: setLocale,
        applyI18n: applyI18n,
        formatType: formatType,
        formatStreamStatus: formatStreamStatus,
        catalogLabel: catalogLabel,
        mountLangSwitch: mountLangSwitch,
        loadCatalogs: loadCatalogs,
        getLocale: getLocale,
        hasStoredLocale: hasStoredLocale,
        ready: function () {
            return readyPromise || loadCatalogs();
        },
    };
    loadCatalogs();
})(window);

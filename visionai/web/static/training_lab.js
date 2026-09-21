(function () {
  'use strict';

  const state = {
    projectId: null,
    projectClasses: [],
    deployTarget: null,
    deployMode: null,
    templateId: null,
    imageName: null,
    naturalW: 0,
    naturalH: 0,
    boxes: [],
    drag: null,
    selectedBox: -1,
    history: [],
    historyIndex: -1,
    annoImg: null,
    interaction: null,
    jobPoll: null,
    lastJobId: null,
    validatePollTimer: null,
    validateRunning: false,
    lastUploadedValidateFile: null,
    snapItems: [],
    snapVerdicts: {},
    sampleFiles: [],
    templates: [],
    projects: [],
    specialists: [],
    calibProjectId: null,
    calibKey: null,
    calibSpecialist: null,
    calibJobPoll: null,
    calibLastJobId: null,
  };

  const HANDLE = 8;
  const MIN_BOX = 4;

  const $ = (id) => document.getElementById(id);


  function tr(key, vars) {
    return typeof window.t === 'function' ? window.t(key, vars) : key;
  }

  function typeLabel(zh) {
    return typeof window.formatType === 'function' ? window.formatType(zh) : (zh || '');
  }

  function specialistLabel(sp) {
    if (!sp) return '';
    if (typeof window.catalogLabel === 'function') return window.catalogLabel(sp);
    return sp.name_zh || sp.name_en || sp.key || '';
  }

  function currentLocale() {
    if (window.VisionAI && VisionAI.i18n && typeof VisionAI.i18n.getLocale === 'function') {
      return VisionAI.i18n.getLocale();
    }
    return 'zh';
  }

  function templateTitle(tpl) {
    if (!tpl) return '';
    if (currentLocale() === 'en') {
      return tpl.title_en || tpl.title || tpl.id || '';
    }
    return tpl.title || tpl.title_en || tpl.id || '';
  }

  function templateDesc(tpl) {
    if (!tpl) return '';
    if (currentLocale() === 'en') {
      return tpl.description_en || tpl.description || '';
    }
    return tpl.description || tpl.description_en || '';
  }

  function jobStatusText(status) {
    if (status === 'completed') return tr('training.jobDone');
    if (status === 'failed') return tr('training.jobFailed');
    return tr('training.jobRunning');
  }

  function sampleStatusText(status) {
    if (status === 'reviewed') return tr('training.sampleReviewed');
    if (status === 'draft') return tr('training.sampleDraft');
    if (status === 'negative') return tr('training.sampleNeg');
    return tr('training.sampleUnlabeled');
  }

  function projectBadgeText(p) {
    if (!p) return '';
    var extra = '';
    if (state.deployTarget) extra = ' [' + state.deployTarget + ']';
    else if (state.deployMode === 'specialist') extra = ' ' + tr('training.badgeSpecialist');
    return ' · ' + p.title + extra;
  }

  function fillTemplateSelect() {
    var sel = $('np-template');
    if (!sel) return;
    var keep = sel.value;
    sel.innerHTML = '';
    (state.templates || []).forEach(function (tpl) {
      var o = document.createElement('option');
      o.value = tpl.id;
      o.textContent =
        templateTitle(tpl) + (tpl.id !== 'custom' ? ' (' + (tpl.classes || []).join(',') + ')' : '');
      sel.appendChild(o);
    });
    if (keep && Array.from(sel.options).some(function (o) { return o.value === keep; })) {
      sel.value = keep;
    }
    applyTemplateToForm(sel.value || 'smoking');
  }


  async function api(path, opts) {
    const r = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(opts && opts.headers) },
      ...opts,
    });
    return r;
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function stopValidatePolling() {
    if (state.validatePollTimer) {
      clearInterval(state.validatePollTimer);
      state.validatePollTimer = null;
    }
  }

  function setValidateUiRunning(run) {
    var stopB = $('btn-val-stop');
    var startB = $('btn-val-start');
    if (stopB) stopB.disabled = !run;
    if (startB) startB.disabled = !!run;
  }

  function resolveWeightsPath() {
    var manual = ($('val-weights-manual') && $('val-weights-manual').value.trim()) || '';
    if (manual) return manual;
    return (($('val-weights') && $('val-weights').value.trim()) || '');
  }

  function renderValidateLogs(items) {
    var div = $('val-log');
    if (!div) return;
    div.innerHTML = '';
    items.forEach(function (it) {
      var row = document.createElement('div');
      row.className = 'tl-val-entry';
      var kind = it.kind || 'infer';
      var head = document.createElement('div');
      head.className = 'tl-val-entry-head';
      head.innerHTML =
        esc(it.ts_iso || '') +
        ' <span class="tl-kind">' +
        esc(kind) +
        '</span>' +
        (it.source ? ' [' + esc(String(it.source)) + ']' : '') +
        '<br>' +
        esc(it.message || '');
      row.appendChild(head);
      if (it.snapshot) {
        var img = document.createElement('img');
        img.className = 'tl-val-thumb';
        img.alt = '';
        img.loading = 'lazy';
        img.src =
          '/api/training/projects/' +
          encodeURIComponent(state.projectId) +
          '/validate/snap/' +
          encodeURIComponent(it.snapshot) +
          '?_=' +
          (it.ts != null ? it.ts : Date.now());
        row.appendChild(img);
      }
      if (it.detections && it.detections.length) {
        var pre = document.createElement('pre');
        pre.className = 'tl-val-det';
        pre.textContent = tr('training.hitAbove') + JSON.stringify(it.detections, null, 2);
        row.appendChild(pre);
      }
      if (it.candidates && it.candidates.length) {
        var preC = document.createElement('pre');
        preC.className = 'tl-val-det';
        var floor = it.candidate_conf_floor != null ? it.candidate_conf_floor : '';
        preC.textContent =
          tr('training.candHead', {
            floor: floor,
            th: it.conf_threshold != null ? it.conf_threshold : '',
          }) + JSON.stringify(it.candidates, null, 2);
        row.appendChild(preC);
      }
      div.appendChild(row);
    });
  }

  async function refreshValidateLogs() {
    if (!state.projectId) return;
    var r = await api('/api/training/projects/' + state.projectId + '/validate/logs?limit=80');
    var items = await r.json();
    renderValidateLogs(items);
  }

  async function loadWeightOptions() {
    var sel = $('val-weights');
    if (!sel) return;
    sel.innerHTML = '<option value="">' + tr('training.pickWeights') + '</option>';
    if (!state.projectId) return;
    var r = await api('/api/training/projects/' + state.projectId + '/weights');
    var items = await r.json();
    items.forEach(function (it) {
      var o = document.createElement('option');
      o.value = it.path;
      o.textContent = it.label || it.path.split(/[/\\\\]/).pop();
      sel.appendChild(o);
    });
  }

  function startValidatePolling() {
    stopValidatePolling();
    state.validatePollTimer = setInterval(function () {
      refreshValidateLogs().catch(function () {});
    }, 2000);
  }

  async function deleteProjectEntry(p, ev) {
    if (ev) ev.stopPropagation();
    var msg = tr('training.delProjectConfirm', { title: p.title || p.id });
    if (!window.confirm(msg)) return;
    const r = await api('/api/training/projects/' + encodeURIComponent(p.id), { method: 'DELETE' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.success) {
      alert(j.message || tr('training.delFail'));
      return;
    }
    if (state.projectId === p.id) {
      state.projectId = null;
      syncDelProjectButton();
      state.projectClasses = [];
      $('current-project-label').textContent = '';
      fillClassPicker();
      clearCanvas();
      state.sampleFiles = [];
      $('sample-list').innerHTML = '';
      updateSampleNav();
      $('btn-capture').disabled = true;
      if (state.jobPoll) clearInterval(state.jobPoll);
      $('train-job-panel').classList.add('tl-hidden');
      stopValidatePolling();
      state.validateRunning = false;
      $('val-log').innerHTML = '';
      $('val-upload-status').textContent = '';
      state.lastUploadedValidateFile = null;
      setValidateUiRunning(false);
      $('val-cycle-status').textContent = '';
    }
    await loadProjects();
  }

  async function loadProjects() {
    const r = await api('/api/training/projects');
    const list = await r.json();
    state.projects = list;
    const ul = $('project-list');
    if (ul) {
      ul.innerHTML = '';
      list.forEach((p) => {
        const li = document.createElement('li');
        li.dataset.id = p.id;
        if (p.id === state.projectId) li.classList.add('active');

        const inner = document.createElement('div');
        inner.className = 'tl-project-inner';

        const body = document.createElement('div');
        body.className = 'tl-project-body';
        body.innerHTML =
          '<strong>' +
          esc(p.title) +
          '</strong><br><span class="tl-muted">' +
          esc(tr('training.labeledCount', { a: p.labeled_count, b: p.image_count })) +
          '</span>';
        body.addEventListener('click', () => selectProject(p.id));

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tl-project-del';
        btn.setAttribute('aria-label', tr('training.delProjectAria'));
        btn.setAttribute('title', tr('training.delProjectAria'));
        btn.textContent = '\u2715';
        btn.addEventListener('click', (ev) => deleteProjectEntry(p, ev));

        inner.appendChild(body);
        inner.appendChild(btn);
        li.appendChild(inner);
        ul.appendChild(li);
      });
    }
    renderProjectSelect();
  }

  function renderProjectSelect() {
    const sel = $('project-select');
    if (!sel) return;
    const list = state.projects || [];
    sel.innerHTML = '';
    if (!list.length) {
      const o = document.createElement('option');
      o.value = '';
      o.textContent = tr('training.noProjects');
      sel.appendChild(o);
      sel.value = '';
      return;
    }
    list.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.title + '（' + p.labeled_count + '/' + p.image_count + '）';
      sel.appendChild(o);
    });
    if (state.projectId && list.some(function (p) { return p.id === state.projectId; })) {
      sel.value = state.projectId;
    } else {
      sel.value = '';
    }
  }

  async function loadStreams() {
    const r = await api('/api/training/redis-streams');
    const streams = await r.json();
    const sel = $('stream-picker');
    sel.innerHTML = '<option value="">' + tr('training.streamPlaceholder') + '</option>';
    streams.forEach((s) => {
      const u = (s.rtsp_url || '').trim();
      if (!u) return;
      const o = document.createElement('option');
      o.value = u;
      o.textContent = (s.name || s.id || tr('training.streamFallback')) + ' — ' + u.substring(0, 48);
      sel.appendChild(o);
    });
  }

  $('stream-picker').addEventListener('change', function () {
    if (this.value) $('rtsp-url').value = this.value;
    $('preview-img').classList.remove('show');
    $('btn-capture').disabled = !state.projectId || !$('rtsp-url').value.trim();
  });

  $('rtsp-url').addEventListener('input', function () {
    $('btn-capture').disabled = !state.projectId || !this.value.trim().toLowerCase().startsWith('rtsp');
    $('preview-img').classList.remove('show');
  });

  function setProjectActionButtons(enabled) {
    var ids = [
      'btn-capture',
      'btn-prelabel',
      'btn-approve-all',
      'btn-refresh-health',
      'btn-threshold-suggest',
    ];
    ids.forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = !enabled;
    });
  }

  async function refreshDatasetHealth() {
    if (!state.projectId) return;
    var r = await api('/api/training/projects/' + state.projectId + '/dataset-health');
    var h = await r.json();
    var box = $('dataset-health');
    if (!box) return;
    box.classList.remove('tl-hidden');
    var clsLines = (h.class_names || []).map(function (name, i) {
      return tr('training.boxCount', { name: name, n: (h.boxes_per_class && h.boxes_per_class[i]) || 0 });
    });
    var splitHint = tr('training.splitHint', {
      a: h.train_images_estimated || '?',
      b: h.val_images_estimated || '?',
      c: h.test_images_estimated || '?',
    });
    box.innerHTML =
      '<div class="tl-health-row ' +
      (h.can_train ? 'ok' : 'warn') +
      '">' +
      '<strong>' +
      esc(tr('training.healthTitle')) +
      '</strong> ' +
      esc(tr('training.reviewedN', { n: h.labeled_images })) +
      ' / ' +
      esc(tr('training.draftN', { n: h.draft_images || 0 })) +
      ' / ' +
      esc(tr('training.totalN', { n: h.total_images })) +
      (h.can_train ? ' · ' + esc(tr('training.canTrain')) : ' · ' + esc(tr('training.cannotTrain'))) +
      '</div>' +
      '<div class="tl-muted">' +
      esc(splitHint) +
      '</div>' +
      '<div class="tl-muted">' +
      esc((h.warnings || []).join('；')) +
      '</div>' +
      (h.errors && h.errors.length
        ? '<div class="tl-health-err">' + esc(h.errors.join('；')) + '</div>'
        : '') +
      '<div class="tl-muted">' +
      esc(clsLines.join(' · ')) +
      '</div>';
    return h;
  }

  function getCurrentTemplate() {
    return (
      state.templates.find(function (x) {
        return x.id === state.templateId;
      }) || null
    );
  }

  function canShowDeployButton() {
    var t = getCurrentTemplate();
    if (t && t.deploy_mode === 'specialist') return true;
    if (state.deployMode === 'specialist') return true;
    if (state.templateId === 'custom') return true;
    return false;
  }

  function isSpecialistDeploy() {
    var t = getCurrentTemplate();
    if (t && t.deploy_mode === 'specialist') return true;
    if (state.deployMode === 'specialist') return true;
    if (state.templateId === 'custom') return true;
    return true;
  }

  async function loadSpecialists() {
    var ul = $('specialist-list');
    var r = await api('/api/training/specialists');
    var items = await r.json();
    state.specialists = items || [];
    resolveCalibSpecialist();
    if (!ul) return;
    ul.innerHTML = '';
    if (!items.length) {
      var empty = document.createElement('li');
      empty.className = 'tl-muted';
      empty.textContent = tr('training.noSpecialists');
      ul.appendChild(empty);
      return;
    }
    items.forEach(function (sp) {
      var li = document.createElement('li');
      li.className = 'tl-specialist-item';
      var inner = document.createElement('div');
      inner.className = 'tl-project-inner';
        inner.innerHTML =
        '<strong>' +
        esc(specialistLabel(sp)) +
        '</strong> <span class="tl-muted">(' +
        esc(sp.key) +
        ' · ' +
        esc(sp.kind || '') +
        (sp.origin === 'imported' ? ' · ' + tr('training.originImport') : ' · ' + tr('training.originTrain')) +
        ')</span>';
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'tl-btn tl-btn-ghost tl-btn-sm';
      del.textContent = tr('training.delete');
      del.addEventListener('click', function () {
        deleteSpecialist(sp.key, specialistLabel(sp));
      });
      li.appendChild(inner);
      li.appendChild(del);
      ul.appendChild(li);
    });
  }

  async function deleteSpecialist(key, label) {
    if (
      !window.confirm(
        tr('training.delSpecialistConfirm', { label: label, key: key })
      )
    ) {
      return;
    }
    var r = await api('/api/training/specialists/' + encodeURIComponent(key), { method: 'DELETE' });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok || !j.success) {
      alert(j.message || tr('training.delFail'));
      return;
    }
    await loadSpecialists();
  }

  async function loadTemplates() {
    var r = await api('/api/training/templates');
    state.templates = await r.json();
    fillTemplateSelect();
  }

  function applyTemplateToForm(tid) {
    var t = state.templates.find(function (x) {
      return x.id === tid;
    });
    if (!t) return;
    if ($('np-template-desc')) $('np-template-desc').textContent = templateDesc(t);
    if (t.classes && t.classes.length && $('np-classes')) {
      $('np-classes').value = t.classes.join(', ');
    }
    if (t.defaults) {
      if ($('train-epochs') && t.defaults.epochs) $('train-epochs').value = t.defaults.epochs;
      if ($('train-batch') && t.defaults.batch) $('train-batch').value = t.defaults.batch;
      if ($('train-imgsz') && t.defaults.imgsz) $('train-imgsz').value = t.defaults.imgsz;
      if ($('train-pretrained') && t.defaults.pretrained)
        $('train-pretrained').value = t.defaults.pretrained;
    }
  }

  async function selectProject(id) {
    var prev = state.projectId;
    if (prev && prev !== id) {
      stopValidatePolling();
      state.validateRunning = false;
      setValidateUiRunning(false);
      $('val-cycle-status').textContent = '';
      api('/api/training/projects/' + encodeURIComponent(prev) + '/validate/stop', {
        method: 'POST',
        body: '{}',
      }).catch(function () {});
    }

    state.projectId = id;
    syncDelProjectButton();
    document.querySelectorAll('#project-list li').forEach(function (li) {
      li.classList.toggle('active', li.dataset.id === id);
    });
    const projectSelect = $('project-select');
    if (projectSelect) projectSelect.value = id || '';
    var r = await api('/api/training/projects');
    var list = await r.json();
    var p = list.find(function (x) {
      return x.id === id;
    });
    state.projectClasses = (p && p.classes) || [];
    state.deployTarget = (p && p.deploy_target) || null;
    state.deployMode = (p && p.deploy_mode) || null;
    state.templateId = (p && p.template_id) || null;
    state.calibKey = (p && p.calib_specialist_key) || null;
    $('current-project-label').textContent = projectBadgeText(p);
    fillClassPicker();
    setProjectActionButtons(!!id);
    await loadSamples();
    await refreshDatasetHealth();
    clearCanvas();
    $('btn-capture').disabled = !id || !$('rtsp-url').value.trim().toLowerCase().startsWith('rtsp');
    if (state.jobPoll) clearInterval(state.jobPoll);
    $('train-job-panel').classList.add('tl-hidden');
    await loadWeightOptions();
    state.lastUploadedValidateFile = null;
    $('val-upload-status').textContent = '';
    await refreshValidateLogs();
  }

  function fillClassPicker() {
    const sel = $('class-picker');
    sel.innerHTML = '';
    state.projectClasses.forEach((name, i) => {
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = i + ': ' + name;
      sel.appendChild(o);
    });
    fillValClassFilter();
  }

  function fillValClassFilter() {
    const sel = $('val-class-filter');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '';
    const all = document.createElement('option');
    all.value = '';
    all.textContent = tr('training.classAll');
    sel.appendChild(all);
    state.projectClasses.forEach((name, i) => {
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = i + ': ' + name;
      sel.appendChild(o);
    });
    if (prev && Array.from(sel.options).some((o) => o.value === prev)) {
      sel.value = prev;
    }
  }

  function readValClassFilter() {
    const sel = $('val-class-filter');
    if (!sel || sel.value === '') return null;
    const n = parseInt(sel.value, 10);
    return Number.isFinite(n) ? n : null;
  }

  async function deleteSampleEntry(filename, ev) {
    if (ev) ev.stopPropagation();
    if (
      !window.confirm(tr('training.delSampleConfirm', { filename: filename }))
    ) {
      return;
    }
    const r = await api('/api/training/projects/' + state.projectId + '/samples', {
      method: 'DELETE',
      body: JSON.stringify({ filename: filename }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.success) {
      alert(j.message || tr('training.delFail'));
      return;
    }
    if (state.imageName === filename) {
      clearCanvas();
    }
    await loadSamples();
  }

  async function loadSamples() {
    if (!state.projectId) return;
    const r = await api('/api/training/projects/' + state.projectId + '/samples');
    const rows = await r.json();
    state.sampleFiles = rows.map((row) => row.filename);
    const ul = $('sample-list');
    ul.innerHTML = '';
    rows.forEach((row) => {
      const li = document.createElement('li');
      li.dataset.file = row.filename;
      if (row.filename === state.imageName) li.classList.add('on');

      const status = row.status || (row.labeled ? 'reviewed' : 'unlabeled');
      const dotClass =
        status === 'reviewed'
          ? 'ok'
          : status === 'draft'
            ? 'draft'
            : status === 'negative'
              ? 'neg'
              : '';
      const statusText = sampleStatusText(status);

      const body = document.createElement('div');
      body.className = 'tl-sample-body';
      body.innerHTML =
        '<span class="tl-dot ' +
        dotClass +
        '" title="' +
        statusText +
        '"></span><span class="tl-fname" title="' +
        esc(row.filename) +
        '">' +
        esc(row.filename) +
        '</span>';
      body.addEventListener('click', () => openSample(row.filename));

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tl-sample-del';
      btn.setAttribute('aria-label', tr('training.delSampleAria'));
      btn.setAttribute('title', tr('training.delSampleAria'));
      btn.textContent = '\u2715';
      btn.addEventListener('click', (ev) => deleteSampleEntry(row.filename, ev));

      li.appendChild(body);
      li.appendChild(btn);
      ul.appendChild(li);
    });
    updateSampleNav();
  }

  function currentSampleIndex() {
    if (!state.imageName || !state.sampleFiles.length) return -1;
    return state.sampleFiles.indexOf(state.imageName);
  }

  function updateSampleNav() {
    const idx = currentSampleIndex();
    const total = state.sampleFiles.length;
    const prev = $('btn-prev-sample');
    const next = $('btn-next-sample');
    const pos = $('sample-nav-pos');
    if (prev) prev.disabled = idx <= 0;
    if (next) next.disabled = idx < 0 || idx >= total - 1;
    if (pos) {
      pos.textContent = idx >= 0 && total ? idx + 1 + ' / ' + total : '';
    }
  }

  async function saveLabels(opts) {
    const quiet = opts && opts.quiet;
    if (!state.projectId || !state.imageName || !state.naturalW) {
      if (!quiet) $('label-status').textContent = tr('training.pickImageFirst');
      return false;
    }
    const nw = state.naturalW;
    const nh = state.naturalH;
    const boxes = state.boxes.map((b) => boxToYolo(b, nw, nh));
    const r = await api('/api/training/projects/' + state.projectId + '/labels', {
      method: 'POST',
      body: JSON.stringify({ image: state.imageName, boxes }),
    });
    const j = await r.json();
    if (j.success) {
      if (!quiet) $('label-status').textContent = tr('training.savedBoxes', { n: j.lines });
      await loadSamples();
      return true;
    }
    $('label-status').textContent = j.message || tr('training.saveFail');
    return false;
  }

  async function navigateSample(delta) {
    const idx = currentSampleIndex();
    if (idx < 0) {
      $('label-status').textContent = tr('training.pickSampleFirst');
      return;
    }
    const nextIdx = idx + delta;
    if (nextIdx < 0 || nextIdx >= state.sampleFiles.length) return;
    const ok = await saveLabels({ quiet: true });
    if (!ok) return;
    await openSample(state.sampleFiles[nextIdx]);
    $('label-status').textContent = tr(delta < 0 ? 'training.savedPrev' : 'training.savedNext', {
      pos: nextIdx + 1 + ' / ' + state.sampleFiles.length,
    });
  }

  function cloneBoxes(boxes) {
    return (boxes || []).map((b) => ({
      class_index: b.class_index,
      x1: b.x1,
      y1: b.y1,
      x2: b.x2,
      y2: b.y2,
    }));
  }

  function normBox(b) {
    return {
      class_index: b.class_index,
      x1: Math.min(b.x1, b.x2),
      y1: Math.min(b.y1, b.y2),
      x2: Math.max(b.x1, b.x2),
      y2: Math.max(b.y1, b.y2),
    };
  }

  function boxToYolo(b, nw, nh) {
    const n = normBox(b);
    const w = n.x2 - n.x1;
    const h = n.y2 - n.y1;
    return {
      class_index: n.class_index,
      cx: (n.x1 + n.x2) / 2 / nw,
      cy: (n.y1 + n.y2) / 2 / nh,
      w: w / nw,
      h: h / nh,
    };
  }

  function resetHistory(boxes) {
    state.history = [cloneBoxes(boxes)];
    state.historyIndex = 0;
    updateAnnoButtons();
  }

  function pushHistory() {
    const snap = cloneBoxes(state.boxes);
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(snap);
    if (state.history.length > 80) {
      state.history.shift();
    } else {
      state.historyIndex += 1;
    }
    state.historyIndex = state.history.length - 1;
    updateAnnoButtons();
  }

  function applyHistoryIndex(idx) {
    if (idx < 0 || idx >= state.history.length) return;
    state.historyIndex = idx;
    state.boxes = cloneBoxes(state.history[idx]);
    if (state.selectedBox >= state.boxes.length) state.selectedBox = -1;
    updateAnnoButtons();
    redraw();
  }

  function undoBoxes() {
    if (state.historyIndex <= 0) return;
    applyHistoryIndex(state.historyIndex - 1);
    $('label-status').textContent = tr('training.undone');
  }

  function redoBoxes() {
    if (state.historyIndex >= state.history.length - 1) return;
    applyHistoryIndex(state.historyIndex + 1);
    $('label-status').textContent = tr('training.redone');
  }

  function updateAnnoButtons() {
    const u = $('btn-undo-box');
    const r = $('btn-redo-box');
    const d = $('btn-delete-box');
    if (u) u.disabled = state.historyIndex <= 0;
    if (r) r.disabled = state.historyIndex >= state.history.length - 1;
    if (d) d.disabled = state.selectedBox < 0;
  }

  function clearCanvas() {
    state.imageName = null;
    state.boxes = [];
    state.naturalW = 0;
    state.naturalH = 0;
    state.selectedBox = -1;
    state.drag = null;
    state.interaction = null;
    state.annoImg = null;
    resetHistory([]);
    const c = $('anno-canvas');
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    $('annotate-filename').textContent = '';
    $('label-status').textContent = '';
    updateSampleNav();
  }

  async function openSample(filename) {
    if (!state.projectId) return;
    state.imageName = filename;
    state.selectedBox = -1;
    state.drag = null;
    state.interaction = null;
    document.querySelectorAll('#sample-list li').forEach((li) => {
      li.classList.toggle('on', li.dataset.file === filename);
    });
    $('annotate-filename').textContent = filename;
    updateSampleNav();

    const url = '/api/training/projects/' + state.projectId + '/image/' + encodeURIComponent(filename);
    const img = new Image();
    img.onload = async function () {
      state.annoImg = img;
      state.naturalW = img.naturalWidth;
      state.naturalH = img.naturalHeight;
      const c = $('anno-canvas');
      c.width = state.naturalW;
      c.height = state.naturalH;
      state.boxes = [];
      const lr = await api(
        '/api/training/projects/' + state.projectId + '/labels/' + encodeURIComponent(filename.replace(/\.[^.]+$/, '') + '.txt')
      );
      const txt = await lr.text();
      parseYoloLines(txt);
      resetHistory(state.boxes);
      redraw();
    };
    img.src = url;
  }

  function parseYoloLines(txt) {
    const lines = (txt || '').trim().split(/\r?\n/).filter(Boolean);
    const nw = state.naturalW;
    const nh = state.naturalH;
    lines.forEach((line) => {
      const p = line.trim().split(/\s+/);
      if (p.length < 5) return;
      const ci = parseInt(p[0], 10);
      const cx = parseFloat(p[1]) * nw;
      const cy = parseFloat(p[2]) * nh;
      const w = parseFloat(p[3]) * nw;
      const h = parseFloat(p[4]) * nh;
      state.boxes.push({
        class_index: ci,
        x1: cx - w / 2,
        y1: cy - h / 2,
        x2: cx + w / 2,
        y2: cy + h / 2,
      });
    });
  }

  function handlesFor(b) {
    const n = normBox(b);
    const mx = (n.x1 + n.x2) / 2;
    const my = (n.y1 + n.y2) / 2;
    return [
      { id: 'nw', x: n.x1, y: n.y1, cursor: 'nwse-resize' },
      { id: 'n', x: mx, y: n.y1, cursor: 'ns-resize' },
      { id: 'ne', x: n.x2, y: n.y1, cursor: 'nesw-resize' },
      { id: 'e', x: n.x2, y: my, cursor: 'ew-resize' },
      { id: 'se', x: n.x2, y: n.y2, cursor: 'nwse-resize' },
      { id: 's', x: mx, y: n.y2, cursor: 'ns-resize' },
      { id: 'sw', x: n.x1, y: n.y2, cursor: 'nesw-resize' },
      { id: 'w', x: n.x1, y: my, cursor: 'ew-resize' },
    ];
  }

  function hitHandle(b, x, y) {
    const hs = handlesFor(b);
    const r = HANDLE;
    for (let i = 0; i < hs.length; i++) {
      const h = hs[i];
      if (Math.abs(x - h.x) <= r && Math.abs(y - h.y) <= r) return h;
    }
    return null;
  }

  function hitBox(x, y) {
    for (let i = state.boxes.length - 1; i >= 0; i--) {
      const n = normBox(state.boxes[i]);
      if (x >= n.x1 && x <= n.x2 && y >= n.y1 && y <= n.y2) return i;
    }
    return -1;
  }

  function drawBoxes(ctx, draft) {
    state.boxes.forEach((b, idx) => {
      const n = normBox(b);
      const selected = idx === state.selectedBox;
      ctx.strokeStyle = selected ? '#fbbf24' : '#22d3ee';
      ctx.lineWidth = selected ? 2.5 : 2;
      ctx.strokeRect(n.x1, n.y1, n.x2 - n.x1, n.y2 - n.y1);
      const name = state.projectClasses[b.class_index] || String(b.class_index);
      const labelW = Math.min(220, name.length * 8 + 10);
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fillRect(n.x1, Math.max(0, n.y1 - 18), labelW, 18);
      ctx.fillStyle = '#fff';
      ctx.font = '14px sans-serif';
      ctx.fillText(name, n.x1 + 4, Math.max(14, n.y1 - 4));
      if (selected) {
        handlesFor(b).forEach((h) => {
          ctx.fillStyle = '#fbbf24';
          ctx.fillRect(h.x - HANDLE / 2, h.y - HANDLE / 2, HANDLE, HANDLE);
          ctx.strokeStyle = '#0f172a';
          ctx.lineWidth = 1;
          ctx.strokeRect(h.x - HANDLE / 2, h.y - HANDLE / 2, HANDLE, HANDLE);
        });
      }
    });
    if (draft) {
      ctx.strokeStyle = '#fbbf24';
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.strokeRect(
        Math.min(draft.x1, draft.x2),
        Math.min(draft.y1, draft.y2),
        Math.abs(draft.x2 - draft.x1),
        Math.abs(draft.y2 - draft.y1)
      );
      ctx.setLineDash([]);
    }
  }

  function redraw(draft) {
    const c = $('anno-canvas');
    if (!state.naturalW || !state.annoImg) return;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(state.annoImg, 0, 0);
    drawBoxes(ctx, draft || null);
    updateAnnoButtons();
  }

  function canvasCoords(ev) {
    const c = $('anno-canvas');
    const rect = c.getBoundingClientRect();
    const scaleX = c.width / rect.width;
    const scaleY = c.height / rect.height;
    return {
      x: (ev.clientX - rect.left) * scaleX,
      y: (ev.clientY - rect.top) * scaleY,
    };
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function applyResize(orig, handleId, x, y) {
    const n = normBox(orig);
    let x1 = n.x1;
    let y1 = n.y1;
    let x2 = n.x2;
    let y2 = n.y2;
    const xx = clamp(x, 0, state.naturalW);
    const yy = clamp(y, 0, state.naturalH);
    if (handleId.indexOf('n') >= 0) y1 = yy;
    if (handleId.indexOf('s') >= 0) y2 = yy;
    if (handleId.indexOf('w') >= 0) x1 = xx;
    if (handleId.indexOf('e') >= 0) x2 = xx;
    if (Math.abs(x2 - x1) < MIN_BOX) {
      if (handleId.indexOf('w') >= 0) x1 = x2 - MIN_BOX;
      else x2 = x1 + MIN_BOX;
    }
    if (Math.abs(y2 - y1) < MIN_BOX) {
      if (handleId.indexOf('n') >= 0) y1 = y2 - MIN_BOX;
      else y2 = y1 + MIN_BOX;
    }
    return {
      class_index: orig.class_index,
      x1: clamp(Math.min(x1, x2), 0, state.naturalW),
      y1: clamp(Math.min(y1, y2), 0, state.naturalH),
      x2: clamp(Math.max(x1, x2), 0, state.naturalW),
      y2: clamp(Math.max(y1, y2), 0, state.naturalH),
    };
  }

  function setCanvasCursor(cursor) {
    const c = $('anno-canvas');
    if (c) c.style.cursor = cursor || 'crosshair';
  }

  function deleteSelectedBox() {
    if (state.selectedBox < 0 || state.selectedBox >= state.boxes.length) return;
    state.boxes.splice(state.selectedBox, 1);
    state.selectedBox = -1;
    pushHistory();
    redraw();
    $('label-status').textContent = tr('training.deletedBox');
  }

  const canvasEl = $('anno-canvas');

  canvasEl.addEventListener('mousedown', function (ev) {
    if (!state.imageName || !state.naturalW) return;
    if (ev.button !== 0) return;
    const { x, y } = canvasCoords(ev);

    if (state.selectedBox >= 0) {
      const handle = hitHandle(state.boxes[state.selectedBox], x, y);
      if (handle) {
        state.interaction = {
          mode: 'resize',
          index: state.selectedBox,
          handle: handle.id,
          orig: cloneBoxes([state.boxes[state.selectedBox]])[0],
          dirty: false,
        };
        return;
      }
    }

    const hit = hitBox(x, y);
    if (hit >= 0) {
      state.selectedBox = hit;
      const b = state.boxes[hit];
      state.interaction = {
        mode: 'move',
        index: hit,
        startX: x,
        startY: y,
        orig: cloneBoxes([b])[0],
        dirty: false,
      };
      redraw();
      return;
    }

    state.selectedBox = -1;
    const ci = parseInt($('class-picker').value, 10) || 0;
    state.interaction = {
      mode: 'draw',
      x1: x,
      y1: y,
      x2: x,
      y2: y,
      class_index: ci,
    };
    redraw();
  });

  canvasEl.addEventListener('mousemove', function (ev) {
    if (!state.imageName || !state.naturalW) return;
    const { x, y } = canvasCoords(ev);
    const inter = state.interaction;

    if (!inter) {
      if (state.selectedBox >= 0) {
        const handle = hitHandle(state.boxes[state.selectedBox], x, y);
        if (handle) {
          setCanvasCursor(handle.cursor);
          return;
        }
      }
      setCanvasCursor(hitBox(x, y) >= 0 ? 'move' : 'crosshair');
      return;
    }

    if (inter.mode === 'draw') {
      inter.x2 = x;
      inter.y2 = y;
      redraw(inter);
      return;
    }

    if (inter.mode === 'move') {
      const dx = x - inter.startX;
      const dy = y - inter.startY;
      const o = inter.orig;
      const w = o.x2 - o.x1;
      const h = o.y2 - o.y1;
      let nx1 = o.x1 + dx;
      let ny1 = o.y1 + dy;
      nx1 = clamp(nx1, 0, state.naturalW - w);
      ny1 = clamp(ny1, 0, state.naturalH - h);
      state.boxes[inter.index] = {
        class_index: o.class_index,
        x1: nx1,
        y1: ny1,
        x2: nx1 + w,
        y2: ny1 + h,
      };
      inter.dirty = Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5;
      redraw();
      return;
    }

    if (inter.mode === 'resize') {
      state.boxes[inter.index] = applyResize(inter.orig, inter.handle, x, y);
      inter.dirty = true;
      redraw();
    }
  });

  function finishInteraction() {
    const inter = state.interaction;
    if (!inter) return;
    state.interaction = null;

    if (inter.mode === 'draw') {
      const w = Math.abs(inter.x2 - inter.x1);
      const h = Math.abs(inter.y2 - inter.y1);
      if (w < MIN_BOX || h < MIN_BOX) {
        redraw();
        return;
      }
      state.boxes.push(
        normBox({
          class_index: inter.class_index,
          x1: inter.x1,
          y1: inter.y1,
          x2: inter.x2,
          y2: inter.y2,
        })
      );
      state.selectedBox = state.boxes.length - 1;
      pushHistory();
      redraw();
      return;
    }

    if ((inter.mode === 'move' || inter.mode === 'resize') && inter.dirty) {
      state.boxes[inter.index] = normBox(state.boxes[inter.index]);
      pushHistory();
    }
    redraw();
  }

  canvasEl.addEventListener('mouseup', finishInteraction);
  canvasEl.addEventListener('mouseleave', function () {
    if (state.interaction) finishInteraction();
  });

  canvasEl.addEventListener('dblclick', function (ev) {
    if (!state.imageName || !state.naturalW) return;
    const { x, y } = canvasCoords(ev);
    const hit = hitBox(x, y);
    if (hit < 0) return;
    state.selectedBox = hit;
    deleteSelectedBox();
  });

  function isTypingTarget(el) {
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
  }

  $('btn-save-labels').addEventListener('click', function () {
    saveLabels();
  });
  $('btn-undo-box').addEventListener('click', undoBoxes);
  $('btn-redo-box').addEventListener('click', redoBoxes);
  $('btn-delete-box').addEventListener('click', deleteSelectedBox);
  $('btn-prev-sample').addEventListener('click', function () {
    navigateSample(-1);
  });
  $('btn-next-sample').addEventListener('click', function () {
    navigateSample(1);
  });

  document.addEventListener('keydown', function (e) {
    if (isTypingTarget(e.target)) return;

    const mod = e.ctrlKey || e.metaKey;
    if (mod && (e.key === 'z' || e.key === 'Z') && !e.shiftKey) {
      e.preventDefault();
      undoBoxes();
      return;
    }
    if (mod && (e.key === 'y' || e.key === 'Y' || (e.shiftKey && (e.key === 'z' || e.key === 'Z')))) {
      e.preventDefault();
      redoBoxes();
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedBox >= 0) {
      e.preventDefault();
      deleteSelectedBox();
      return;
    }
    if (e.key === 'Escape') {
      state.selectedBox = -1;
      state.interaction = null;
      redraw();
      return;
    }
    if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
      e.preventDefault();
      navigateSample(-1);
      return;
    }
    if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
      e.preventDefault();
      navigateSample(1);
      return;
    }
    if (e.key === 's' || e.key === 'S') {
      e.preventDefault();
      saveLabels();
    }
  });

  $('btn-preview').addEventListener('click', async function () {
    const url = $('rtsp-url').value.trim();
    if (!url.toLowerCase().startsWith('rtsp')) {
      alert(tr('training.needRtsp'));
      return;
    }
    const img = $('preview-img');
    img.classList.add('show');
    img.src =
      '/api/training/rtsp-preview?url=' +
      encodeURIComponent(url) +
      '&_t=' +
      Date.now();
  });

  $('btn-capture').addEventListener('click', async function () {
    if (!state.projectId) return;
    const url = $('rtsp-url').value.trim();
    const r = await api('/api/training/projects/' + state.projectId + '/capture', {
      method: 'POST',
      body: JSON.stringify({ rtsp_url: url }),
    });
    const j = await r.json();
    if (j.success) {
      await loadSamples();
      await openSample(j.filename);
    } else {
      alert(j.message || tr('training.captureFail'));
    }
  });

  $('btn-train').addEventListener('click', async function () {
    if (!state.projectId) {
      alert(tr('training.pickProject'));
      return;
    }
    var health = await refreshDatasetHealth();
    if (health && !health.can_train) {
      alert(tr('training.trainGateBlocked', { errors: (health.errors || []).join('\n') }));
      $('train-status').textContent = tr('training.trainGateShort');
      return;
    }
    const body = {
      epochs: parseInt($('train-epochs').value, 10) || 80,
      batch_size: parseInt($('train-batch').value, 10) || 8,
      img_size: parseInt($('train-imgsz').value, 10) || 640,
      device: $('train-device').value.trim() || 'cpu',
      pretrained_model: $('train-pretrained').value.trim() || 'yolo26s.pt',
      force: false,
    };
    const r = await api('/api/training/projects/' + state.projectId + '/train', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok || !j.success) {
      $('train-status').textContent = j.message || tr('training.jobStartFail');
      if (j.health) refreshDatasetHealth();
      return;
    }
    $('train-job-panel').classList.remove('tl-hidden');
    $('job-id').textContent = j.job_id;
    state.lastJobId = j.job_id;
    $('train-status').textContent = tr('training.jobStarted');
    $('job-log-link').href = '/api/training/jobs/' + j.job_id + '/log';
    $('job-weights-link').classList.add('tl-hidden');
    $('btn-deploy').classList.add('tl-hidden');
    $('job-eval-metrics').classList.add('tl-hidden');
    $('deploy-status').textContent = '';
    if (state.jobPoll) clearInterval(state.jobPoll);
    state.jobPoll = setInterval(async () => pollJob(j.job_id), 2000);
    pollJob(j.job_id);
  });

  async function pollJob(jobId) {
    const r = await api('/api/training/jobs/' + jobId);
    if (!r.ok) return;
    const j = await r.json();
    $('job-status').textContent =
      jobStatusText(j.status);
    if (j.status === 'completed') {
      $('job-weights-link').href = '/api/training/jobs/' + jobId + '/weights';
      $('job-weights-link').classList.remove('tl-hidden');
      var em = $('job-eval-metrics');
      if (em) {
        em.classList.remove('tl-hidden');
        var valLine = '';
        if (j.evaluation && j.evaluation.ok) {
          valLine =
            'Val mAP@0.5: <b>' +
            Number(j.map50 != null ? j.map50 : j.evaluation.map50).toFixed(4) +
            '</b> · P: ' +
            Number(j.precision != null ? j.precision : j.evaluation.precision).toFixed(4) +
            ' · R: ' +
            Number(j.recall != null ? j.recall : j.evaluation.recall).toFixed(4);
        } else if (j.evaluation) {
          valLine = esc(tr('training.valEvalFail', { err: j.evaluation.error || '' }));
        }
        var testLine = '';
        if (j.test_evaluation && j.test_evaluation.ok) {
          testLine =
            '<br>Test mAP@0.5: <b>' +
            Number(j.test_map50 != null ? j.test_map50 : j.test_evaluation.map50).toFixed(4) +
            '</b> · P: ' +
            Number(
              j.test_precision != null ? j.test_precision : j.test_evaluation.precision
            ).toFixed(4) +
            ' · R: ' +
            Number(j.test_recall != null ? j.test_recall : j.test_evaluation.recall).toFixed(4);
        } else if (j.test_evaluation) {
          testLine = '<br>' + esc(tr('training.testEvalFail', { err: j.test_evaluation.error || '' }));
        }
        var gateLine = '';
        if (j.deploy_ready && canShowDeployButton()) {
          gateLine = '<br><span class="tl-gate-ok">' + esc(tr('training.gateOkDeploy')) + '</span>';
          $('btn-deploy').classList.remove('tl-hidden');
        } else if (j.deploy_ready) {
          gateLine = '<br><span class="tl-gate-ok">' + esc(tr('training.gateOk')) + '</span>';
          $('btn-deploy').classList.add('tl-hidden');
        } else {
          gateLine =
            '<br><span class="tl-gate-bad">' + esc(tr('training.gateBad')) + '</span> ' +
            esc((j.deploy_gate_errors || []).join('；'));
          $('btn-deploy').classList.add('tl-hidden');
        }
        em.innerHTML = valLine + testLine + gateLine;
      }
      clearInterval(state.jobPoll);
      state.jobPoll = null;
      loadWeightOptions().catch(function () {});
    }
    if (j.status === 'failed') {
      $('job-status').textContent += j.error ? ' — ' + j.error : '';
      clearInterval(state.jobPoll);
      state.jobPoll = null;
    }
  }

  $('btn-deploy').addEventListener('click', async function () {
    if (!state.projectId || !state.lastJobId) return;
    if (!canShowDeployButton()) {
      alert(tr('training.cannotDeploy'));
      return;
    }
    var body = {
      job_id: state.lastJobId,
      backup: true,
      force: false,
    };
    var specialist = isSpecialistDeploy();
    if (specialist) {
      var t = getCurrentTemplate();
      var sd = (t && t.specialist_defaults) || {};
      var keyDefault = state.calibKey || sd.key_suggestion || 'custom_model';
      var key = window.prompt(
        state.calibKey
          ? tr('training.promptKeyCalib', { key: state.calibKey })
          : tr('training.promptKey'),
        keyDefault
      );
      if (!key || !key.trim()) return;
      var nameZh = window.prompt(tr('training.promptNameZh'), sd.name_zh || key.trim());
      if (nameZh === null) return;
      var kind = window.prompt(tr('training.promptKind'), sd.kind || 'person_event');
      if (!kind || !kind.trim()) return;
      body.deploy_mode = 'specialist';
      body.key = key.trim();
      body.name_zh = (nameZh || key).trim();
      body.kind = kind.trim();
      if (sd.positive_class_ids) body.positive_class_ids = sd.positive_class_ids;
      if (sd.subject_class_ids) body.subject_class_ids = sd.subject_class_ids;
      if (sd.comply_class_ids) body.comply_class_ids = sd.comply_class_ids;
      if (sd.class_ids) body.class_ids = sd.class_ids;
      if (sd.needs_persons !== undefined) body.needs_persons = sd.needs_persons;
      var overwrite = state.calibKey && body.key === state.calibKey;
      if (
        !window.confirm(
          (overwrite
            ? tr('training.confirmOverwrite', { key: body.key })
            : tr('training.confirmDeploy', { key: body.key }))
        )
      ) {
        return;
      }
    } else {
      alert(tr('training.builtinGone'));
      return;
    }
    var r = await api('/api/training/projects/' + state.projectId + '/deploy', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    var j = await r.json();
    $('deploy-status').textContent = j.message || tr(j.success ? 'training.deployOk' : 'training.deployFail');
    if (!j.success) alert(j.message || tr('training.deployFail'));
    else if (specialist) loadSpecialists().catch(function () {});
  });

  $('btn-refresh-health').addEventListener('click', function () {
    refreshDatasetHealth().catch(function () {});
  });

  $('btn-prelabel').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert(tr('training.pickValWeights'));
      return;
    }
    if (
      !window.confirm(
        tr('training.prelabelConfirm')
      )
    )
      return;
    var r = await api('/api/training/projects/' + state.projectId + '/prelabel', {
      method: 'POST',
      body: JSON.stringify({ weights_path: w, conf: 0.25, only_unlabeled: true }),
    });
    var j = await r.json();
    alert(j.message || tr(j.success ? 'training.done' : 'training.fail'));
    if (j.success) {
      await loadSamples();
      await refreshDatasetHealth();
    }
  });

  if ($('btn-approve-all')) {
    $('btn-approve-all').addEventListener('click', async function () {
      if (!state.projectId) return;
      if (!window.confirm(tr('training.approveConfirm'))) return;
      var r = await api('/api/training/projects/' + state.projectId + '/labels/approve', {
        method: 'POST',
        body: JSON.stringify({ all: true }),
      });
      var j = await r.json();
      alert(j.message || tr(j.success ? 'training.done' : 'training.fail'));
      if (j.success) {
        await loadSamples();
        await refreshDatasetHealth();
      }
    });
  }

  // ---- 回流校准：选流+检测类型 → 加载告警截图 → 人工研判 → 导入 → 重训 → 覆盖部署 ----
  function getCalibSpecialist() {
    return state.calibSpecialist || null;
  }

  function calibVerdictOf(it) {
    return state.snapVerdicts[it.path] || '';
  }

  function calibCounts() {
    var tp = 0;
    var fp = 0;
    state.snapItems.forEach(function (it) {
      var v = calibVerdictOf(it);
      if (v === 'tp') tp += 1;
      else if (v === 'fp') fp += 1;
    });
    return { tp: tp, fp: fp, unjudged: state.snapItems.length - tp - fp };
  }

  function updateCalibSummary() {
    var c = calibCounts();
    var el = $('calib-summary');
    if (el) {
      el.textContent = state.snapItems.length
        ? tr('training.calibSummary', { tp: c.tp, fp: c.fp, un: c.unjudged })
        : '';
    }
    var btn = $('btn-calib-import');
    if (btn) btn.disabled = !getCalibSpecialist() || !(c.tp + c.fp);
  }

  function setSnapVerdict(path, verdict) {
    if (state.snapVerdicts[path] === verdict) {
      delete state.snapVerdicts[path];
    } else {
      state.snapVerdicts[path] = verdict;
    }
    renderSnapGrid();
  }

  function renderSnapGrid() {
    var grid = $('calib-snap-grid');
    if (!grid) return;
    grid.innerHTML = '';
    state.snapItems.forEach(function (it) {
      var card = document.createElement('div');
      card.className = 'tl-snap-card';

      var img = document.createElement('img');
      img.className = 'tl-snap-thumb';
      img.loading = 'lazy';
      img.alt = '';
      img.src = '/api/training/snapshots/image?path=' + encodeURIComponent(it.path);
      img.title = tr('training.zoomPreview');
      img.addEventListener('click', function () {
        openImgPreview(img.src);
      });

      var name = document.createElement('div');
      name.className = 'tl-snap-name';
      name.title = it.relative || it.filename;
      name.textContent = it.relative || it.filename;

      var ops = document.createElement('div');
      ops.className = 'tl-snap-ops';
      var v = calibVerdictOf(it);
      var btnTp = document.createElement('button');
      btnTp.type = 'button';
      btnTp.className = 'tl-verdict tl-verdict-tp' + (v === 'tp' ? ' on' : '');
      btnTp.textContent = tr('training.verdictTp');
      btnTp.addEventListener('click', function () { setSnapVerdict(it.path, 'tp'); });
      var btnFp = document.createElement('button');
      btnFp.type = 'button';
      btnFp.className = 'tl-verdict tl-verdict-fp' + (v === 'fp' ? ' on' : '');
      btnFp.textContent = tr('training.verdictFp');
      btnFp.addEventListener('click', function () { setSnapVerdict(it.path, 'fp'); });
      ops.appendChild(btnTp);
      ops.appendChild(btnFp);

      card.appendChild(img);
      card.appendChild(name);
      card.appendChild(ops);
      grid.appendChild(card);
    });
    updateCalibSummary();
  }

  function openImgPreview(src) {
    var m = $('modal-img-preview');
    var img = $('img-preview-full');
    if (!m || !img) return;
    img.src = src;
    m.classList.remove('tl-hidden');
  }

  if ($('modal-img-preview')) {
    $('modal-img-preview').addEventListener('click', function () {
      this.classList.add('tl-hidden');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !$('modal-img-preview').classList.contains('tl-hidden')) {
        $('modal-img-preview').classList.add('tl-hidden');
        e.stopPropagation();
      }
    });
  }

  // 仅「已部署专模」对应的告警类型支持回流校准（内置行为/COCO/识别实例标签不可训练）
  function findSpecialistForType(type) {
    var t = (type || '').trim();
    if (!t) return null;
    var tl = t.toLowerCase();
    return (
      (state.specialists || []).find(function (s) {
        return (
          (s.key || '').toLowerCase() === tl ||
          (s.name_zh || '').trim() === t ||
          (s.name_en || '').toLowerCase() === tl
        );
      }) || null
    );
  }

  async function loadCalibAlertTypes() {
    var sel = $('calib-det-type');
    if (!sel) return;
    var prev = sel.value;
    sel.innerHTML = '<option value="">' + tr('training.calibTypeOnly') + '</option>';
    try {
      var r = await api('/api/detections?limit=500');
      var j = await r.json();
      var rows = (j && j.data) || [];
      var counts = {};
      rows.forEach(function (d) {
        (d.detection_types || []).forEach(function (t) {
          counts[t] = (counts[t] || 0) + 1;
        });
      });
      var trainable = Object.keys(counts)
        .filter(function (t) { return !!findSpecialistForType(t); })
        .sort(function (a, b) { return counts[b] - counts[a]; });
      trainable.forEach(function (t) {
        var o = document.createElement('option');
        o.value = t;
        o.textContent = tr('training.typeCount', { type: typeLabel(t), n: counts[t] });
        sel.appendChild(o);
      });
      if (!trainable.length) {
        var eo = document.createElement('option');
        eo.value = '';
        eo.textContent = (state.specialists || []).length
          ? tr('training.noAlertsForSp')
          : tr('training.noSpecialists');
        sel.appendChild(eo);
      }
      if (prev && counts[prev] && findSpecialistForType(prev)) sel.value = prev;
    } catch (e) { /* ignore */ }
    resolveCalibSpecialist();
  }

  function resolveCalibSpecialist() {
    var type = ($('calib-det-type') && $('calib-det-type').value) || '';
    state.calibSpecialist = type ? findSpecialistForType(type) : null;
    resolveCalibTargetProject();
  }

  function resolveCalibTargetProject() {
    var sp = getCalibSpecialist();
    var type = ($('calib-det-type') && $('calib-det-type').value) || '';
    var spName = $('calib-sp-name');
    var target = $('calib-target-project');
    var newBtn = $('btn-calib-new-project');
    var loadBtn = $('btn-calib-load');
    state.calibProjectId = null;
    if (loadBtn) loadBtn.disabled = !type;
    if (!type) {
      if (spName) spName.textContent = tr('training.dash');
      if (target) target.textContent = tr('training.dash');
      if (newBtn) newBtn.classList.add('tl-hidden');
      updateCalibSummary();
      return;
    }
    if (!sp) {
      if (spName) spName.textContent = tr('training.notSpecialistType');
      if (target) target.textContent = tr('training.dash');
      if (newBtn) newBtn.classList.add('tl-hidden');
      updateCalibSummary();
      return;
    }
    if (spName) spName.textContent = specialistLabel(sp) + '（' + sp.key + '）';
    var pid = sp.source_project_id || '';
    var proj = pid && (state.projects || []).find(function (p) { return p.id === pid; });
    var projFromKey = !proj && (state.projects || []).find(function (p) {
      return p.calib_specialist_key === sp.key;
    });
    if (proj || projFromKey) {
      var found = proj || projFromKey;
      state.calibProjectId = found.id;
      if (target) {
        target.textContent = found.title + (proj ? tr('training.origProject') : tr('training.existingCalib'));
      }
      if (newBtn) newBtn.classList.add('tl-hidden');
    } else {
      if (target) target.textContent = tr('training.willAutoCreate');
      if (newBtn) newBtn.classList.remove('tl-hidden');
    }
    updateCalibSummary();
    syncCalibTrainBlock();
  }

  async function ensureCalibProject() {
    if (state.calibProjectId) return state.calibProjectId;
    var sp = getCalibSpecialist();
    if (!sp) return null;
    var title = tr('training.calibNameTpl', { name: specialistLabel(sp) || sp.key, ts: Math.floor(Date.now() / 1000) });
    var r = await api('/api/training/projects', {
      method: 'POST',
      body: JSON.stringify({
        title: title,
        classes: sp.classes || [],
        template_id: 'custom',
        calib_specialist_key: sp.key,
      }),
    });
    var j = await r.json();
    if (!j.success) {
      alert(j.message || tr('training.createCalibFail'));
      return null;
    }
    await loadProjects();
    state.calibProjectId = j.project.id;
    var target = $('calib-target-project');
    if (target) target.textContent = j.project.title + tr('training.autoCreated');
    var newBtn = $('btn-calib-new-project');
    if (newBtn) newBtn.classList.add('tl-hidden');
    syncCalibTrainBlock();
    return state.calibProjectId;
  }

  if ($('calib-det-type')) {
    $('calib-det-type').addEventListener('change', function () {
      state.snapItems = [];
      state.snapVerdicts = {};
      renderSnapGrid();
      resolveCalibSpecialist();
    });
  }

  if ($('btn-calib-new-project')) {
    $('btn-calib-new-project').addEventListener('click', async function () {
      var sp = getCalibSpecialist();
      if (!sp) return;
      var defaultName =
        tr('training.calibNameTpl', { name: specialistLabel(sp) || sp.key, ts: Math.floor(Date.now() / 1000) });
      var title = window.prompt(tr('training.promptCalibName'), defaultName);
      if (title === null) return;
      title = title.trim() || defaultName;
      var r = await api('/api/training/projects', {
        method: 'POST',
        body: JSON.stringify({
          title: title,
          classes: sp.classes || [],
          template_id: 'custom',
          calib_specialist_key: sp.key,
        }),
      });
      var j = await r.json();
      if (!j.success) {
        alert(j.message || tr('training.createCalibFail'));
        return;
      }
      await loadProjects();
      state.calibProjectId = j.project.id;
      var target = $('calib-target-project');
      if (target) target.textContent = j.project.title + tr('training.newlyCreated');
      $('btn-calib-new-project').classList.add('tl-hidden');
      updateCalibSummary();
      syncCalibTrainBlock();
    });
  }

  if ($('btn-calib-load')) {
    $('btn-calib-load').addEventListener('click', async function () {
      var detType = ($('calib-det-type') && $('calib-det-type').value) || '';
      if (!detType) return;
      var q = '?limit=200&detection_type=' + encodeURIComponent(detType);
      var status = $('calib-status');
      if (status) status.textContent = tr('training.loading');
      var r = await api('/api/detections' + q);
      var j = await r.json().catch(function () { return {}; });
      var rows = (j && j.data) || [];
      var skippedRemote = 0;
      state.snapItems = [];
      rows.forEach(function (d) {
        var ip = (d.image_path || '').trim();
        if (!ip) {
          skippedRemote += 1;
          return;
        }
        var ts = (d.timestamp || '').replace('T', ' ').substring(0, 19);
        state.snapItems.push({
          path: ip,
          relative: (d.stream_name || '') + ' ' + ts,
          filename: ip.split(/[/\\]/).pop(),
        });
      });
      state.snapVerdicts = {};
      renderSnapGrid();
      if (status) {
        status.textContent = state.snapItems.length
          ? (skippedRemote ? tr('training.skippedRemote', { n: skippedRemote }) : '')
          : tr('training.noLocalSnaps');
      }
    });
  }

  if ($('btn-calib-import')) {
    $('btn-calib-import').addEventListener('click', async function () {
      var sp = getCalibSpecialist();
      if (!sp) return;
      var pid = state.calibProjectId || (await ensureCalibProject());
      if (!pid) return;
      var judged = state.snapItems.filter(function (it) { return calibVerdictOf(it); });
      if (!judged.length) {
        alert(tr('training.judgeFirst'));
        return;
      }
      var verdicts = {};
      judged.forEach(function (it) { verdicts[it.path] = calibVerdictOf(it); });
      var r = await api('/api/training/projects/' + pid + '/import-snapshots', {
        method: 'POST',
        body: JSON.stringify({
          paths: judged.map(function (it) { return it.path; }),
          verdicts: verdicts,
          specialist_key: sp.key,
        }),
      });
      var j = await r.json();
      var msg =
        tr('training.importedN', { count: j.count || 0, neg: j.negative_count || 0, pos: j.positive_count || 0 });
      if (j.autolabel) {
        msg += j.autolabel.success
          ? tr('training.autolabelOk', { n: j.autolabel.written || 0 })
          : tr('training.autolabelFail', { err: j.autolabel.message || '' });
      }
      var status = $('calib-status');
      if (status) status.textContent = msg + tr('training.canCalibTrain');
      state.snapItems = [];
      state.snapVerdicts = {};
      renderSnapGrid();
      await refreshCalibProjectStats();
    });
  }

  // ---- 校准训练与部署（页内闭环，不跳转） ----
  function syncCalibTrainBlock() {
    var block = $('calib-train-block');
    if (!block) return;
    var sp = getCalibSpecialist();
    var show = !!(state.calibProjectId && sp);
    block.classList.toggle('tl-hidden', !show);
    if (show) {
      var pre = $('calib-pretrained');
      if (pre && !pre.value.trim()) {
        pre.value = (sp.weights_exists && sp.model_path) ? sp.model_path : 'yolo26s.pt';
      }
      refreshCalibProjectStats().catch(function () {});
    }
  }

  async function refreshCalibProjectStats() {
    var el = $('calib-project-stats');
    if (!el || !state.calibProjectId) return;
    var r = await api('/api/training/projects/' + state.calibProjectId + '/dataset-health');
    var h = await r.json().catch(function () { return {}; });
    el.textContent =
      tr('training.calibStats', {
        labeled: h.labeled_images || 0,
        neg: h.negative_count || 0,
        draft: h.draft_images || 0,
      });
    var sp = getCalibSpecialist();
    var preHint = $('calib-pretrained-hint');
    if (preHint) {
      preHint.textContent = (sp && sp.weights_exists)
        ? tr('training.finetuneHint')
        : tr('training.noWeightsHint');
    }
    var trainBtn = $('btn-calib-train');
    if (trainBtn) trainBtn.disabled = (h.labeled_images || 0) < 3;
  }

  function pollCalibJob(jobId) {
    return api('/api/training/jobs/' + jobId).then(async function (r) {
      if (!r.ok) return;
      var j = await r.json();
      $('calib-job-status').textContent =
        jobStatusText(j.status);
      if (j.status === 'completed') {
        var em = $('calib-job-metrics');
        if (em && j.test_evaluation) {
          em.classList.remove('tl-hidden');
          em.innerHTML = j.test_evaluation.ok
            ? 'Test mAP@0.5: <b>' + Number(j.test_evaluation.map50).toFixed(4) +
              '</b> · P: ' + Number(j.test_evaluation.precision).toFixed(4) +
              ' · R: ' + Number(j.test_evaluation.recall).toFixed(4) +
              (j.deploy_ready
                ? '<br><span class="tl-gate-ok">' + esc(tr('training.gateOkOverwrite')) + '</span>'
                : '<br><span class="tl-gate-bad">' + esc(tr('training.gateBadColon')) +
                  esc((j.deploy_gate_errors || []).join('；')) + '</span>')
            : esc(tr('training.testEvalFailShort', { err: j.test_evaluation.error || '' }));
        }
        if (j.deploy_ready) $('btn-calib-deploy').classList.remove('tl-hidden');
        else $('btn-calib-deploy').classList.add('tl-hidden');
        clearInterval(state.calibJobPoll);
        state.calibJobPoll = null;
      }
      if (j.status === 'failed') {
        $('calib-job-status').textContent += j.error ? ' — ' + j.error : '';
        clearInterval(state.calibJobPoll);
        state.calibJobPoll = null;
      }
    }).catch(function () {});
  }

  if ($('btn-calib-train')) {
    $('btn-calib-train').addEventListener('click', async function () {
      var pid = state.calibProjectId;
      var sp = getCalibSpecialist();
      if (!pid || !sp) return;
      // 样本规模提示：由用户自行决断是否继续
      try {
        var hr = await api('/api/training/projects/' + pid + '/dataset-health');
        var hh = await hr.json();
        var labeled = hh.labeled_images || 0;
        var negs = hh.negative_count || 0;
        var hints = [];
        if (labeled < 8) {
          hints.push(tr('training.fewPos', { n: labeled }));
        }
        if (negs < 1) {
          hints.push(tr('training.noNeg'));
        }
        if (hints.length && !window.confirm(hints.join('\n') + tr('training.stillCalib'))) {
          return;
        }
      } catch (e) { /* 健康检查失败不阻塞 */ }
      var body = {
        epochs: parseInt($('calib-epochs').value, 10) || 30,
        batch_size: 8,
        img_size: parseInt($('calib-imgsz').value, 10) || 640,
        device: ($('calib-device').value || '').trim() || 'cpu',
        pretrained_model:
          ($('calib-pretrained').value || '').trim() || sp.model_path || 'yolo26s.pt',
      };
      var r = await api('/api/training/projects/' + pid + '/train', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      var j = await r.json();
      if (!r.ok || !j.success) {
        $('calib-train-status').textContent = j.message || tr('training.jobStartFail');
        return;
      }
      $('calib-job-panel').classList.remove('tl-hidden');
      $('calib-job-id').textContent = j.job_id;
      state.calibLastJobId = j.job_id;
      $('calib-train-status').textContent = tr('training.jobStarted');
      $('calib-job-log-link').href = '/api/training/jobs/' + j.job_id + '/log';
      $('btn-calib-deploy').classList.add('tl-hidden');
      $('calib-job-metrics').classList.add('tl-hidden');
      $('calib-deploy-status').textContent = '';
      if (state.calibJobPoll) clearInterval(state.calibJobPoll);
      state.calibJobPoll = setInterval(function () { pollCalibJob(j.job_id); }, 2000);
      pollCalibJob(j.job_id);
    });
  }

  if ($('btn-calib-deploy')) {
    $('btn-calib-deploy').addEventListener('click', async function () {
      var pid = state.calibProjectId;
      var sp = getCalibSpecialist();
      if (!pid || !sp || !state.calibLastJobId) return;
      if (
        !window.confirm(
          tr('training.overwriteCalibConfirm', { key: sp.key })
        )
      ) {
        return;
      }
      var body = {
        job_id: state.calibLastJobId,
        deploy_mode: 'specialist',
        key: sp.key,
        name_zh: sp.name_zh || sp.key,
        name_en: sp.name_en || '',
        kind: sp.kind || 'person_event',
        needs_persons: sp.needs_persons !== false,
        backup: true,
        force: false,
      };
      ['positive_class_ids', 'subject_class_ids', 'comply_class_ids', 'class_ids'].forEach(
        function (f) {
          if (sp[f]) body[f] = sp[f];
        }
      );
      var r = await api('/api/training/projects/' + pid + '/deploy', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      var j = await r.json();
      $('calib-deploy-status').textContent =
        j.message || tr(j.success ? 'training.overwritten' : 'training.deployFail');
      if (j.success) {
        loadSpecialists().catch(function () {});
      }
    });
  }

  $('btn-threshold-suggest').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert(tr('training.pickWeightsFirst'));
      return;
    }
    var applyCfg = $('threshold-apply-config') && $('threshold-apply-config').checked;
    var r = await api('/api/training/projects/' + state.projectId + '/threshold-suggest', {
      method: 'POST',
      body: JSON.stringify({
        weights_path: w,
        apply_config: applyCfg,
      }),
    });
    var j = await r.json();
    var pre = $('threshold-result');
    if (!pre) return;
    if (!r.ok || !j.success) {
      pre.textContent = j.message || tr('training.analyzeFail');
      return;
    }
    pre.textContent = JSON.stringify(j, null, 2);
    if (j.suggested_detector_conf != null) {
      if ($('val-conf')) $('val-conf').value = j.suggested_detector_conf;
    }
  });

  $('val-file').addEventListener('change', async function () {
    if ($('val-upload-status')) $('val-upload-status').textContent = '';
    state.lastUploadedValidateFile = null;
    if (!state.projectId || !this.files || !this.files[0]) return;
    var fd = new FormData();
    fd.append('file', this.files[0]);
    var r = await fetch('/api/training/projects/' + state.projectId + '/validate/upload', {
      method: 'POST',
      credentials: 'same-origin',
      body: fd,
    });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok || !j.success) {
      if ($('val-upload-status')) $('val-upload-status').textContent = j.message || tr('training.uploadFail');
      return;
    }
    state.lastUploadedValidateFile = j.filename;
    if ($('val-upload-status')) {
      $('val-upload-status').textContent =
        tr('training.uploadedAs', { name: j.filename });
    }
  });

  $('btn-val-once').addEventListener('click', async function () {
    if (!state.projectId) {
      alert(tr('training.pickProject'));
      return;
    }
    var w = resolveWeightsPath();
    if (!w) {
      alert(tr('training.pickOrPasteWeights'));
      return;
    }
    var srcEl = document.querySelector('input[name="val-src"]:checked');
    var mode = srcEl ? srcEl.value : 'rtsp_once';
    var body = {
      weights_path: w,
      device: $('val-device').value.trim() || undefined,
      conf: parseFloat($('val-conf').value) || 0.25,
      imgsz: parseInt($('val-imgsz').value, 10) || 640,
      class_filter: readValClassFilter(),
    };
    if (mode === 'upload') {
      body.source = 'upload';
      body.filename = state.lastUploadedValidateFile;
      if (!body.filename) {
        alert(tr('training.uploadImageFirst'));
        return;
      }
    } else {
      body.source = 'rtsp';
      body.rtsp_url = $('rtsp-url').value.trim();
      if (!body.rtsp_url.toLowerCase().startsWith('rtsp')) {
        alert(tr('training.badRtsp'));
        return;
      }
    }
    var r = await api('/api/training/projects/' + state.projectId + '/validate/run-once', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok || !j.success) {
      alert(j.message || tr('training.validateFail'));
      return;
    }
    await refreshValidateLogs();
  });

  $('btn-val-start').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert(tr('training.pickWeightsShort'));
      return;
    }
    var rtsp = $('rtsp-url').value.trim();
    if (!rtsp.toLowerCase().startsWith('rtsp')) {
      alert(tr('training.needRtspAbove'));
      return;
    }
    var r = await api('/api/training/projects/' + state.projectId + '/validate/start', {
      method: 'POST',
      body: JSON.stringify({
        weights_path: w,
        rtsp_url: rtsp,
        interval_sec: parseFloat($('val-interval').value) || 5,
        device: $('val-device').value.trim() || undefined,
        conf: parseFloat($('val-conf').value) || 0.25,
        imgsz: parseInt($('val-imgsz').value, 10) || 640,
        class_filter: readValClassFilter(),
      }),
    });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok || !j.success) {
      alert(j.message || tr('training.startFail'));
      return;
    }
    state.validateRunning = true;
    setValidateUiRunning(true);
    if ($('val-cycle-status')) $('val-cycle-status').textContent = tr('training.cycleRunning');
    startValidatePolling();
    await refreshValidateLogs();
  });

  $('btn-val-stop').addEventListener('click', async function () {
    if (!state.projectId) return;
    stopValidatePolling();
    var r = await api('/api/training/projects/' + state.projectId + '/validate/stop', {
      method: 'POST',
      body: '{}',
    });
    await r.json().catch(function () {});
    state.validateRunning = false;
    setValidateUiRunning(false);
    if ($('val-cycle-status')) $('val-cycle-status').textContent = tr('training.cycleStopped');
    await refreshValidateLogs();
  });

  $('btn-val-logs-refresh').addEventListener('click', function () {
    refreshValidateLogs().catch(function () {});
  });

  // 菜单 + 子页 + 步骤导航
  const STEP_KEYS = ['capture', 'samples', 'annotate', 'train', 'validate', 'threshold'];
  const MENU_KEYS = ['train', 'import'];
  const TRAIN_SUB_KEYS = ['new', 'calib'];
  let currentStep = 'capture';
  let currentMenu = 'train';
  let currentTrainSub = 'new';

  function setStep(step) {
    if (STEP_KEYS.indexOf(step) < 0) step = 'capture';
    currentStep = step;
    document.querySelectorAll('.tl-step').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-step') === step);
    });
    document.querySelectorAll('[data-step-panel]').forEach(function (panel) {
      panel.classList.toggle('tl-hidden', panel.getAttribute('data-step-panel') !== step);
    });
    syncHash();
  }

  function setTrainSub(sub) {
    if (TRAIN_SUB_KEYS.indexOf(sub) < 0) sub = 'new';
    currentTrainSub = sub;
    document.querySelectorAll('.tl-subnav-item').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-train-sub') === sub);
    });
    document.querySelectorAll('[data-train-sub-panel]').forEach(function (panel) {
      panel.classList.toggle('tl-hidden', panel.getAttribute('data-train-sub-panel') !== sub);
    });
    if (sub === 'calib') {
      // 先加载专模列表，再加载告警类型（类型要用专模表过滤）
      loadSpecialists()
        .catch(function () {})
        .then(function () {
          return loadCalibAlertTypes();
        })
        .catch(function () {});
    }
    syncHash();
  }

  function setMenu(menu) {
    if (MENU_KEYS.indexOf(menu) < 0) menu = 'train';
    currentMenu = menu;
    document.querySelectorAll('.tl-menu-item').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-menu') === menu);
    });
    document.querySelectorAll('[data-menu-panel]').forEach(function (panel) {
      panel.classList.toggle('tl-hidden', panel.getAttribute('data-menu-panel') !== menu);
    });
    if (menu === 'import') {
      loadSpecialists().catch(function () {});
    }
    syncHash();
  }

  function syncHash() {
    try {
      let h;
      if (currentMenu === 'import') h = 'menu=import';
      else if (currentTrainSub === 'calib') h = 'menu=train&sub=calib';
      else h = 'step=' + currentStep;
      history.replaceState(null, '', '#' + h);
    } catch (e) { /* ignore */ }
  }

  function initNavFromHash() {
    try {
      const raw = (location.hash || '').replace(/^#/, '');
      const q = new URLSearchParams(raw);
      const m = q.get('menu');
      if (m === 'import') {
        setMenu('import');
        return;
      }
      const sub = q.get('sub');
      if (sub && TRAIN_SUB_KEYS.indexOf(sub) >= 0) {
        setMenu('train');
        setTrainSub(sub);
        return;
      }
      const s = q.get('step');
      if (s && STEP_KEYS.indexOf(s) >= 0) setStep(s);
    } catch (e) { /* ignore */ }
  }

  document.querySelectorAll('.tl-menu-item').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMenu(this.getAttribute('data-menu') || 'train');
    });
  });
  document.querySelectorAll('.tl-subnav-item').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMenu('train');
      setTrainSub(this.getAttribute('data-train-sub') || 'new');
    });
  });
  document.querySelectorAll('.tl-step').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setMenu('train');
      setTrainSub('new');
      setStep(this.getAttribute('data-step') || 'capture');
    });
  });
  initNavFromHash();

  // 项目下拉
  if ($('project-select')) {
    $('project-select').addEventListener('change', function () {
      const id = this.value;
      if (id) selectProject(id);
    });
  }

  // 删除当前项目
  function syncDelProjectButton() {
    var btn = $('btn-del-project');
    if (btn) btn.disabled = !state.projectId;
  }
  if ($('btn-del-project')) {
    $('btn-del-project').addEventListener('click', function () {
      var p = (state.projects || []).find(function (x) { return x.id === state.projectId; });
      if (!p) {
        alert(tr('training.pickProjectToDel'));
        return;
      }
      deleteProjectEntry(p, null);
    });
  }

  $('btn-new-project').addEventListener('click', () => $('modal-new').classList.remove('tl-hidden'));
  $('np-cancel').addEventListener('click', () => $('modal-new').classList.add('tl-hidden'));
  if ($('modal-new')) {
    $('modal-new').addEventListener('click', function (e) {
      if (e.target === this) this.classList.add('tl-hidden');
    });
  }

  if ($('np-template')) {
    $('np-template').addEventListener('change', function () {
      applyTemplateToForm(this.value);
    });
  }

  $('np-create').addEventListener('click', async function () {
    const title = $('np-title').value.trim();
    const classesRaw = $('np-classes').value.trim();
    const classes = classesRaw.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    const template_id = ($('np-template') && $('np-template').value) || 'custom';
    const r = await api('/api/training/projects', {
      method: 'POST',
      body: JSON.stringify({ title: title || tr('training.untitled'), classes, template_id }),
    });
    const j = await r.json();
    if (!j.success) {
      alert(j.message || tr('training.createFail'));
      return;
    }
    $('modal-new').classList.add('tl-hidden');
    $('np-title').value = '';
    $('np-classes').value = '';
    await loadProjects();
    await selectProject(j.project.id);
  });

  function rerenderLabLocale() {
    renderProjectSelect();
    if (state.projectId) {
      var p = (state.projects || []).find(function (x) { return x.id === state.projectId; });
      if ($('current-project-label')) $('current-project-label').textContent = projectBadgeText(p);
      refreshDatasetHealth().catch(function () {});
      loadSamples().catch(function () {});
    }
    loadStreams().catch(function () {});
    loadSpecialists().catch(function () {});
    fillTemplateSelect();
    loadWeightOptions().catch(function () {});
    fillClassPicker();
    renderSnapGrid();
    loadCalibAlertTypes().catch(function () {});
  }

  window.__visionaiOnLocaleChange = function () {
    rerenderLabLocale();
  };

  async function bootLab() {
    if (window.VisionAI && VisionAI.i18n) {
      VisionAI.i18n.mountLangSwitch(document.getElementById('langSwitch'));
      await VisionAI.i18n.ready();
    }
    try {
      var cr = await fetch('/api/detection-catalog', { credentials: 'same-origin' });
      var cat = await cr.json();
      window.detectionCatalog = Array.isArray(cat) ? cat : (cat.items || cat.data || []);
    } catch (e) { /* ignore */ }
    await loadTemplates();
    await loadProjects();
    await loadSpecialists();
    await loadStreams();
  }
  bootLab();

  if ($('btn-refresh-specialists')) {
    $('btn-refresh-specialists').addEventListener('click', function () {
      loadSpecialists().catch(function () {});
    });
  }

  function syncImportKindFields() {
    var kind = ($('import-kind') && $('import-kind').value) || 'person_event';
    var root = $('import-kind-fields');
    if (!root) return;
    root.querySelectorAll('[data-for-kind]').forEach(function (el) {
      var forKind = el.getAttribute('data-for-kind');
      if (forKind === kind) {
        el.classList.remove('tl-hidden');
      } else {
        el.classList.add('tl-hidden');
      }
    });
  }

  if ($('import-kind')) {
    $('import-kind').addEventListener('change', syncImportKindFields);
    syncImportKindFields();
  }

  if ($('btn-import-inspect')) {
    $('btn-import-inspect').addEventListener('click', async function () {
      var fileInput = $('import-file');
      var status = $('import-inspect-status');
      if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        alert(tr('training.pickWeightFile'));
        return;
      }
      if (status) status.textContent = tr('training.reading');
      var fd = new FormData();
      fd.append('file', fileInput.files[0]);
      var r = await fetch('/api/training/specialists/inspect', {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      });
      var j = await r.json().catch(function () {
        return {};
      });
      if (!r.ok || !j.success) {
        if (status) status.textContent = j.message || tr('training.readFail');
        return;
      }
      var cls = j.classes || [];
      if ($('import-classes') && cls.length && !$('import-classes').value.trim()) {
        $('import-classes').value = cls.join(',');
      }
      if (status) {
        status.textContent = tr('training.classCount', {
          file: j.filename || '',
          n: cls.length,
          list: cls.map(function (c, i) { return i + '=' + c; }).join(', '),
        });
      }
    });
  }

  if ($('btn-import-specialist')) {
    $('btn-import-specialist').addEventListener('click', async function () {
      var fileInput = $('import-file');
      var status = $('import-status');
      if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        var url = ($('import-weights-url') && $('import-weights-url').value.trim()) || '';
        if (!url) {
          alert(tr('training.pickFileOrUrl'));
          return;
        }
      }
      var key = ($('import-key') && $('import-key').value.trim()) || '';
      if (!key) {
        alert(tr('training.needKey'));
        return;
      }
      var nameZh = ($('import-name-zh') && $('import-name-zh').value.trim()) || key;
      if (
        !window.confirm(
          tr('training.confirmImport', { name: nameZh, key: key })
        )
      ) {
        return;
      }
      if (status) status.textContent = tr('training.importing');
      var fd = new FormData();
      if (fileInput && fileInput.files && fileInput.files[0]) {
        fd.append('file', fileInput.files[0]);
      }
      var wurl = ($('import-weights-url') && $('import-weights-url').value.trim()) || '';
      if (wurl) fd.append('weights_url', wurl);
      fd.append('key', key);
      fd.append('kind', ($('import-kind') && $('import-kind').value) || 'person_event');
      fd.append('name_zh', nameZh);
      fd.append('name_en', ($('import-name-en') && $('import-name-en').value.trim()) || '');
      fd.append('classes', ($('import-classes') && $('import-classes').value) || '');
      fd.append('conf', ($('import-conf') && $('import-conf').value) || '');
      fd.append('score_threshold', ($('import-score') && $('import-score').value) || '');
      fd.append('min_duration_sec', ($('import-duration') && $('import-duration').value) || '');
      fd.append(
        'needs_persons',
        $('import-needs-persons') && $('import-needs-persons').checked ? 'true' : 'false'
      );
      fd.append('positive_class_ids', ($('import-positive-ids') && $('import-positive-ids').value) || '');
      fd.append('subject_class_ids', ($('import-subject-ids') && $('import-subject-ids').value) || '');
      fd.append('comply_class_ids', ($('import-comply-ids') && $('import-comply-ids').value) || '');
      fd.append('class_ids', ($('import-class-ids') && $('import-class-ids').value) || '');
      var r = await fetch('/api/training/specialists/import', {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      });
      var j = await r.json().catch(function () {
        return {};
      });
      if (!r.ok || !j.success) {
        if (status) status.textContent = j.message || tr('training.importFail');
        alert(j.message || tr('training.importFail'));
        return;
      }
      if (status) status.textContent = j.message || tr('training.imported');
      await loadSpecialists();
    });
  }
})();

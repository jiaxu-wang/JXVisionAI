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
    snapSelected: new Set(),
    sampleFiles: [],
    templates: [],
  };

  const HANDLE = 8;
  const MIN_BOX = 4;

  const $ = (id) => document.getElementById(id);

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
        pre.textContent = '命中（≥显示阈值）: ' + JSON.stringify(it.detections, null, 2);
        row.appendChild(pre);
      }
      if (it.candidates && it.candidates.length) {
        var preC = document.createElement('pre');
        preC.className = 'tl-val-det';
        var floor = it.candidate_conf_floor != null ? it.candidate_conf_floor : '';
        preC.textContent =
          '候选（conf≥' +
          floor +
          '，含低于显示阈值 ' +
          (it.conf_threshold != null ? it.conf_threshold : '') +
          ' 的框）:\n' +
          JSON.stringify(it.candidates, null, 2);
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
    sel.innerHTML = '<option value="">\u2014 \u9009\u62e9\u672c\u9879\u76ee\u5df2\u8bad\u7ec3\u6743\u91cd \u2014</option>';
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
    var msg = '确定删除训练项目「' + (p.title || p.id) + '」？\n本地截图、标注与 runs 将全部删除且不可恢复。';
    if (!window.confirm(msg)) return;
    const r = await api('/api/training/projects/' + encodeURIComponent(p.id), { method: 'DELETE' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.success) {
      alert(j.message || '删除失败');
      return;
    }
    if (state.projectId === p.id) {
      state.projectId = null;
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
    const ul = $('project-list');
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
        esc(p.labeled_count + '/' + p.image_count + ' 已标注') +
        '</span>';
      body.addEventListener('click', () => selectProject(p.id));

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tl-project-del';
      btn.setAttribute('aria-label', '删除项目');
      btn.setAttribute('title', '删除项目');
      btn.textContent = '\u2715';
      btn.addEventListener('click', (ev) => deleteProjectEntry(p, ev));

      inner.appendChild(body);
      inner.appendChild(btn);
      li.appendChild(inner);
      ul.appendChild(li);
    });
  }

  async function loadStreams() {
    const r = await api('/api/training/redis-streams');
    const streams = await r.json();
    const sel = $('stream-picker');
    sel.innerHTML = '<option value="">— 可选：Redis 中的流 —</option>';
    streams.forEach((s) => {
      const u = (s.rtsp_url || '').trim();
      if (!u) return;
      const o = document.createElement('option');
      o.value = u;
      o.textContent = (s.name || s.id || '流') + ' — ' + u.substring(0, 48);
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
      'btn-snap-list',
      'btn-snap-import',
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
      return name + ': ' + ((h.boxes_per_class && h.boxes_per_class[i]) || 0) + ' 框';
    });
    var splitHint =
      '划分预估 train/val/test ≈ ' +
      (h.train_images_estimated || '?') +
      '/' +
      (h.val_images_estimated || '?') +
      '/' +
      (h.test_images_estimated || '?');
    box.innerHTML =
      '<div class="tl-health-row ' +
      (h.can_train ? 'ok' : 'warn') +
      '">' +
      '<strong>数据检查</strong> 已审核 ' +
      h.labeled_images +
      ' / 草稿 ' +
      (h.draft_images || 0) +
      ' / 总图 ' +
      h.total_images +
      (h.can_train ? ' · 可开训' : ' · 未达开训门槛') +
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
    if (state.deployTarget === 'make_call') return true;
    var t = getCurrentTemplate();
    if (t && t.deploy_mode === 'specialist') return true;
    if (state.deployMode === 'specialist') return true;
    if (state.templateId === 'custom') return true;
    return false;
  }

  function isSpecialistDeploy() {
    if (state.deployTarget === 'make_call') return false;
    var t = getCurrentTemplate();
    if (t && t.deploy_mode === 'specialist') return true;
    if (state.deployMode === 'specialist') return true;
    if (state.templateId === 'custom') return true;
    return !state.deployTarget;
  }

  async function loadSpecialists() {
    var ul = $('specialist-list');
    if (!ul) return;
    var r = await api('/api/training/specialists');
    var items = await r.json();
    ul.innerHTML = '';
    if (!items.length) {
      var empty = document.createElement('li');
      empty.className = 'tl-muted';
      empty.textContent = '尚无已部署专模';
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
        esc(sp.name_zh || sp.key) +
        '</strong> <span class="tl-muted">(' +
        esc(sp.key) +
        ' · ' +
        esc(sp.kind || '') +
        (sp.origin === 'imported' ? ' · 导入' : ' · 自训') +
        ')</span>';
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'tl-btn tl-btn-ghost tl-btn-sm';
      del.textContent = '删除';
      del.addEventListener('click', function () {
        deleteSpecialist(sp.key, sp.name_zh || sp.key);
      });
      li.appendChild(inner);
      li.appendChild(del);
      ul.appendChild(li);
    });
  }

  async function deleteSpecialist(key, label) {
    if (
      !window.confirm(
        '确定删除专模「' + label + '」（键 ' + key + '）？\n权重将移除，各流检测配置中的该项也会被清除。'
      )
    ) {
      return;
    }
    var r = await api('/api/training/specialists/' + encodeURIComponent(key), { method: 'DELETE' });
    var j = await r.json().catch(function () {
      return {};
    });
    if (!r.ok || !j.success) {
      alert(j.message || '删除失败');
      return;
    }
    await loadSpecialists();
  }

  async function loadTemplates() {
    var r = await api('/api/training/templates');
    state.templates = await r.json();
    var sel = $('np-template');
    if (!sel) return;
    sel.innerHTML = '';
    state.templates.forEach(function (t) {
      var o = document.createElement('option');
      o.value = t.id;
      o.textContent = t.title + (t.id !== 'custom' ? ' (' + (t.classes || []).join(',') + ')' : '');
      sel.appendChild(o);
    });
    applyTemplateToForm(sel.value || 'smoking');
  }

  function applyTemplateToForm(tid) {
    var t = state.templates.find(function (x) {
      return x.id === tid;
    });
    if (!t) return;
    if ($('np-template-desc')) $('np-template-desc').textContent = t.description || '';
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
    document.querySelectorAll('#project-list li').forEach(function (li) {
      li.classList.toggle('active', li.dataset.id === id);
    });
    var r = await api('/api/training/projects');
    var list = await r.json();
    var p = list.find(function (x) {
      return x.id === id;
    });
    state.projectClasses = (p && p.classes) || [];
    state.deployTarget = (p && p.deploy_target) || null;
    state.deployMode = (p && p.deploy_mode) || null;
    state.templateId = (p && p.template_id) || null;
    $('current-project-label').textContent = p
      ? '\u00b7 ' +
        p.title +
        (state.deployTarget
          ? ' [' + state.deployTarget + ']'
          : state.deployMode === 'specialist'
            ? ' [专模]'
            : '')
      : '';
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
    all.textContent = '全部';
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
      !window.confirm('确定从数据集中移除「' + filename + '」？\n对应标注文件（若有）会一并删除。')
    ) {
      return;
    }
    const r = await api('/api/training/projects/' + state.projectId + '/samples', {
      method: 'DELETE',
      body: JSON.stringify({ filename: filename }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.success) {
      alert(j.message || '删除失败');
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
        status === 'reviewed' ? 'ok' : status === 'draft' ? 'draft' : '';

      const body = document.createElement('div');
      body.className = 'tl-sample-body';
      body.innerHTML =
        '<span class="tl-dot ' +
        dotClass +
        '" title="' +
        (status === 'reviewed' ? '已审核' : status === 'draft' ? '草稿待审' : '未标注') +
        '"></span><span class="tl-fname" title="' +
        esc(row.filename) +
        '">' +
        esc(row.filename) +
        '</span>';
      body.addEventListener('click', () => openSample(row.filename));

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tl-sample-del';
      btn.setAttribute('aria-label', '删除样本');
      btn.setAttribute('title', '删除样本');
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
      if (!quiet) $('label-status').textContent = '请先选择图片';
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
      if (!quiet) $('label-status').textContent = '已保存 ' + j.lines + ' 个框';
      await loadSamples();
      return true;
    }
    $('label-status').textContent = j.message || '保存失败';
    return false;
  }

  async function navigateSample(delta) {
    const idx = currentSampleIndex();
    if (idx < 0) {
      $('label-status').textContent = '请先选择一张样本';
      return;
    }
    const nextIdx = idx + delta;
    if (nextIdx < 0 || nextIdx >= state.sampleFiles.length) return;
    const ok = await saveLabels({ quiet: true });
    if (!ok) return;
    await openSample(state.sampleFiles[nextIdx]);
    $('label-status').textContent =
      (delta < 0 ? '已保存并上一张 · ' : '已保存并下一张 · ') +
      (nextIdx + 1) +
      ' / ' +
      state.sampleFiles.length;
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
    $('label-status').textContent = '已撤销';
  }

  function redoBoxes() {
    if (state.historyIndex >= state.history.length - 1) return;
    applyHistoryIndex(state.historyIndex + 1);
    $('label-status').textContent = '已重做';
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
    $('label-status').textContent = '已删除选中框';
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
      alert('请输入 rtsp:// 地址');
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
      alert(j.message || '截帧失败');
    }
  });

  $('btn-train').addEventListener('click', async function () {
    if (!state.projectId) {
      alert('请先选择项目');
      return;
    }
    var health = await refreshDatasetHealth();
    if (health && !health.can_train) {
      alert(
        '未达开训门槛，已禁止强制开训：\n' +
          (health.errors || []).join('\n') +
          '\n\n请补齐已审核样本（绿点）后再训。'
      );
      $('train-status').textContent = '未达门槛';
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
      $('train-status').textContent = j.message || '启动失败';
      if (j.health) refreshDatasetHealth();
      return;
    }
    $('train-job-panel').classList.remove('tl-hidden');
    $('job-id').textContent = j.job_id;
    state.lastJobId = j.job_id;
    $('train-status').textContent = '任务已启动';
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
      j.status === 'completed' ? '已完成' : j.status === 'failed' ? '失败' : '运行中…';
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
          valLine = 'Val 评估失败: ' + esc(j.evaluation.error || '');
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
          testLine = '<br>Test 评估失败: ' + esc(j.test_evaluation.error || '');
        }
        var gateLine = '';
        if (j.deploy_ready && canShowDeployButton()) {
          gateLine = '<br><span class="tl-gate-ok">已达上线门禁，可部署</span>';
          $('btn-deploy').classList.remove('tl-hidden');
        } else if (j.deploy_ready) {
          gateLine = '<br><span class="tl-gate-ok">已达上线门禁</span>';
          $('btn-deploy').classList.add('tl-hidden');
        } else {
          gateLine =
            '<br><span class="tl-gate-bad">未达上线门禁</span> ' +
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
      alert('当前项目不可部署');
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
      var key = window.prompt('专模键名（小写 a-z 开头，如 smoking）', sd.key_suggestion || 'custom_model');
      if (!key || !key.trim()) return;
      var nameZh = window.prompt('中文显示名', sd.name_zh || key.trim());
      if (nameZh === null) return;
      var kind = window.prompt('类型：scene / person_event / violation', sd.kind || 'person_event');
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
      if (
        !window.confirm(
          '部署专模到 models/specialists/' +
            body.key +
            '？插件将热加载，可在管理平台检测类型中勾选。继续？'
        )
      ) {
        return;
      }
    } else {
      body.target = state.deployTarget || 'make_call';
      body.patch_config = true;
      if (
        !window.confirm(
          '将通过测试集门禁的 best.pt 部署到 models/ 并更新 config.ini（' +
            body.target +
            '）。\nmake_call 会自动导出 ONNX。\n部署后需重启服务。继续？'
        )
      ) {
        return;
      }
    }
    var r = await api('/api/training/projects/' + state.projectId + '/deploy', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    var j = await r.json();
    $('deploy-status').textContent = j.message || (j.success ? '部署成功' : '部署失败');
    if (!j.success) alert(j.message || '部署失败');
    else if (specialist) loadSpecialists().catch(function () {});
  });

  $('btn-refresh-health').addEventListener('click', function () {
    refreshDatasetHealth().catch(function () {});
  });

  $('btn-prelabel').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert('请先在验证区选择已训练权重');
      return;
    }
    if (
      !window.confirm(
        '用所选权重对未标注图片写入「草稿」（labels_draft/）？\n草稿不计入训练，需人工审核或点「保存标注」后才生效。'
      )
    )
      return;
    var r = await api('/api/training/projects/' + state.projectId + '/prelabel', {
      method: 'POST',
      body: JSON.stringify({ weights_path: w, conf: 0.25, only_unlabeled: true }),
    });
    var j = await r.json();
    alert(j.message || (j.success ? '完成' : '失败'));
    if (j.success) {
      await loadSamples();
      await refreshDatasetHealth();
    }
  });

  if ($('btn-approve-all')) {
    $('btn-approve-all').addEventListener('click', async function () {
      if (!state.projectId) return;
      if (!window.confirm('将全部预标注草稿提升为已审核？请确认草稿质量。')) return;
      var r = await api('/api/training/projects/' + state.projectId + '/labels/approve', {
        method: 'POST',
        body: JSON.stringify({ all: true }),
      });
      var j = await r.json();
      alert(j.message || (j.success ? '完成' : '失败'));
      if (j.success) {
        await loadSamples();
        await refreshDatasetHealth();
      }
    });
  }

  function renderSnapList() {
    var ul = $('snap-list');
    if (!ul) return;
    ul.innerHTML = '';
    state.snapItems.forEach(function (it) {
      var li = document.createElement('li');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = state.snapSelected.has(it.path);
      cb.addEventListener('change', function () {
        if (cb.checked) state.snapSelected.add(it.path);
        else state.snapSelected.delete(it.path);
      });
      var span = document.createElement('span');
      span.textContent = it.relative || it.filename;
      li.appendChild(cb);
      li.appendChild(span);
      ul.appendChild(li);
    });
  }

  $('btn-snap-list').addEventListener('click', async function () {
    if (!state.projectId) return;
    var stream = ($('snap-stream') && $('snap-stream').value.trim()) || '';
    var det = ($('snap-det-type') && $('snap-det-type').value.trim()) || '';
    var q = '?limit=50' + (stream ? '&stream=' + encodeURIComponent(stream) : '');
    if (det) q += '&detection_type=' + encodeURIComponent(det);
    var r = await api('/api/training/snapshots' + q);
    state.snapItems = await r.json();
    state.snapSelected = new Set();
    renderSnapList();
  });

  $('btn-snap-import').addEventListener('click', async function () {
    if (!state.projectId) return;
    var paths = Array.from(state.snapSelected);
    if (!paths.length) {
      alert('请先勾选快照');
      return;
    }
    var r = await api('/api/training/projects/' + state.projectId + '/import-snapshots', {
      method: 'POST',
      body: JSON.stringify({ paths: paths }),
    });
    var j = await r.json();
    alert('已导入 ' + (j.count || 0) + ' 张');
    await loadSamples();
    await refreshDatasetHealth();
  });

  $('btn-threshold-suggest').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert('请先选择权重');
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
      pre.textContent = j.message || '分析失败';
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
      if ($('val-upload-status')) $('val-upload-status').textContent = j.message || '\u4e0a\u4f20\u5931\u8d25';
      return;
    }
    state.lastUploadedValidateFile = j.filename;
    if ($('val-upload-status')) {
      $('val-upload-status').textContent =
        '\u5df2\u4e0a\u4f20\uff1a' + j.filename + '\uff08\u9009\u300c\u5355\u6b21\uff1a\u4e0a\u4f20\u56fe\u7247\u300d\u540e\u70b9\u6267\u884c\u5355\u6b21\u9a8c\u8bc1\uff09';
    }
  });

  $('btn-val-once').addEventListener('click', async function () {
    if (!state.projectId) {
      alert('\u8bf7\u5148\u9009\u62e9\u9879\u76ee');
      return;
    }
    var w = resolveWeightsPath();
    if (!w) {
      alert('\u8bf7\u9009\u62e9\u6216\u586b\u5199\u6743\u91cd\u8def\u5f84');
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
        alert('\u8bf7\u5148\u9009\u62e9\u5e76\u4e0a\u4f20\u4e00\u5f20\u56fe\u7247');
        return;
      }
    } else {
      body.source = 'rtsp';
      body.rtsp_url = $('rtsp-url').value.trim();
      if (!body.rtsp_url.toLowerCase().startsWith('rtsp')) {
        alert('RTSP \u5730\u5740\u65e0\u6548');
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
      alert(j.message || '\u9a8c\u8bc1\u5931\u8d25');
      return;
    }
    await refreshValidateLogs();
  });

  $('btn-val-start').addEventListener('click', async function () {
    if (!state.projectId) return;
    var w = resolveWeightsPath();
    if (!w) {
      alert('\u8bf7\u9009\u62e9\u6216\u586b\u5199\u6743\u91cd');
      return;
    }
    var rtsp = $('rtsp-url').value.trim();
    if (!rtsp.toLowerCase().startsWith('rtsp')) {
      alert('\u8bf7\u5148\u5728\u4e0a\u65b9\u586b\u5199\u6709\u6548\u7684 RTSP\u5730\u5740');
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
      alert(j.message || '\u542f\u52a8\u5931\u8d25');
      return;
    }
    state.validateRunning = true;
    setValidateUiRunning(true);
    if ($('val-cycle-status')) $('val-cycle-status').textContent = '\u5faa\u73af\u9a8c\u8bc1\u8fd0\u884c\u4e2d\uff082s \u5237\u65b0\u65e5\u5fd7\uff09\u2026';
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
    if ($('val-cycle-status')) $('val-cycle-status').textContent = '\u5df2\u505c\u6b62\u5faa\u73af\u9a8c\u8bc1';
    await refreshValidateLogs();
  });

  $('btn-val-logs-refresh').addEventListener('click', function () {
    refreshValidateLogs().catch(function () {});
  });

  $('btn-new-project').addEventListener('click', () => $('modal-new').classList.remove('tl-hidden'));
  $('np-cancel').addEventListener('click', () => $('modal-new').classList.add('tl-hidden'));

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
      body: JSON.stringify({ title: title || '未命名训练', classes, template_id }),
    });
    const j = await r.json();
    if (!j.success) {
      alert(j.message || '创建失败');
      return;
    }
    $('modal-new').classList.add('tl-hidden');
    $('np-title').value = '';
    $('np-classes').value = '';
    await loadProjects();
    await selectProject(j.project.id);
  });

  loadTemplates()
    .then(function () {
      return loadProjects();
    })
    .then(function () {
      return loadSpecialists();
    })
    .then(loadStreams);

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
        alert('请先选择权重文件');
        return;
      }
      if (status) status.textContent = '读取中…';
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
        if (status) status.textContent = j.message || '读取失败';
        return;
      }
      var cls = j.classes || [];
      if ($('import-classes') && cls.length && !$('import-classes').value.trim()) {
        $('import-classes').value = cls.join(',');
      }
      if (status) {
        status.textContent =
          (j.filename || '') +
          ' · ' +
          cls.length +
          ' 类：' +
          cls.map(function (c, i) {
            return i + '=' + c;
          }).join(', ');
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
          alert('请先选择权重文件或填写权重 URL');
          return;
        }
      }
      var key = ($('import-key') && $('import-key').value.trim()) || '';
      if (!key) {
        alert('请填写专模键名 key');
        return;
      }
      var nameZh = ($('import-name-zh') && $('import-name-zh').value.trim()) || key;
      if (
        !window.confirm(
          '确认导入专模「' + nameZh + '」（键 ' + key + '）？\n同名键将备份旧权重后覆盖。'
        )
      ) {
        return;
      }
      if (status) status.textContent = '导入中…';
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
        if (status) status.textContent = j.message || '导入失败';
        alert(j.message || '导入失败');
        return;
      }
      if (status) status.textContent = j.message || '已导入';
      await loadSpecialists();
    });
  }
})();

(function () {
  'use strict';

  const state = {
    projectId: null,
    projectClasses: [],
    deployTarget: null,
    templateId: null,
    imageName: null,
    naturalW: 0,
    naturalH: 0,
    boxes: [],
    drag: null,
    jobPoll: null,
    lastJobId: null,
    validatePollTimer: null,
    validateRunning: false,
    lastUploadedValidateFile: null,
    snapItems: [],
    snapSelected: new Set(),
    templates: [],
  };

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
      $('sample-list').innerHTML = '';
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
    box.innerHTML =
      '<div class="tl-health-row ' +
      (h.can_train ? 'ok' : 'warn') +
      '">' +
      '<strong>数据检查</strong> ' +
      h.labeled_images +
      '/' +
      h.total_images +
      ' 已标注' +
      (h.can_train ? ' · 可开训' : ' · 未达开训门槛') +
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
    state.templateId = (p && p.template_id) || null;
    $('current-project-label').textContent = p
      ? '\u00b7 ' + p.title + (state.deployTarget ? ' [' + state.deployTarget + ']' : '')
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
    const ul = $('sample-list');
    ul.innerHTML = '';
    rows.forEach((row) => {
      const li = document.createElement('li');
      li.dataset.file = row.filename;
      if (row.filename === state.imageName) li.classList.add('on');

      const body = document.createElement('div');
      body.className = 'tl-sample-body';
      body.innerHTML =
        '<span class="tl-dot ' +
        (row.labeled ? 'ok' : '') +
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
  }

  function boxToYolo(b, nw, nh) {
    const x1 = Math.min(b.x1, b.x2);
    const x2 = Math.max(b.x1, b.x2);
    const y1 = Math.min(b.y1, b.y2);
    const y2 = Math.max(b.y1, b.y2);
    const w = x2 - x1;
    const h = y2 - y1;
    const cx = (x1 + x2) / 2 / nw;
    const cy = (y1 + y2) / 2 / nh;
    return {
      class_index: b.class_index,
      cx: cx,
      cy: cy,
      w: w / nw,
      h: h / nh,
    };
  }

  function clearCanvas() {
    state.imageName = null;
    state.boxes = [];
    state.naturalW = 0;
    state.naturalH = 0;
    const c = $('anno-canvas');
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, c.width, c.height);
    $('annotate-filename').textContent = '';
    $('label-status').textContent = '';
  }

  async function openSample(filename) {
    if (!state.projectId) return;
    state.imageName = filename;
    document.querySelectorAll('#sample-list li').forEach((li) => {
      li.classList.toggle('on', li.dataset.file === filename);
    });
    $('annotate-filename').textContent = filename;

    const url = '/api/training/projects/' + state.projectId + '/image/' + encodeURIComponent(filename);
    const img = new Image();
    img.onload = async function () {
      state.naturalW = img.naturalWidth;
      state.naturalH = img.naturalHeight;
      const c = $('anno-canvas');
      c.width = state.naturalW;
      c.height = state.naturalH;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      state.boxes = [];
      const lr = await api(
        '/api/training/projects/' + state.projectId + '/labels/' + encodeURIComponent(filename.replace(/\.[^.]+$/, '') + '.txt')
      );
      const txt = await lr.text();
      parseYoloLines(txt);
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

  function redraw() {
    const c = $('anno-canvas');
    if (!state.naturalW) return;
    const ctx = c.getContext('2d');
    const img = new Image();
    img.onload = function () {
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0);
      state.boxes.forEach((b, idx) => {
        const x1 = Math.min(b.x1, b.x2);
        const y1 = Math.min(b.y1, b.y2);
        const x2 = Math.max(b.x1, b.x2);
        const y2 = Math.max(b.y1, b.y2);
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        const name = state.projectClasses[b.class_index] || String(b.class_index);
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.fillRect(x1, y1 - 18, Math.min(200, name.length * 8 + 8), 18);
        ctx.fillStyle = '#fff';
        ctx.font = '14px sans-serif';
        ctx.fillText(name, x1 + 4, y1 - 4);
      });
    };
    img.src = '/api/training/projects/' + state.projectId + '/image/' + encodeURIComponent(state.imageName);
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

  $('anno-canvas').addEventListener('mousedown', function (ev) {
    if (!state.imageName || !state.naturalW) return;
    const { x, y } = canvasCoords(ev);
    const ci = parseInt($('class-picker').value, 10) || 0;
    state.drag = { x1: x, y1: y, x2: x, y2: y, class_index: ci };
  });

  $('anno-canvas').addEventListener('mousemove', function (ev) {
    if (!state.drag) return;
    const { x, y } = canvasCoords(ev);
    state.drag.x2 = x;
    state.drag.y2 = y;
    const c = $('anno-canvas');
    const ctx = c.getContext('2d');
    const img = new Image();
    img.onload = function () {
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0);
      state.boxes.forEach((b) => {
        const x1 = Math.min(b.x1, b.x2);
        const y1 = Math.min(b.y1, b.y2);
        const x2 = Math.max(b.x1, b.x2);
        const y2 = Math.max(b.y1, b.y2);
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      });
      const d = state.drag;
      ctx.strokeStyle = '#fbbf24';
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(
        Math.min(d.x1, d.x2),
        Math.min(d.y1, d.y2),
        Math.abs(d.x2 - d.x1),
        Math.abs(d.y2 - d.y1)
      );
      ctx.setLineDash([]);
    };
    img.src = '/api/training/projects/' + state.projectId + '/image/' + encodeURIComponent(state.imageName);
  });

  $('anno-canvas').addEventListener('mouseup', function () {
    if (!state.drag) return;
    const d = state.drag;
    state.drag = null;
    const w = Math.abs(d.x2 - d.x1);
    const h = Math.abs(d.y2 - d.y1);
    if (w < 4 || h < 4) {
      redraw();
      return;
    }
    state.boxes.push({
      class_index: d.class_index,
      x1: d.x1,
      y1: d.y1,
      x2: d.x2,
      y2: d.y2,
    });
    redraw();
  });

  $('anno-canvas').addEventListener('dblclick', function (ev) {
    if (!state.imageName || !state.naturalW) return;
    const { x, y } = canvasCoords(ev);
    for (let i = state.boxes.length - 1; i >= 0; i--) {
      const b = state.boxes[i];
      const x1 = Math.min(b.x1, b.x2);
      const y1 = Math.min(b.y1, b.y2);
      const x2 = Math.max(b.x1, b.x2);
      const y2 = Math.max(b.y1, b.y2);
      if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
        state.boxes.splice(i, 1);
        redraw();
        break;
      }
    }
  });

  async function saveLabels() {
    if (!state.projectId || !state.imageName || !state.naturalW) {
      $('label-status').textContent = '请先选择图片';
      return;
    }
    const nw = state.naturalW;
    const nh = state.naturalH;
    const boxes = state.boxes.map((b) => {
      const y = boxToYolo(b, nw, nh);
      return y;
    });
    const r = await api('/api/training/projects/' + state.projectId + '/labels', {
      method: 'POST',
      body: JSON.stringify({ image: state.imageName, boxes }),
    });
    const j = await r.json();
    if (j.success) {
      $('label-status').textContent = '已保存 ' + j.lines + ' 个框';
      loadSamples();
    } else {
      $('label-status').textContent = j.message || '保存失败';
    }
  }

  $('btn-save-labels').addEventListener('click', saveLabels);
  document.addEventListener('keydown', function (e) {
    if (e.key === 's' || e.key === 'S') {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
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
    var force = false;
    if (health && !health.can_train) {
      if (
        !window.confirm(
          '未达开训门槛：\n' +
            (health.errors || []).join('\n') +
            '\n\n仍要强制开训？（仅建议调试）'
        )
      ) {
        $('train-status').textContent = '已取消';
        return;
      }
      force = true;
    }
    const body = {
      epochs: parseInt($('train-epochs').value, 10) || 30,
      batch_size: parseInt($('train-batch').value, 10) || 8,
      img_size: parseInt($('train-imgsz').value, 10) || 640,
      device: $('train-device').value.trim() || 'cpu',
      pretrained_model: $('train-pretrained').value.trim() || 'yolov8n.pt',
      force: force,
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
      if (state.deployTarget) $('btn-deploy').classList.remove('tl-hidden');
      var em = $('job-eval-metrics');
      if (em && j.evaluation && j.evaluation.ok) {
        em.classList.remove('tl-hidden');
        em.innerHTML =
          'mAP@0.5: <b>' +
          (j.map50 != null ? j.map50.toFixed(4) : j.evaluation.map50) +
          '</b> · P: ' +
          (j.precision != null ? j.precision.toFixed(4) : j.evaluation.precision) +
          ' · R: ' +
          (j.recall != null ? j.recall.toFixed(4) : j.evaluation.recall);
      } else if (em && j.evaluation && !j.evaluation.ok) {
        em.classList.remove('tl-hidden');
        em.textContent = '自动评估失败: ' + (j.evaluation.error || '');
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
    if (!state.deployTarget) {
      alert('该项目未绑定部署目标');
      return;
    }
    if (
      !window.confirm(
        '将 best.pt 部署到 models/ 并更新 config.ini（' +
          state.deployTarget +
          '）。需重启 JXVisionAI 后生效。继续？'
      )
    ) {
      return;
    }
    var r = await api('/api/training/projects/' + state.projectId + '/deploy', {
      method: 'POST',
      body: JSON.stringify({
        job_id: state.lastJobId,
        target: state.deployTarget,
        backup: true,
        patch_config: true,
      }),
    });
    var j = await r.json();
    $('deploy-status').textContent = j.message || (j.success ? '部署成功' : '部署失败');
    if (!j.success) alert(j.message || '部署失败');
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
    if (!window.confirm('用所选权重对未标注图片预标注？请人工复核后保存。')) return;
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
    .then(loadStreams);
})();

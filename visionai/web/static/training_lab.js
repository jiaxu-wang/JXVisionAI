(function () {
  'use strict';

  const state = {
    projectId: null,
    projectClasses: [],
    imageName: null,
    naturalW: 0,
    naturalH: 0,
    boxes: [],
    drag: null,
    jobPoll: null,
    validatePollTimer: null,
    validateRunning: false,
    lastUploadedValidateFile: null,
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
    $('current-project-label').textContent = p ? '\u00b7 ' + p.title : '';
    fillClassPicker();
    await loadSamples();
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
    const body = {
      epochs: parseInt($('train-epochs').value, 10) || 30,
      batch_size: parseInt($('train-batch').value, 10) || 8,
      img_size: parseInt($('train-imgsz').value, 10) || 640,
      device: $('train-device').value.trim() || 'cpu',
      pretrained_model: $('train-pretrained').value.trim() || 'yolov8n.pt',
    };
    const r = await api('/api/training/projects/' + state.projectId + '/train', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!j.success) {
      $('train-status').textContent = j.message || '启动失败';
      return;
    }
    $('train-job-panel').classList.remove('tl-hidden');
    $('job-id').textContent = j.job_id;
    $('train-status').textContent = '任务已启动';
    $('job-log-link').href = '/api/training/jobs/' + j.job_id + '/log';
    $('job-weights-link').classList.add('tl-hidden');
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

  $('np-create').addEventListener('click', async function () {
    const title = $('np-title').value.trim();
    const classesRaw = $('np-classes').value.trim();
    const classes = classesRaw.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    const r = await api('/api/training/projects', {
      method: 'POST',
      body: JSON.stringify({ title: title || '未命名训练', classes }),
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

  loadProjects().then(loadStreams);
})();

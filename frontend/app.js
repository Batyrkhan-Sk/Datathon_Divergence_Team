/* UI controller: upload -> processing -> result / error. No framework.
   All API strings go into the DOM through textContent only. */
(function () {
  'use strict';

  var Fmt = window.Fmt;
  var POLL_MS = 2000;
  var MAX_BACKOFF_MS = 15000;
  var POLL_TIMEOUT_MS = 6 * 60 * 1000;
  var LONG_DOC_CHARS = 140;
  var BASE_TITLE = document.title;

  /* ---------- setup ---------- */

  var params = new URLSearchParams(window.location.search);
  var mockScenario = params.get('mock');
  if (mockScenario === '1' || mockScenario === 'true' || mockScenario === '') mockScenario = 'violation';
  var api = mockScenario ? window.Api.createMock(mockScenario) : window.Api.createReal();
  var pollTimeoutMs = api.pollTimeoutMs || POLL_TIMEOUT_MS;

  function $(id) { return document.getElementById(id); }

  var views = {
    upload: $('view-upload'),
    processing: $('view-processing'),
    error: $('view-error'),
    result: $('view-result')
  };
  var video = $('video');

  var state = {
    session: null,     // current upload/poll run; cancelled on reset
    file: null,        // the user's local file (played via object URL)
    jobId: null,
    objectUrl: null,
    result: null,      // normalised result
    playerOk: false,
    lightbox: null     // { vIndex, fIndex, opener }
  };

  /* ---------- small DOM helpers ---------- */

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? '' : v);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  function svgIcon(pathD, cls) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    if (cls) svg.setAttribute('class', cls);
    var p = document.createElementNS(ns, 'path');
    p.setAttribute('d', pathD);
    svg.appendChild(p);
    return svg;
  }

  function announce(msg) {
    var region = $('sr-status');
    region.textContent = '';
    // A tick later so repeated identical messages are still announced.
    setTimeout(function () { region.textContent = msg; }, 50);
  }

  function showView(name, focusId) {
    Object.keys(views).forEach(function (k) { views[k].hidden = k !== name; });
    document.body.setAttribute('data-view', name);
    if (name !== 'processing') document.title = BASE_TITLE;
    var target = focusId ? $(focusId) : null;
    if (target) target.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  function setBar(bar, fraction) {
    var fill = bar.firstElementChild;
    if (fraction === null || fraction === undefined || !isFinite(fraction)) {
      bar.classList.add('is-indeterminate');
      bar.removeAttribute('aria-valuenow');
      bar.setAttribute('aria-valuetext', 'Выполняется');
      fill.style.width = '';
      return;
    }
    var pct = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
    bar.classList.remove('is-indeterminate');
    bar.setAttribute('aria-valuenow', String(pct));
    bar.setAttribute('aria-valuetext', pct + '%');
    fill.style.width = pct + '%';
  }

  /* ---------- sessions (cancellable runs) ---------- */

  function newSession() {
    if (state.session) cancelSession(state.session);
    var s = { cancelled: false, timers: [], upload: null, startedAt: Date.now() };
    state.session = s;
    return s;
  }

  function cancelSession(s) {
    s.cancelled = true;
    s.timers.forEach(function (t) { clearTimeout(t); clearInterval(t); });
    s.timers = [];
    if (s.upload) { try { s.upload.abort(); } catch (e) { /* already finished */ } }
  }

  function sleep(ms, s) {
    return new Promise(function (resolve) { s.timers.push(setTimeout(resolve, ms)); });
  }

  /* ---------- upload screen ---------- */

  var dropzone = $('dropzone');
  var fileInput = $('file-input');
  var uploadError = $('upload-error');

  function showUploadError(msg) {
    uploadError.textContent = msg;
    uploadError.hidden = !msg;
    dropzone.classList.toggle('has-error', !!msg);
  }

  function handleFiles(list) {
    if (!list || !list.length) return;
    var file = list[0];
    var problem = Fmt.validateFile(file);
    if (problem) {
      showUploadError(problem);
      fileInput.value = '';
      return;
    }
    showUploadError('');
    start(file);
  }

  fileInput.addEventListener('change', function () { handleFiles(fileInput.files); });

  var dragDepth = 0;
  dropzone.addEventListener('dragenter', function (e) {
    e.preventDefault(); dragDepth++; dropzone.classList.add('is-dragover');
  });
  dropzone.addEventListener('dragleave', function () {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropzone.classList.remove('is-dragover');
  });
  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault(); dragDepth = 0; dropzone.classList.remove('is-dragover');
    if (!views.upload.hidden) handleFiles(e.dataTransfer && e.dataTransfer.files);
  });
  // A file dropped anywhere else must not make the browser navigate away.
  ['dragover', 'drop'].forEach(function (type) {
    window.addEventListener(type, function (e) {
      if (!dropzone.contains(e.target)) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'none';
      }
    });
  });

  /* ---------- processing ---------- */

  var uploadBar = $('upload-bar');
  var analysisBar = $('analysis-bar');

  function setProcStatus(msg) { $('proc-status').textContent = msg; }

  function showProcessing(file, uploadDone) {
    $('proc-file-name').textContent = file.name;
    $('proc-file-size').textContent = Fmt.formatBytes(file.size);
    $('stage-upload').classList.toggle('is-done', !!uploadDone);
    $('stage-analysis').classList.toggle('is-pending', !uploadDone);
    $('stage-analysis').classList.remove('is-done');
    setBar(uploadBar, uploadDone ? 1 : 0);
    $('upload-value').textContent = uploadDone ? 'Готово' : '0%';
    setBar(analysisBar, 0);
    $('analysis-value').textContent = uploadDone ? '' : 'Ожидание';
    $('proc-elapsed').textContent = '0:00';
    showView('processing', 'processing-title');
  }

  function startElapsedClock(s) {
    var tick = function () {
      $('proc-elapsed').textContent = Fmt.formatElapsed((Date.now() - s.startedAt) / 1000);
    };
    tick();
    s.timers.push(setInterval(tick, 1000));
  }

  function start(file) {
    state.file = file;
    state.jobId = null;
    var s = newSession();
    showProcessing(file, false);
    startElapsedClock(s);
    setProcStatus('Загружаем видео на сервер…');
    announce('Загрузка видео началась.');

    s.upload = api.upload(file, function (fraction) {
      if (s.cancelled) return;
      setBar(uploadBar, fraction);
      $('upload-value').textContent = fraction === null ? '' : Fmt.formatPercent(fraction);
      if (fraction !== null) document.title = '(' + Fmt.formatPercent(fraction) + ') Загрузка — ' + BASE_TITLE;
      if (fraction === 1) setProcStatus('Видео загружено. Запускаем анализ…');
    });

    s.upload.promise.then(function (resp) {
      if (s.cancelled) return;
      s.upload = null;
      state.jobId = String(resp.job_id);
      markUploadDone();
      announce('Видео загружено. Идёт анализ.');
      return poll(state.jobId, s);
    }).catch(function (err) {
      if (s.cancelled || (err && err.status === -1)) return;
      s.upload = null;
      cancelSession(s);
      showError({
        title: 'Не удалось загрузить видео',
        message: (err && err.message) || 'Ошибка при отправке файла.',
        detail: err && err.detail,
        actions: [
          { label: 'Повторить', primary: true, onClick: function () { start(file); } },
          { label: 'Выбрать другой файл', onClick: reset }
        ]
      });
    });
  }

  function markUploadDone() {
    $('stage-upload').classList.add('is-done');
    $('stage-analysis').classList.remove('is-pending');
    setBar(uploadBar, 1);
    $('upload-value').textContent = 'Готово';
    $('analysis-value').textContent = '';
    setBar(analysisBar, 0);
    setProcStatus('Анализируем запись…');
  }

  function updateAnalysis(progress) {
    var p = (typeof progress === 'number' && isFinite(progress)) ? progress : null;
    setBar(analysisBar, p);
    $('analysis-value').textContent = p === null ? '' : Fmt.formatPercent(p);
    document.title = (p === null ? '' : '(' + Fmt.formatPercent(p) + ') ') + 'Анализ — ' + BASE_TITLE;
  }

  /** Polls until done/failed, with backoff on network errors and a hard timeout. */
  function poll(jobId, s) {
    var deadline = Date.now() + pollTimeoutMs;
    var failures = 0;

    function step() {
      if (s.cancelled) return Promise.resolve();
      if (Date.now() > deadline) { showTimeout(jobId, s); return Promise.resolve(); }

      return api.getJob(jobId).then(function (job) {
        if (s.cancelled) return;
        if (failures) setProcStatus('Связь восстановлена. Анализируем запись…');
        failures = 0;
        if (job.status === 'done') {
          cancelSession(s);
          return renderResult(job);
        }
        if (job.status === 'failed') {
          cancelSession(s);
          showError({
            title: 'Анализ не удалось завершить',
            message: 'Сервис не смог обработать это видео. Попробуйте ещё раз или выберите другой файл.',
            detail: job.error ? String(job.error) : '',
            actions: [
              { label: 'Повторить', primary: true, onClick: function () { start(state.file); } },
              { label: 'Выбрать другой файл', onClick: reset }
            ]
          });
          return;
        }
        updateAnalysis(job.progress);
        return sleep(POLL_MS, s).then(step);
      }, function (err) {
        if (s.cancelled) return;
        if (!err || !err.retryable) {
          cancelSession(s);
          showError({
            title: 'Не удалось получить результат',
            message: (err && err.message) || 'Ошибка при запросе статуса.',
            detail: err && err.detail,
            actions: [
              { label: 'Загрузить заново', primary: true, onClick: function () { start(state.file); } },
              { label: 'Выбрать другой файл', onClick: reset }
            ]
          });
          return;
        }
        failures++;
        var delay = Math.min(POLL_MS * Math.pow(2, failures), MAX_BACKOFF_MS);
        setProcStatus(err.message + ' Повторная попытка через ' + Math.round(delay / 1000) + ' с…');
        if (failures === 1) announce('Нет связи с сервером. Повторяем запрос.');
        return sleep(delay, s).then(step);
      });
    }

    return step();
  }

  function showTimeout(jobId, s) {
    cancelSession(s);
    showError({
      title: 'Анализ занимает больше времени, чем ожидалось',
      message: 'Результат не получен за 6 минут. Можно подождать ещё или отправить видео повторно.',
      actions: [
        { label: 'Продолжить ожидание', primary: true, onClick: function () { resume(jobId); } },
        { label: 'Загрузить заново', onClick: function () { start(state.file); } },
        { label: 'Проверить другое видео', onClick: reset }
      ]
    });
  }

  function resume(jobId) {
    var s = newSession();
    showProcessing(state.file, true);
    markUploadDone();
    startElapsedClock(s);
    announce('Продолжаем ожидание результата.');
    poll(jobId, s);
  }

  $('btn-cancel').addEventListener('click', function () {
    reset();
    announce('Проверка отменена.');
  });

  window.addEventListener('beforeunload', function (e) {
    if (!views.processing.hidden) { e.preventDefault(); e.returnValue = ''; }
  });

  /* ---------- error screen ---------- */

  function showError(opts) {
    $('error-title').textContent = opts.title;
    $('error-message').textContent = opts.message || '';
    var detail = $('error-detail');
    detail.textContent = opts.detail ? 'Подробности: ' + opts.detail : '';
    detail.hidden = !opts.detail;
    var box = $('error-actions');
    box.textContent = '';
    (opts.actions || []).forEach(function (a) {
      box.appendChild(el('button', {
        type: 'button',
        class: 'btn ' + (a.primary ? 'btn-primary' : 'btn-secondary'),
        text: a.label,
        onclick: a.onClick
      }));
    });
    showView('error', 'error-title');
    announce(opts.title + '. ' + (opts.message || ''));
  }

  /* ---------- result ---------- */

  function renderResult(job) {
    var r = Fmt.normalizeResult(job);
    state.result = r;
    var n = r.violations.length;

    var banner = $('verdict');
    banner.classList.toggle('is-violation', r.isViolation);
    banner.classList.toggle('is-clean', !r.isViolation);
    var title = r.isViolation ? 'Найдены возможные нарушения' : 'Нарушений не найдено';
    $('verdict-title').textContent = title;

    var meta = [];
    if (r.isViolation) {
      meta.push(n ? 'Найдено ' + n + ' ' + Fmt.plural(n, ['эпизод', 'эпизода', 'эпизодов'])
                  : 'Подробности по эпизодам не переданы');
    }
    if (r.processingSec !== null) meta.push('Время обработки: ' + Fmt.formatDuration(r.processingSec));
    if (state.file) meta.push(state.file.name);
    $('verdict-meta').textContent = meta.join(' · ');

    $('player-file').textContent = state.file ? state.file.name + ' · ' + Fmt.formatBytes(state.file.size) : '';

    var list = $('findings');
    list.textContent = '';
    r.violations.forEach(function (v, i) { list.appendChild(renderFinding(v, i)); });
    list.hidden = n === 0;
    $('findings-title').textContent = r.isViolation ? 'Эпизоды для проверки' : 'Итог проверки';
    $('clean-note').hidden = r.isViolation;
    $('disclaimer-extra').hidden = !n;

    setupVideo(state.file, r.violations);
    renderScene(r.scene);
    showView('result', 'verdict-title');
    announce(title + (r.isViolation && n ? '. Эпизодов: ' + n + '.' : '.'));
  }

  // Colours match the boxes drawn by the server (ml/pipeline.py SCENE_COLORS, BGR there).
  var SCENE_COLORS = {
    'Рабочее место (ноутбук)': 'rgb(60,180,60)',
    'Рабочее место (по положению кассира)': 'rgb(60,180,60)',
    'Зона стола': 'rgb(40,140,220)',
    'Сейф': 'rgb(255,140,0)',
    'Человек': 'rgb(150,150,150)'
  };

  function renderScene(scene) {
    var card = $('scene-card');
    if (!scene) { card.hidden = true; return; }
    $('scene-img').src = scene.src;
    var legend = $('scene-legend');
    legend.textContent = '';
    scene.labels.forEach(function (label) {
      legend.appendChild(el('li', null, [
        el('span', { class: 'scene-swatch', 'aria-hidden': 'true',
                     style: 'border-color:' + (SCENE_COLORS[label] || 'currentColor') }),
        el('span', { text: label })
      ]));
    });
    card.hidden = false;
  }

  /* ---------- downloadable report (self-contained HTML, opens offline, prints to PDF) ---------- */

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function buildReport(r) {
    var fileName = state.file ? state.file.name : '';
    var now = new Date();
    var when = now.toLocaleString('ru-RU');
    var verdict = r.isViolation ? 'Обнаружены признаки возможных нарушений' : 'Нарушение не обнаружено';
    var items = r.violations.map(function (v, i) {
      var rule = v.rule ? (
        '<div class="rule"><div class="rule-title">Нормативное основание</div>' +
        (v.rule.document ? '<p>' + esc(v.rule.document) + '</p>' : '') +
        (v.rule.clause ? '<p><b>Пункт:</b> ' + esc(v.rule.clause) + '</p>' : '') +
        (v.rule.quote ? '<blockquote>' + esc(v.rule.quote) + '</blockquote>' : '') +
        (v.rule.url ? '<p><a href="' + esc(v.rule.url) + '">' + esc(v.rule.url) + '</a></p>' : '') +
        '</div>') : '';
      var frames = v.frames.map(function (f) {
        return '<figure><img src="' + esc(f.src) + '" alt=""><figcaption>' +
               esc(Fmt.formatTimecode(f.timestamp)) + '</figcaption></figure>';
      }).join('');
      return '<section class="ep"><h2>' + (i + 1) + '. ' + esc(v.type) + '</h2>' +
        '<p class="meta">Таймкод: <b>' + esc(Fmt.formatTimecode(v.timecode)) + '</b>' +
        (v.confidence !== null ? ' · Уверенность: ' + esc(Fmt.formatPercent(v.confidence)) : '') + '</p>' +
        (v.description ? '<p>' + esc(v.description) + '</p>' : '') +
        (frames ? '<div class="frames">' + frames + '</div>' : '') + rule + '</section>';
    }).join('');
    var scene = r.scene ? (
      '<section class="ep"><h2>Как сервис понял сцену</h2>' +
      '<p class="meta">Объекты найдены автоматически для этой записи: ' + esc(r.scene.labels.join(', ')) + '</p>' +
      '<div class="frames"><figure><img src="' + esc(r.scene.src) + '" alt=""></figure></div></section>') : '';
    var css = 'body{font:15px/1.5 "Segoe UI",Arial,sans-serif;color:#1b2130;max-width:900px;margin:24px auto;padding:0 16px}' +
      'h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 6px}.meta{color:#5a6376;margin:2px 0 8px}' +
      '.verdict{padding:14px 18px;border-radius:10px;margin:16px 0;font-weight:600}' +
      '.v-bad{background:#fdf1ef;color:#b3261e;border:1px solid #f2c3bd}.v-ok{background:#eaf6ef;color:#17703f;border:1px solid #b5dfc5}' +
      '.ep{border:1px solid #dde1e8;border-radius:10px;padding:14px 18px;margin:14px 0;page-break-inside:avoid}' +
      '.frames{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}figure{margin:0}img{max-height:320px;border-radius:6px;display:block}' +
      'figcaption{font-size:12px;color:#5a6376;text-align:center}.rule{background:#f8f9fb;border-radius:8px;padding:10px 14px;margin-top:8px}' +
      '.rule-title{font-weight:600;margin-bottom:4px}blockquote{margin:6px 0;padding-left:10px;border-left:3px solid #c5cbd6;color:#3a4252}' +
      '.note{color:#5a6376;font-size:13px;margin-top:20px}';
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Отчёт — ' + esc(fileName) +
      '</title><style>' + css + '</style></head><body>' +
      '<h1>Контроль кассовой дисциплины — отчёт</h1>' +
      '<p class="meta">Файл: ' + esc(fileName) + ' · Сформирован: ' + esc(when) +
      (r.processingSec !== null ? ' · Время обработки: ' + esc(Fmt.formatDuration(r.processingSec)) : '') + '</p>' +
      '<div class="verdict ' + (r.isViolation ? 'v-bad' : 'v-ok') + '">' + esc(verdict) +
      (r.isViolation ? ' · Эпизодов: ' + r.violations.length : '') + '</div>' +
      items + scene +
      '<p class="note">Результат — подсказка для проверяющего сотрудника, а не окончательное юридическое ' +
      'или дисциплинарное заключение. Каждый эпизод нужно проверить по записи.</p></body></html>';
  }

  function downloadReport() {
    if (!state.result) return;
    var html = buildReport(state.result);
    var base = (state.file ? state.file.name.replace(/\.[^.]+$/, '') : 'video').replace(/[^\w.\-]+/g, '_');
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    a.download = 'report_' + base + '.html';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    announce('Отчёт сохранён');
  }

  function confidenceInfo(c) {
    if (c >= 0.75) return { level: 'high', label: 'высокая' };
    if (c >= 0.5) return { level: 'mid', label: 'средняя' };
    return { level: 'low', label: 'низкая' };
  }

  function renderFinding(v, i) {
    var num = i + 1;
    var tc = Fmt.formatTimecode(v.timecode);
    var titleId = 'finding-title-' + num;

    var metaRow = el('div', { class: 'finding-meta' }, [
      v.timecode !== null ? el('button', {
        type: 'button',
        class: 'timecode-btn',
        'data-seek': String(v.timecode),
        'aria-label': 'Перейти к моменту ' + tc + ' в видео',
        onclick: function () { seekTo(v.timecode, i); }
      }, [svgIcon('M8 5v14l11-7z', 'tc-icon'), el('span', { text: tc })]) : null
    ]);

    if (v.confidence !== null) {
      var ci = confidenceInfo(v.confidence);
      var pct = Fmt.formatPercent(v.confidence);
      metaRow.appendChild(el('span', {
        class: 'confidence is-' + ci.level,
        title: 'Уверенность модели: ' + pct
      }, [
        el('span', { class: 'confidence-bar', 'aria-hidden': 'true' }, [
          el('span', { style: 'width:' + Math.round(v.confidence * 100) + '%' })
        ]),
        el('span', { text: 'Уверенность: ' + ci.label + ' (' + pct + ')' })
      ]));
    }

    var article = el('article', { class: 'finding-card', 'aria-labelledby': titleId }, [
      el('header', { class: 'finding-head' }, [
        el('span', { class: 'finding-num', 'aria-hidden': 'true', text: String(num) }),
        el('h3', { class: 'finding-title', id: titleId }, [
          el('span', { class: 'visually-hidden', text: 'Эпизод ' + num + ': ' }),
          v.type
        ])
      ]),
      metaRow,
      v.description ? el('p', { class: 'finding-desc', text: v.description }) : null,
      v.frames.length ? renderFrames(v, i) : null,
      v.rule ? renderRule(v.rule, num) : null
    ]);

    // Clicking the card body (not its controls) also seeks the video.
    article.addEventListener('click', function (e) {
      if (e.target.closest('button, a, summary, details, input')) return;
      if (window.getSelection && String(window.getSelection())) return; // user is selecting text
      if (v.timecode !== null) seekTo(v.timecode, i);
    });

    return el('li', { class: 'finding', id: 'finding-' + num }, [article]);
  }

  function renderFrames(v, vIndex) {
    var total = v.frames.length;
    return el('div', { class: 'frames-block' }, [
      el('h4', { class: 'block-title', text: total > 1 ? 'Кадры из фрагмента' : 'Кадр из фрагмента' }),
      el('ul', { class: 'frames' }, v.frames.map(function (f, fIndex) {
        var ts = Fmt.formatTimecode(f.timestamp);
        var alt = 'Кадр ' + (fIndex + 1) + ' из ' + total + ', ' + ts + ': ' + v.type;
        return el('li', null, [
          el('button', {
            type: 'button',
            class: 'thumb',
            'aria-label': 'Открыть кадр ' + (fIndex + 1) + ' из ' + total + ' (' + ts + ') крупно',
            onclick: function (e) { openLightbox(vIndex, fIndex, e.currentTarget); }
          }, [
            el('img', { src: f.src, alt: alt, loading: 'lazy', decoding: 'async', width: '464', height: '848' }),
            el('span', { class: 'thumb-time', text: ts })
          ])
        ]);
      }))
    ]);
  }

  function renderRule(rule, num) {
    var docId = 'rule-doc-' + num;
    var children = [el('h4', { class: 'block-title', text: 'Нормативное основание' })];

    if (rule.document) {
      var docP = el('p', { class: 'rule-doc', id: docId, text: rule.document });
      children.push(docP);
      if (rule.document.length > LONG_DOC_CHARS) {
        docP.classList.add('is-clamped');
        var toggle = el('button', {
          type: 'button', class: 'link-btn', 'aria-expanded': 'false', 'aria-controls': docId,
          text: 'Показать полностью'
        });
        toggle.addEventListener('click', function () {
          var open = docP.classList.toggle('is-clamped') === false;
          toggle.setAttribute('aria-expanded', String(open));
          toggle.textContent = open ? 'Свернуть' : 'Показать полностью';
        });
        children.push(toggle);
      }
    }
    if (rule.clause) {
      children.push(el('p', { class: 'rule-clause' }, [
        el('span', { class: 'rule-label', text: 'Пункт: ' }),
        el('strong', { text: rule.clause })
      ]));
    }
    if (rule.quote) {
      children.push(el('details', { class: 'rule-quote' }, [
        el('summary', { text: 'Текст нормы' }),
        el('blockquote', { text: rule.quote })
      ]));
    }
    if (rule.url) {
      var host = Fmt.hostOf(rule.url);
      children.push(el('a', {
        class: 'rule-link', href: rule.url, target: '_blank', rel: 'noopener noreferrer'
      }, [
        host === 'adilet.zan.kz' ? 'Открыть на adilet.zan.kz' : 'Открыть официальный текст',
        svgIcon('M14 4h6v6m0-6L10 14M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5', 'ext-icon'),
        el('span', { class: 'visually-hidden', text: ' (откроется в новой вкладке)' })
      ]));
    }
    return el('section', { class: 'rule', 'aria-label': 'Нормативное основание, эпизод ' + num }, children);
  }

  /* ---------- video ---------- */

  function releaseVideo() {
    video.onloadedmetadata = null;
    video.onerror = null;
    video.ontimeupdate = null;
    try { video.pause(); } catch (e) { /* ignore */ }
    video.removeAttribute('src');
    try { video.load(); } catch (e) { /* ignore */ }
    if (state.objectUrl) { URL.revokeObjectURL(state.objectUrl); state.objectUrl = null; }
  }

  function setPlayerAvailable(ok) {
    state.playerOk = ok;
    $('video-wrap').hidden = !ok;
    $('player-note').hidden = ok;
    document.querySelectorAll('.timecode-btn').forEach(function (b) {
      b.disabled = !ok;
      if (!ok) b.removeAttribute('aria-label');
    });
    $('view-result').classList.toggle('no-player', !ok);
  }

  function setupVideo(file, violations) {
    releaseVideo();
    if (!file) { setPlayerAvailable(false); return; }

    // .mov is often reported as video/quicktime, which Chromium says it cannot
    // play even though H.264 inside it plays fine, so only trust a definite "no"
    // for other types and rely on the error event otherwise.
    var type = file.type || '';
    if (type && type !== 'video/quicktime' && video.canPlayType(type) === '') {
      setPlayerAvailable(false);
      return;
    }

    setPlayerAvailable(true);
    video.onerror = function () { setPlayerAvailable(false); };
    video.onloadedmetadata = function () {
      if (!video.videoWidth) setPlayerAvailable(false); // e.g. audio-only decode
    };
    state.objectUrl = URL.createObjectURL(file);
    video.src = state.objectUrl;
  }

  function isInViewport(node) {
    var r = node.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= (window.innerHeight || document.documentElement.clientHeight);
  }

  function highlight(index) {
    document.querySelectorAll('.finding.is-active').forEach(function (n) {
      n.classList.remove('is-active');
    });
    var card = $('finding-' + (index + 1));
    if (card) card.classList.add('is-active');
    return card;
  }

  function seekTo(t, index) {
    highlight(index);
    if (!state.playerOk) return;
    try { video.currentTime = Math.max(0, t); } catch (e) { return; }
    var wrap = $('video-wrap');
    if (!isInViewport(wrap)) wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    announce('Видео перемотано на ' + Fmt.formatTimecode(t) + '.');
  }

  /* ---------- lightbox ---------- */

  var lightbox = $('lightbox');
  var lbImg = $('lightbox-img');
  var lbVideo = $('lightbox-video');
  var LB_LEAD_SEC = 2; // start a little before the frame so the moment has context

  /** Switches the viewer between the evidence frame and the video at that moment. */
  function setLightboxVideo(on) {
    var lb = state.lightbox;
    if (on && lb && state.objectUrl) {
      var f = state.result.violations[lb.vIndex].frames[lb.fIndex];
      var t = Math.max(0, f.timestamp - LB_LEAD_SEC);
      if (lbVideo.getAttribute('src') !== state.objectUrl) lbVideo.src = state.objectUrl;
      var go = function () {
        lbVideo.onloadedmetadata = null;
        try { lbVideo.currentTime = t; } catch (e) { /* ignore */ }
        var p = lbVideo.play();
        if (p && p.catch) p.catch(function () { /* autoplay blocked: controls stay */ });
      };
      if (lbVideo.readyState >= 1) go(); else lbVideo.onloadedmetadata = go;
      lbImg.hidden = true;
      lbVideo.hidden = false;
      lb.playing = true;
      $('lb-seek').textContent = 'Показать кадр';
      $('lightbox-caption').textContent = 'Эпизод ' + (lb.vIndex + 1) + ' · видео с ' +
        Fmt.formatTimecode(t);
      announce('Воспроизведение с ' + Fmt.formatTimecode(t) + '.');
    } else {
      try { lbVideo.pause(); } catch (e) { /* ignore */ }
      lbVideo.onloadedmetadata = null;
      lbVideo.hidden = true;
      lbImg.hidden = false;
      if (lb) lb.playing = false;
      $('lb-seek').textContent = 'Показать момент в видео';
    }
  }

  function showLightboxFrame() {
    var lb = state.lightbox;
    var v = state.result.violations[lb.vIndex];
    var f = v.frames[lb.fIndex];
    var total = v.frames.length;
    var ts = Fmt.formatTimecode(f.timestamp);
    setLightboxVideo(false);
    lbImg.src = f.src;
    lbImg.alt = 'Кадр ' + (lb.fIndex + 1) + ' из ' + total + ', ' + ts + ': ' + v.type;
    $('lightbox-caption').textContent = 'Эпизод ' + (lb.vIndex + 1) + ' · кадр ' +
      (lb.fIndex + 1) + ' из ' + total + ' · ' + ts;
    $('lb-prev').hidden = total < 2;
    $('lb-next').hidden = total < 2;
    $('lb-seek').hidden = !state.playerOk || f.timestamp === null;
  }

  function openLightbox(vIndex, fIndex, opener) {
    state.lightbox = { vIndex: vIndex, fIndex: fIndex, opener: opener };
    showLightboxFrame();
    if (typeof lightbox.showModal === 'function') lightbox.showModal();
    else lightbox.setAttribute('open', '');
    document.body.classList.add('lightbox-open');
    $('lb-close').focus();
  }

  function closeLightbox() {
    if (lightbox.open) {
      if (typeof lightbox.close === 'function') lightbox.close();
      else lightbox.removeAttribute('open');
    }
  }

  function stepLightbox(delta) {
    var lb = state.lightbox;
    if (!lb) return;
    var total = state.result.violations[lb.vIndex].frames.length;
    if (total < 2) return;
    lb.fIndex = (lb.fIndex + delta + total) % total;
    showLightboxFrame();
  }

  lightbox.addEventListener('close', function () {
    document.body.classList.remove('lightbox-open');
    var opener = state.lightbox && state.lightbox.opener;
    setLightboxVideo(false);
    state.lightbox = null;
    lbImg.removeAttribute('src');
    if (opener && document.body.contains(opener)) opener.focus();
  });
  lightbox.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') { e.preventDefault(); stepLightbox(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); stepLightbox(1); }
    else if (e.key === 'Escape' && typeof lightbox.showModal !== 'function') closeLightbox();
  });
  lightbox.addEventListener('click', function (e) {
    if (e.target === lightbox) closeLightbox(); // backdrop click
  });
  $('lb-close').addEventListener('click', closeLightbox);
  $('lb-prev').addEventListener('click', function () { stepLightbox(-1); });
  $('lb-next').addEventListener('click', function () { stepLightbox(1); });
  $('lb-seek').addEventListener('click', function () {
    var lb = state.lightbox;
    if (!lb) return;
    if (lb.playing) showLightboxFrame();
    else setLightboxVideo(true);
  });

  /* ---------- reset ---------- */

  function reset() {
    if (state.session) cancelSession(state.session);
    state.session = null;
    closeLightbox();
    releaseVideo();
    state.file = null;
    state.jobId = null;
    state.result = null;
    $('findings').textContent = '';
    fileInput.value = '';
    showUploadError('');
    showView('upload', 'upload-title');
  }

  $('btn-reset').addEventListener('click', reset);
  $('btn-report').addEventListener('click', downloadReport);

  /* ---------- mock mode extras ---------- */

  if (mockScenario) {
    var badge = $('mode-badge');
    badge.hidden = false;
    badge.textContent = 'Демо-режим: ' + mockScenario;
    // Test hook for headless screenshots: ?mock=1&auto=1[&video=<url>] starts
    // the flow without a file picker. Ignored outside mock mode.
    if (params.get('auto') === '1') {
      var src = params.get('video');
      var startWith = function (blob, name) {
        start(new File([blob], name, { type: name.slice(-4) === '.mp4' ? 'video/mp4' : 'video/quicktime' }));
      };
      if (src) {
        fetch(src).then(function (r) { return r.blob(); })
          .then(function (b) { startWith(b, src.split('/').pop() || 'video.mov'); })
          .catch(function () { startWith(new Uint8Array(1), 'demo.mov'); });
      } else {
        startWith(new Uint8Array(1), 'demo.mov');
      }
    }
  }

  document.body.setAttribute('data-view', 'upload');
})();

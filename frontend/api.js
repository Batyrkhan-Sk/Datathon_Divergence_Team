/* API client for the backend UI routes, plus a mock used with ?mock=... */
(function (root) {
  'use strict';

  var Fmt = root.Fmt;
  var ANALYZE_URL = '/ui/api/analyze';
  var JOB_URL = '/ui/api/jobs/';
  var REQUEST_TIMEOUT_MS = 15000;

  /** Error with a user-facing message and whether polling may retry it. */
  function ApiError(message, opts) {
    this.name = 'ApiError';
    this.message = message;
    this.status = (opts && opts.status) || 0;
    this.detail = (opts && opts.detail) || '';
    this.retryable = !!(opts && opts.retryable);
  }
  ApiError.prototype = Object.create(Error.prototype);

  function messageForStatus(status) {
    if (status === 413) return 'Файл слишком большой для сервера.';
    if (status === 415) return 'Сервер не принял этот формат файла.';
    if (status === 400 || status === 422) return 'Сервер не принял файл.';
    if (status === 401 || status === 403) return 'Нет доступа к сервису анализа.';
    if (status === 404) return 'Задача анализа не найдена на сервере.';
    if (status === 429 || status === 503) return 'Сервис сейчас загружен. Попробуйте ещё раз через минуту.';
    if (status >= 500) return 'Ошибка на стороне сервиса анализа.';
    return 'Не удалось выполнить запрос к сервису.';
  }

  function isRetryableStatus(status) {
    return status === 0 || status === 408 || status === 429 || status >= 500;
  }

  function parseJson(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  // API paths are absolute (same origin); mock files are relative to the page.
  function resolve(path) {
    return new URL(path, root.location.href).toString();
  }

  /* ---------- real backend ---------- */

  function createReal() {
    return {
      /** Uploads with XHR (fetch has no upload progress). Returns {promise, abort}. */
      upload: function (file, onProgress) {
        var xhr = new XMLHttpRequest();
        var promise = new Promise(function (resolveP, reject) {
          xhr.open('POST', resolve(ANALYZE_URL));
          xhr.responseType = 'text';
          xhr.upload.onprogress = function (e) {
            onProgress(e.lengthComputable ? e.loaded / e.total : null);
          };
          xhr.upload.onload = function () { onProgress(1); };
          xhr.onload = function () {
            var body = parseJson(xhr.responseText);
            if (xhr.status >= 200 && xhr.status < 300) {
              if (body && body.job_id) return resolveP(body);
              return reject(new ApiError('Сервер не вернул идентификатор задачи.', { status: xhr.status }));
            }
            reject(new ApiError(messageForStatus(xhr.status), {
              status: xhr.status, detail: Fmt.errorDetail(body) || xhr.statusText
            }));
          };
          xhr.onerror = function () {
            reject(new ApiError('Не удалось отправить файл: нет связи с сервером.', { retryable: true }));
          };
          xhr.onabort = function () { reject(new ApiError('Загрузка отменена.', { status: -1 })); };
          var form = new FormData();
          form.append('file', file, file.name);
          xhr.send(form);
        });
        return { promise: promise, abort: function () { xhr.abort(); } };
      },

      getJob: function (jobId) {
        var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
        var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, REQUEST_TIMEOUT_MS);
        return fetch(resolve(JOB_URL + encodeURIComponent(jobId)), {
          headers: { Accept: 'application/json' },
          cache: 'no-store',
          signal: ctrl ? ctrl.signal : undefined
        }).then(function (res) {
          return res.text().then(function (text) {
            var body = parseJson(text);
            if (!res.ok) {
              throw new ApiError(messageForStatus(res.status), {
                status: res.status,
                detail: Fmt.errorDetail(body) || res.statusText,
                retryable: isRetryableStatus(res.status)
              });
            }
            if (!body || typeof body !== 'object') {
              throw new ApiError('Сервер вернул некорректный ответ.', { retryable: true });
            }
            return body;
          });
        }, function () {
          throw new ApiError('Нет связи с сервером.', { retryable: true });
        }).finally(function () { clearTimeout(timer); });
      }
    };
  }

  /* ---------- mock (?mock=1 | clean | fail | timeout | noprogress) ---------- */

  function createMock(scenario) {
    var polls = 0;
    var steps = [0.15, 0.4, 0.65, 0.9];
    return {
      isMock: true,
      // Shortens the polling timeout so the timeout screen can be checked quickly.
      pollTimeoutMs: scenario === 'timeout' ? 8000 : null,

      upload: function (file, onProgress) {
        var timer = null;
        var rejectP = null;
        var promise = new Promise(function (resolveP, reject) {
          rejectP = reject;
          var p = 0;
          onProgress(0);
          timer = setInterval(function () {
            p = Math.min(1, p + 0.12);
            onProgress(p);
            if (p >= 1) {
              clearInterval(timer);
              setTimeout(function () { resolveP({ job_id: 'mock-' + scenario }); }, 300);
            }
          }, 150);
        });
        return {
          promise: promise,
          abort: function () {
            clearInterval(timer);
            if (rejectP) rejectP(new ApiError('Загрузка отменена.', { status: -1 }));
          }
        };
      },

      getJob: function (jobId) {
        polls += 1;
        var base = { job_id: jobId, verdict: null, violations: [] };
        if (scenario === 'timeout') {
          return Promise.resolve(Object.assign(base, { status: 'processing', progress: 0.5 }));
        }
        if (polls <= steps.length) {
          var job = Object.assign(base, { status: 'processing' });
          if (scenario !== 'noprogress') job.progress = steps[polls - 1];
          return Promise.resolve(job);
        }
        if (scenario === 'fail') {
          return Promise.resolve(Object.assign(base, {
            status: 'failed', error: 'Не удалось декодировать видео (тестовая ошибка).'
          }));
        }
        var file = scenario === 'clean' ? 'mock/result_clean.json' : 'mock/result.json';
        return fetch(resolve(file), { cache: 'no-store' }).then(function (res) {
          if (!res.ok) throw new ApiError('Не найден файл ' + file, { status: res.status });
          return res.json();
        });
      }
    };
  }

  root.Api = { createReal: createReal, createMock: createMock, ApiError: ApiError };
})(this);

/* Pure helpers: formatting and validation. No DOM access, so they can be
   tested with node (module.exports) and used in the browser (window.Fmt). */
(function (root) {
  'use strict';

  var MAX_FILE_BYTES = 300 * 1024 * 1024;
  var ALLOWED_EXT = ['.mov', '.mp4'];

  function isFiniteNumber(x) {
    return typeof x === 'number' && isFinite(x);
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  /** 9 -> "00:09.0", 74.26 -> "01:14.3". Minutes are not wrapped into hours. */
  function formatTimecode(sec) {
    if (!isFiniteNumber(sec) || sec < 0) return '--:--.-';
    var tenths = Math.round(sec * 10);
    var minutes = Math.floor(tenths / 600);
    var rest = tenths - minutes * 600;
    var s = Math.floor(rest / 10);
    var t = rest % 10;
    return pad2(minutes) + ':' + pad2(s) + '.' + t;
  }

  /** Elapsed time for the status line: 42 -> "0:42", 125 -> "2:05". */
  function formatElapsed(sec) {
    if (!isFiniteNumber(sec) || sec < 0) sec = 0;
    sec = Math.floor(sec);
    return Math.floor(sec / 60) + ':' + pad2(sec % 60);
  }

  /** Processing time: 12.34 -> "12,3 с", 75 -> "1 мин 15 с". */
  function formatDuration(sec) {
    if (!isFiniteNumber(sec) || sec < 0) return '';
    if (sec < 60) return sec.toFixed(1).replace('.', ',') + ' с';
    var m = Math.floor(sec / 60);
    var s = Math.round(sec - m * 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ' мин ' + s + ' с';
  }

  /** 29.4 MB style sizes with a Russian decimal comma. */
  function formatBytes(bytes) {
    if (!isFiniteNumber(bytes) || bytes < 0) return '';
    var units = ['Б', 'КБ', 'МБ', 'ГБ'];
    var i = 0;
    var v = bytes;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    var str = i === 0 ? String(Math.round(v)) : v.toFixed(v < 10 ? 1 : 0);
    return str.replace('.', ',') + ' ' + units[i];
  }

  function formatPercent(fraction) {
    if (!isFiniteNumber(fraction)) return '';
    var p = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
    return p + '%';
  }

  /** Russian plural: plural(2, ['признак', 'признака', 'признаков']). */
  function plural(n, forms) {
    var n10 = n % 10;
    var n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return forms[0];
    if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return forms[1];
    return forms[2];
  }

  function fileExtension(name) {
    var m = /\.[^./\\]+$/.exec(String(name || ''));
    return m ? m[0].toLowerCase() : '';
  }

  /** Returns null when the file is acceptable, otherwise a user-facing message. */
  function validateFile(file) {
    if (!file) return 'Файл не выбран.';
    var ext = fileExtension(file.name);
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      return 'Формат «' + (ext || 'без расширения') + '» не поддерживается. ' +
        'Загрузите видео в формате .mov или .mp4.';
    }
    if (!file.size) return 'Файл пустой. Выберите другой видеофайл.';
    if (file.size > MAX_FILE_BYTES) {
      return 'Файл слишком большой (' + formatBytes(file.size) + '). ' +
        'Максимальный размер — 300 МБ.';
    }
    return null;
  }

  /** Only http(s) links are rendered, so API data cannot inject javascript: URLs. */
  function safeHttpUrl(url) {
    if (typeof url !== 'string') return null;
    var s = url.trim();
    return /^https?:\/\/[^\s]+$/i.test(s) ? s : null;
  }

  function hostOf(url) {
    var m = /^https?:\/\/([^/:?#]+)/i.exec(url || '');
    return m ? m[1].toLowerCase() : '';
  }

  /** Turns FastAPI-style error bodies into one readable line. */
  function errorDetail(body) {
    if (!body) return '';
    if (typeof body === 'string') return body;
    var d = body.detail !== undefined ? body.detail : body.error;
    if (d === undefined || d === null) return '';
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      return d.map(function (x) { return (x && x.msg) ? x.msg : String(x); }).join('; ');
    }
    if (typeof d === 'object' && d.message) return String(d.message);
    try { return JSON.stringify(d); } catch (e) { return String(d); }
  }

  /** Normalises a "done" job so the UI never has to guard against missing fields. */
  function normalizeResult(job) {
    var list = Array.isArray(job && job.violations) ? job.violations : [];
    var violations = list.filter(Boolean).map(function (v) {
      var frames = Array.isArray(v.evidence_frames) ? v.evidence_frames : [];
      return {
        type: (typeof v.type === 'string' && v.type.trim()) ? v.type : 'Возможное нарушение',
        typeId: typeof v.type_id === 'string' ? v.type_id : null,
        timecode: isFiniteNumber(v.timecode_sec) ? v.timecode_sec : null,
        confidence: isFiniteNumber(v.confidence) ? Math.min(1, Math.max(0, v.confidence)) : null,
        description: typeof v.description === 'string' ? v.description : '',
        rule: (v.rule && typeof v.rule === 'object') ? {
          document: typeof v.rule.document === 'string' ? v.rule.document : '',
          clause: typeof v.rule.clause === 'string' ? v.rule.clause : '',
          quote: typeof v.rule.quote === 'string' ? v.rule.quote : '',
          url: safeHttpUrl(v.rule.url)
        } : null,
        frames: frames.filter(function (f) {
          return f && typeof f.image_base64 === 'string' && f.image_base64.length > 0;
        }).map(function (f) {
          return {
            timestamp: isFiniteNumber(f.timestamp_sec) ? f.timestamp_sec : null,
            src: /^data:image\//.test(f.image_base64)
              ? f.image_base64
              : 'data:image/jpeg;base64,' + f.image_base64.replace(/\s+/g, '')
          };
        })
      };
    });
    violations.sort(function (a, b) {
      var ta = a.timecode === null ? Infinity : a.timecode;
      var tb = b.timecode === null ? Infinity : b.timecode;
      return ta - tb;
    });
    var verdict = job && job.verdict;
    var isViolation = verdict === 'violation' || (verdict !== 'no_violation' && violations.length > 0);
    var scene = job && job.scene;
    var sceneOut = (scene && typeof scene.image_base64 === 'string' && scene.image_base64) ? {
      timestamp: isFiniteNumber(scene.timestamp_sec) ? scene.timestamp_sec : null,
      src: /^data:image\//.test(scene.image_base64)
        ? scene.image_base64
        : 'data:image/jpeg;base64,' + scene.image_base64.replace(/\s+/g, ''),
      labels: (Array.isArray(scene.objects) ? scene.objects : [])
        .map(function (o) { return o && typeof o.label === 'string' ? o.label : null; })
        .filter(function (l, i, arr) { return l && arr.indexOf(l) === i; })
    } : null;
    return {
      jobId: job && job.job_id ? String(job.job_id) : '',
      isViolation: isViolation,
      violations: isViolation ? violations : [],
      processingSec: isFiniteNumber(job && job.processing_sec) ? job.processing_sec : null,
      scene: sceneOut
    };
  }

  var api = {
    MAX_FILE_BYTES: MAX_FILE_BYTES,
    ALLOWED_EXT: ALLOWED_EXT,
    formatTimecode: formatTimecode,
    formatElapsed: formatElapsed,
    formatDuration: formatDuration,
    formatBytes: formatBytes,
    formatPercent: formatPercent,
    plural: plural,
    fileExtension: fileExtension,
    validateFile: validateFile,
    safeHttpUrl: safeHttpUrl,
    hostOf: hostOf,
    errorDetail: errorDetail,
    normalizeResult: normalizeResult
  };

  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Fmt = api;
})(this);

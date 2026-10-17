/* star-player.js — ★18 signal timeline strip under the video player */
(function () {
  'use strict';

  var COLORS = {
    violation: '#e53935',   // red — active violation
    people: '#1976d2',      // blue — people in room
    cash: '#f57c00',        // orange — cash detected
    laptop: '#43a047',      // green — laptop present
    empty: '#dde1e8'        // grey — nothing notable
  };

  function _buildStrip(timeline, duration) {
    if (!Array.isArray(timeline) || !timeline.length || !duration) return null;

    var wrap = document.createElement('div');
    wrap.className = 'sp-timeline-wrap';
    wrap.setAttribute('aria-label', 'Временная шкала сигналов');

    var strip = document.createElement('div');
    strip.className = 'sp-timeline';
    strip.setAttribute('role', 'img');
    strip.setAttribute('aria-hidden', 'true');

    timeline.forEach(function (frame) {
      var pct = (frame.t / duration) * 100;
      var seg = document.createElement('div');
      seg.className = 'sp-seg';
      seg.style.left = pct.toFixed(2) + '%';

      var color = COLORS.empty;
      if (frame.violations && frame.violations.length) {
        color = COLORS.violation;
      } else if (frame.cash) {
        color = COLORS.cash;
      } else if (frame.people > 1) {
        color = COLORS.people;
      } else if (frame.laptop) {
        color = COLORS.laptop;
      }
      seg.style.background = color;
      strip.appendChild(seg);
    });

    var legend = document.createElement('div');
    legend.className = 'sp-legend';
    [
      [COLORS.violation, 'Нарушение'],
      [COLORS.cash,      'Наличные'],
      [COLORS.people,    '≥2 человека'],
      [COLORS.laptop,    'Ноутбук'],
    ].forEach(function (entry) {
      var item = document.createElement('span');
      item.className = 'sp-legend-item';
      var dot = document.createElement('span');
      dot.className = 'sp-legend-dot';
      dot.style.background = entry[0];
      item.appendChild(dot);
      item.appendChild(document.createTextNode(entry[1]));
      legend.appendChild(item);
    });

    wrap.appendChild(strip);
    wrap.appendChild(legend);
    return wrap;
  }

  function _attach(result, videoEl) {
    var tl = result && result.timeline;
    var dur = result && result.videoDurationSec;
    if (!tl || !dur) return;

    var videoWrap = document.getElementById('video-wrap');
    if (!videoWrap) return;

    // Remove any previous strip
    var old = document.getElementById('sp-timeline-wrap');
    if (old) old.remove();

    var strip = _buildStrip(tl, dur);
    if (!strip) return;
    strip.id = 'sp-timeline-wrap';

    // Insert after video-wrap
    if (videoWrap.nextSibling) {
      videoWrap.parentNode.insertBefore(strip, videoWrap.nextSibling);
    } else {
      videoWrap.parentNode.appendChild(strip);
    }

    // Clicking the strip seeks the video
    if (videoEl) {
      strip.querySelector('.sp-timeline').addEventListener('click', function (e) {
        var rect = this.getBoundingClientRect();
        var frac = (e.clientX - rect.left) / rect.width;
        try { videoEl.currentTime = Math.max(0, frac * dur); } catch (ex) { /* ignore */ }
      });
    }
  }

  /* ---- ★8 "What the system sees" trajectory + quality overlay ----------- */

  function _showSystemView(result) {
    // Trajectory map
    var tmap = result && result.trajectoryMap;
    var existingTraj = document.getElementById('sp-traj-card');
    if (existingTraj) existingTraj.remove();

    if (tmap && tmap.src) {
      var card = document.createElement('details');
      card.id = 'sp-traj-card';
      card.className = 'sp-traj-card checks-card'; // reuse existing card styles
      var summary = document.createElement('summary');
      summary.textContent = 'Карта передвижений';
      card.appendChild(summary);
      var note = document.createElement('p');
      note.className = 'scene-note';
      note.textContent = 'Траектории движения людей за весь период видеозаписи.';
      card.appendChild(note);
      var img = document.createElement('img');
      img.className = 'scene-img';
      img.src = tmap.src;
      img.alt = 'Карта передвижений';
      card.appendChild(img);
      var checksCard = document.getElementById('checks-card');
      if (checksCard && checksCard.parentNode) {
        checksCard.parentNode.insertBefore(card, checksCard.nextSibling);
      }
    }

    // Quality warnings
    var quality = result && result.quality;
    var existingQw = document.getElementById('sp-quality-warn');
    if (existingQw) existingQw.remove();

    if (quality && !quality.ok && quality.issues && quality.issues.length) {
      var warn = document.createElement('div');
      warn.id = 'sp-quality-warn';
      warn.className = 'sp-quality-warn';
      var warnTitle = document.createElement('strong');
      warnTitle.textContent = 'Качество видео: ';
      warn.appendChild(warnTitle);
      quality.issues.forEach(function (issue, i) {
        if (i) warn.appendChild(document.createTextNode('; '));
        var span = document.createElement('span');
        span.className = 'sp-quality-issue sp-quality-issue--' + issue.severity;
        span.textContent = issue.label;
        warn.appendChild(span);
      });
      var verdict = document.getElementById('verdict');
      if (verdict && verdict.parentNode) {
        verdict.parentNode.insertBefore(warn, verdict.nextSibling);
      }
    }
  }

  function _normalizeResult(result) {
    if (!result) return result;
    // Ensure trajectory_map uses data URI src (mirrors how scene.src is handled)
    var tm = result.trajectoryMap || (result.trajectory_map && (
      result.trajectoryMap = {
        src: /^data:image\//.test(result.trajectory_map.image_base64)
          ? result.trajectory_map.image_base64
          : 'data:image/jpeg;base64,' + result.trajectory_map.image_base64,
        timestamp: result.trajectory_map.timestamp_sec || null
      }
    ));
    return result;
  }

  // Hook into StarBasic.attach if star-basic.js is present, otherwise
  // use a MutationObserver fallback.
  var _origAttach = window.StarBasic && window.StarBasic.attach;
  if (_origAttach) {
    window.StarBasic.attach = function (opts) {
      _origAttach.call(window.StarBasic, opts);
      _normalizeResult(opts.result);
      _attach(opts.result, opts.video);
      _showSystemView(opts.result);
    };
  } else {
    document.addEventListener('app:result', function (e) {
      var r = e.detail && e.detail.result;
      _normalizeResult(r);
      _attach(r, document.getElementById('video'));
      _showSystemView(r);
    });
  }
})();

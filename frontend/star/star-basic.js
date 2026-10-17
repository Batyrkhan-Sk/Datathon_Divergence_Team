/* star-basic.js — ★19 savings line, ★14 risk badges, ★17 keyboard shortcuts */
(function () {
  'use strict';

  var _state = null;   // { result, video, cardsRoot, bannerEl }
  var _activeIdx = -1;

  /* ---- ★19 Time savings ------------------------------------------------- */

  function _pluralMin(n) {
    var n10 = n % 10, n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return 'минута';
    if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return 'минуты';
    return 'минут';
  }

  function _showSavings(result) {
    var dur = result.videoDurationSec;
    var proc = result.processingSec;
    if (!dur || dur <= 0) return;
    var savedSec = dur - (proc || 0);
    var savedMin = Math.round(savedSec / 60);
    if (savedMin <= 0) return;

    var existing = document.getElementById('sb-savings');
    if (existing) existing.remove();

    var p = document.createElement('p');
    p.id = 'sb-savings';
    p.className = 'sb-savings';
    p.textContent = 'Сэкономлено ~' + savedMin + ' ' + _pluralMin(savedMin) + ' ручного просмотра';

    var banner = _state.bannerEl;
    if (banner && banner.parentNode) {
      banner.parentNode.insertBefore(p, banner.nextSibling);
    }
  }

  /* ---- ★14 Risk level badges -------------------------------------------- */

  var RISK_LABEL = {
    high: 'Высокий риск',
    medium: 'Средний риск',
    low: 'Низкий риск'
  };

  function _showRiskBadges(result) {
    (result.violations || []).forEach(function (v, i) {
      if (!v.riskLevel) return;
      var card = document.getElementById('finding-' + (i + 1));
      if (!card) return;
      var head = card.querySelector('.finding-head');
      if (!head || head.querySelector('.sb-risk')) return; // already added
      var badge = document.createElement('span');
      badge.className = 'sb-risk sb-risk--' + v.riskLevel;
      badge.textContent = RISK_LABEL[v.riskLevel] || v.riskLevel;
      head.appendChild(badge);
    });
  }

  /* ---- ★17 Keyboard shortcuts -------------------------------------------- */

  var SHORTCUTS = [
    ['J', 'Следующий эпизод'],
    ['K', 'Предыдущий эпизод'],
    ['Space', 'Пауза / воспроизведение'],
    ['F', 'Полноэкранный режим'],
    ['?', 'Показать / скрыть справку']
  ];

  function _countCards() {
    var root = _state && _state.cardsRoot;
    return root ? root.querySelectorAll('.finding').length : 0;
  }

  function _goCard(delta) {
    var n = _countCards();
    if (!n) return;
    _activeIdx = (_activeIdx + delta + n) % n;
    var card = document.getElementById('finding-' + (_activeIdx + 1));
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    var btn = card.querySelector('.timecode-btn');
    if (btn && !btn.disabled) btn.focus();
  }

  function _helpVisible() {
    return !!document.getElementById('sb-help-overlay');
  }

  function _toggleHelp() {
    var el = document.getElementById('sb-help-overlay');
    if (el) { el.remove(); return; }

    var overlay = document.createElement('div');
    overlay.id = 'sb-help-overlay';
    overlay.className = 'sb-help-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Горячие клавиши');

    var box = document.createElement('div');
    box.className = 'sb-help-box';

    var h2 = document.createElement('h2');
    h2.textContent = 'Горячие клавиши';
    box.appendChild(h2);

    var tbl = document.createElement('table');
    SHORTCUTS.forEach(function (row) {
      var tr = document.createElement('tr');
      var td1 = document.createElement('td');
      var kbd = document.createElement('kbd');
      kbd.textContent = row[0];
      td1.appendChild(kbd);
      var td2 = document.createElement('td');
      td2.textContent = row[1];
      tr.appendChild(td1);
      tr.appendChild(td2);
      tbl.appendChild(tr);
    });
    box.appendChild(tbl);

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'sb-help-close';
    closeBtn.textContent = 'Закрыть (Esc)';
    closeBtn.addEventListener('click', _toggleHelp);
    box.appendChild(closeBtn);

    overlay.appendChild(box);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) _toggleHelp();
    });
    document.body.appendChild(overlay);
    closeBtn.focus();
  }

  function _onKey(e) {
    // Skip when a native dialog is open (lightbox) — except for ? and Escape
    var nativeDialog = !!document.querySelector('dialog[open]');
    // Skip when typing in a form field
    var tag = (e.target || {}).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target || {}).isContentEditable) return;

    var v = _state && _state.video;

    if (e.key === 'Escape') {
      if (_helpVisible()) { e.preventDefault(); _toggleHelp(); }
      return;
    }
    if (e.key === '?') {
      e.preventDefault();
      _toggleHelp();
      return;
    }

    if (!_state || nativeDialog) return;

    if (e.key === 'j' || e.key === 'J') {
      e.preventDefault();
      _goCard(1);
    } else if (e.key === 'k' || e.key === 'K') {
      e.preventDefault();
      _goCard(-1);
    } else if (e.key === ' ') {
      if (v && !_helpVisible()) {
        e.preventDefault();
        if (v.paused) {
          var p = v.play();
          if (p && p.catch) p.catch(function () {});
        } else {
          v.pause();
        }
      }
    } else if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      var wrap = document.getElementById('video-wrap');
      if (wrap) {
        if (document.fullscreenElement) {
          document.exitFullscreen && document.exitFullscreen();
        } else {
          wrap.requestFullscreen && wrap.requestFullscreen();
        }
      }
    }
  }

  /* ---- Public API -------------------------------------------------------- */

  window.StarBasic = {
    attach: function (opts) {
      // opts: { result, video, cardsRoot, bannerEl }
      _state = opts;
      _activeIdx = -1;
      _showSavings(opts.result);
      _showRiskBadges(opts.result);
    }
  };

  document.addEventListener('keydown', _onKey);
})();

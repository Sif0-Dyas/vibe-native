/* Library tab — a searchable, sortable, groupable text list of EVERY analyzed track.
   Columns are user-choosable (right-click a header or the "columns" button, Windows-
   style); rows can be grouped into collapsible sections (Genre / Key / Camelot / BPM
   range / Artist). Preferences persist in localStorage. Clicking a row loads that
   track into the List via window.loadTrackByHash (app.js). Self-contained IIFE. */
(function () {
  var LIB = null;                 // cached full library ([] of lean track records)
  var wired = false, colMenu = null;

  // Every available column. `w` is its CSS grid width; `num` marks numeric sorts.
  var COLS = [
    { key: 'title', label: 'Title', w: 'minmax(150px,1fr)' },
    { key: 'artist', label: 'Artist', w: '160px' },
    { key: 'style', label: 'Genre', w: '150px' },
    { key: 'bpm', label: 'BPM', w: '62px', num: true },
    { key: 'key', label: 'Key', w: '80px' },
    { key: 'camelot', label: 'Camelot', w: '72px' },
    { key: 'duration', label: 'Length', w: '70px', num: true },
    { key: 'created', label: 'Added', w: '112px', num: true }
  ];
  var COLMAP = {}; COLS.forEach(function (c) { COLMAP[c.key] = c; });

  var state = loadState();
  var els = {};

  function loadState() {
    var d = { cols: ['title', 'style', 'bpm', 'key'], sortKey: 'title', sortDesc: false, group: '', collapsed: {} };
    try {
      var s = JSON.parse(localStorage.getItem('vibeLibraryState'));
      if (s && Array.isArray(s.cols)) {
        d.cols = s.cols.filter(function (k) { return COLMAP[k]; });
        if (d.cols.indexOf('title') === -1) d.cols.unshift('title');
        if (s.sortKey && COLMAP[s.sortKey]) d.sortKey = s.sortKey;
        d.sortDesc = !!s.sortDesc;
        d.group = s.group || '';
        d.collapsed = s.collapsed || {};
      }
    } catch (_) { /* defaults */ }
    return d;
  }
  function persist() { try { localStorage.setItem('vibeLibraryState', JSON.stringify(state)); } catch (_) { /* ignore */ } }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function keyOf(t) { return t.key == null ? '' : t.key + (t.scale === 'minor' ? 'm' : ''); }
  function fmtDur(s) {
    if (s == null) return '';
    s = Math.round(s); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }
  function fmtDate(ts) {
    if (!ts) return '';
    try { return new Date(ts * 1000).toISOString().slice(0, 10); } catch (_) { return ''; }
  }

  // display value for a cell / comparable value for sorting
  function cell(t, key) {
    if (key === 'key') return keyOf(t) || '—';
    if (key === 'duration') return fmtDur(t.duration) || '—';
    if (key === 'created') return fmtDate(t.created) || '—';
    if (key === 'bpm') return t.bpm != null ? t.bpm : '—';
    return t[key] || '—';
  }
  function sortVal(t, key) {
    if (COLMAP[key] && COLMAP[key].num) return (key === 'key' ? 0 : (t[key] || 0));
    if (key === 'key') return keyOf(t).toLowerCase();
    return String(t[key] || '').toLowerCase();
  }
  function groupVal(t, g) {
    if (g === 'bpmband') return t.bpm == null ? null : Math.floor(t.bpm / 10) * 10;
    if (g === 'key') return keyOf(t);
    return t[g] || '';
  }
  function groupLabel(g, v) {
    if (g === 'bpmband') return v == null ? 'no BPM' : v + '–' + (v + 9) + ' BPM';
    return (v === '' || v == null) ? '(none)' : v;
  }

  function render() {
    if (!LIB) return;
    var q = (els.search.value || '').trim().toLowerCase();
    var list = LIB;
    if (q) {
      list = LIB.filter(function (t) {
        return (t.title || '').toLowerCase().indexOf(q) !== -1 ||
          (t.artist || '').toLowerCase().indexOf(q) !== -1 ||
          (t.style || '').toLowerCase().indexOf(q) !== -1 ||
          keyOf(t).toLowerCase().indexOf(q) !== -1 ||
          (t.camelot || '').toLowerCase().indexOf(q) !== -1;
      });
    }
    var dir = state.sortDesc ? -1 : 1;
    var g = state.group;
    list = list.slice().sort(function (a, b) {
      if (g) {                                  // group order first (always ascending)
        var ga = groupVal(a, g), gb = groupVal(b, g);
        if (g === 'bpmband') { var na = ga == null ? 1e9 : ga, nb = gb == null ? 1e9 : gb; if (na !== nb) return na - nb; }
        else { ga = String(ga).toLowerCase(); gb = String(gb).toLowerCase(); if (ga !== gb) return ga < gb ? -1 : 1; }
      }
      var av = sortVal(a, state.sortKey), bv = sortVal(b, state.sortKey);
      if (typeof av === 'number') return (av - bv) * dir;
      return av < bv ? -dir : av > bv ? dir : 0;
    });

    // header + grid template (from the visible columns)
    els.view.style.setProperty('--lib-grid', state.cols.map(function (k) { return COLMAP[k].w; }).join(' '));
    els.head.innerHTML = state.cols.map(function (k) {
      var sorted = k === state.sortKey ? (state.sortDesc ? ' sorted desc' : ' sorted') : '';
      return '<span data-sort="' + k + '" class="' + sorted.trim() + '">' + esc(COLMAP[k].label) + '</span>';
    }).join('');

    els.count.textContent = list.length + (list.length === 1 ? ' track' : ' tracks') + (q ? ' (of ' + LIB.length + ')' : '');
    if (els.sort) els.sort.value = state.sortKey;
    if (els.dir) els.dir.innerHTML = state.sortDesc ? '&#9660;' : '&#9650;';

    if (!list.length) {
      els.rows.innerHTML = '<div class="lib-empty">no tracks' + (q ? ' match “' + esc(q) + '”' : ' in your library yet — analyze some music') + '</div>';
      return;
    }

    var html = '', curG = null, open = false;
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      if (g) {
        var gv = groupVal(t, g), lbl = groupLabel(g, gv);
        if (lbl !== curG) {
          if (open) html += '</div></div>';   // close previous group's rows + its .lib-grp wrapper
          curG = lbl;
          var col = !!state.collapsed[lbl];
          // count members of this group
          var n = 0; for (var j = i; j < list.length && groupLabel(g, groupVal(list[j], g)) === lbl; j++) n++;
          html += '<div class="lib-grp' + (col ? ' collapsed' : '') + '" data-g="' + esc(lbl) + '">' +
            '<div class="lib-group"><span class="arw">▾</span><span class="gname">' + esc(lbl) + '</span>' +
            '<span class="gc">' + n + '</span></div><div class="lib-grp-rows">';
          open = true;
        }
      }
      html += '<div class="lib-row" data-hash="' + esc(t.hash) + '">' +
        state.cols.map(function (k) {
          var cls = COLMAP[k].num ? ' lc-num' : '';
          return '<span class="lc' + cls + '" title="' + esc(cell(t, k)) + '">' + esc(cell(t, k)) + '</span>';
        }).join('') + '</div>';
    }
    if (open) html += '</div></div>';   // close the final group's rows + .lib-grp wrapper
    els.rows.innerHTML = html;
  }

  // ---- column chooser (right-click a header, or the "columns" button) ----
  function closeColMenu() {
    if (colMenu) { colMenu.remove(); colMenu = null; document.removeEventListener('mousedown', onDocDown, true); }
  }
  function onDocDown(e) { if (colMenu && !colMenu.contains(e.target)) closeColMenu(); }
  function showColMenu(x, y) {
    closeColMenu();
    var m = document.createElement('div'); m.className = 'lib-colmenu';
    m.innerHTML = '<div class="lib-colmenu-t">Columns</div>' + COLS.map(function (c) {
      var on = state.cols.indexOf(c.key) !== -1, lock = c.key === 'title';
      return '<label class="' + (lock ? 'dis' : '') + '"><input type="checkbox" data-col="' + c.key + '"' +
        (on ? ' checked' : '') + (lock ? ' disabled' : '') + '> ' + esc(c.label) + '</label>';
    }).join('');
    document.body.appendChild(m);
    var r = m.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 6)) + 'px';
    m.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 6)) + 'px';
    m.addEventListener('change', function (e) {
      var cb = e.target; if (!cb.dataset || !cb.dataset.col) return;
      var k = cb.dataset.col;
      if (cb.checked) { if (state.cols.indexOf(k) === -1) state.cols.push(k); }
      else state.cols = state.cols.filter(function (x2) { return x2 !== k; });
      state.cols = COLS.map(function (c) { return c.key; }).filter(function (c) { return state.cols.indexOf(c) !== -1; });
      persist(); render();  // the sort key stays even if its column is hidden
    });
    colMenu = m;
    setTimeout(function () { document.addEventListener('mousedown', onDocDown, true); }, 0);
  }

  function load(force) {
    if (LIB && !force) { render(); return; }
    els.rows.innerHTML = '<div class="lib-empty">loading library…</div>';
    fetch('/library').then(function (r) { return r.json(); }).then(function (data) {
      LIB = data || []; render();
    }).catch(function () { els.rows.innerHTML = '<div class="lib-empty">failed to load the library</div>'; });
  }

  function exportTxt() {
    if (!LIB) return;
    var cols = state.cols;
    var lines = LIB.map(function (t) { return cols.map(function (k) { return cell(t, k); }).join('\t'); });
    lines.unshift(cols.map(function (k) { return COLMAP[k].label; }).join('\t'));
    var blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'vibe-library.txt'; a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function wire() {
    if (wired) return;
    els = {
      view: document.getElementById('library-view'), search: document.getElementById('lib-search'),
      rows: document.getElementById('lib-rows'), head: document.getElementById('lib-head'),
      count: document.getElementById('lib-count'), sort: document.getElementById('lib-sort'),
      dir: document.getElementById('lib-dir'), group: document.getElementById('lib-group'),
      cols: document.getElementById('lib-cols')
    };
    if (!els.rows) return;
    wired = true;

    // populate the sort dropdown from the column list
    els.sort.innerHTML = COLS.map(function (c) { return '<option value="' + c.key + '">' + esc(c.label) + '</option>'; }).join('');
    els.sort.value = state.sortKey;
    els.group.value = state.group;

    els.search.addEventListener('input', render);
    els.sort.addEventListener('change', function () {
      if (els.sort.value === state.sortKey) return;
      state.sortKey = els.sort.value; state.sortDesc = (state.sortKey === 'created'); persist(); render();
    });
    els.dir.addEventListener('click', function () { state.sortDesc = !state.sortDesc; persist(); render(); });
    els.group.addEventListener('change', function () { state.group = els.group.value; persist(); render(); });

    // click a header to sort; right-click for the column chooser
    els.head.addEventListener('click', function (e) {
      var s = e.target.closest('span[data-sort]'); if (!s) return;
      var k = s.dataset.sort;
      if (k === state.sortKey) state.sortDesc = !state.sortDesc; else { state.sortKey = k; state.sortDesc = false; }
      persist(); render();
    });
    els.head.addEventListener('contextmenu', function (e) { e.preventDefault(); showColMenu(e.clientX, e.clientY); });
    els.cols.addEventListener('click', function (e) {
      var r = e.target.getBoundingClientRect(); showColMenu(r.left, r.bottom + 4);
    });

    // collapse/expand a group by clicking its header
    els.rows.addEventListener('click', function (e) {
      var gh = e.target.closest('.lib-group');
      if (gh) {
        var grp = gh.parentElement, lbl = grp.dataset.g;
        var nowCol = !grp.classList.contains('collapsed');
        grp.classList.toggle('collapsed', nowCol);
        if (nowCol) state.collapsed[lbl] = 1; else delete state.collapsed[lbl];
        persist(); return;
      }
      var row = e.target.closest('.lib-row'); if (!row) return;
      if (window.loadTrackByHash) {
        window.loadTrackByHash(row.dataset.hash);
        var listTab = document.querySelector('.tab[data-view="list"]'); if (listTab) listTab.click();
      }
    });

    document.getElementById('lib-refresh').addEventListener('click', function () { load(true); });
    document.getElementById('lib-export').addEventListener('click', exportTxt);
  }

  // Called by map.js's switchTo() when the Library tab is opened.
  window.vibeLoadLibrary = function () { wire(); load(false); };
})();

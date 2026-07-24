/* Library tab — a searchable, sortable text list of EVERY analyzed track in the DB.
   Loaded once from /library (cached in memory); clicking a row loads that track into
   the List view via window.loadTrackByHash (defined in app.js). Self-contained IIFE. */
(function () {
  var LIB = null;                 // cached full library ([] of lean track records)
  var sortKey = 'title', sortDesc = false;
  var searchEl, rowsEl, countEl, headEl, sortEl, dirEl, wired = false;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function keyOf(t) {
    if (t.key == null) return '';
    return t.key + (t.scale === 'minor' ? 'm' : '');
  }

  function render() {
    if (!LIB) return;
    var q = (searchEl.value || '').trim().toLowerCase();
    var list = LIB;
    if (q) {
      list = LIB.filter(function (t) {
        return (t.title || '').toLowerCase().indexOf(q) !== -1 ||
          (t.style || '').toLowerCase().indexOf(q) !== -1 ||
          keyOf(t).toLowerCase().indexOf(q) !== -1 ||
          (t.camelot || '').toLowerCase().indexOf(q) !== -1;
      });
    }
    var dir = sortDesc ? -1 : 1;
    list = list.slice().sort(function (a, b) {
      var av, bv;
      if (sortKey === 'bpm') { return ((a.bpm || 0) - (b.bpm || 0)) * dir; }
      if (sortKey === 'created') { return ((a.created || 0) - (b.created || 0)) * dir; }
      if (sortKey === 'key') { av = keyOf(a); bv = keyOf(b); }
      else if (sortKey === 'style') { av = (a.style || '').toLowerCase(); bv = (b.style || '').toLowerCase(); }
      else { av = (a.title || '').toLowerCase(); bv = (b.title || '').toLowerCase(); }
      return av < bv ? -dir : av > bv ? dir : 0;
    });

    countEl.textContent = list.length + (list.length === 1 ? ' track' : ' tracks') +
      (q ? ' (of ' + LIB.length + ')' : '');
    // keep the header indicators + the explicit sort control in sync
    headEl.querySelectorAll('span').forEach(function (s) {
      s.classList.toggle('sorted', s.dataset.sort === sortKey);
      s.classList.toggle('desc', s.dataset.sort === sortKey && sortDesc);
    });
    if (sortEl) sortEl.value = sortKey;
    if (dirEl) dirEl.innerHTML = sortDesc ? '&#9660;' : '&#9650;';

    if (!list.length) {
      rowsEl.innerHTML = '<div class="lib-empty">no tracks' +
        (q ? ' match “' + esc(q) + '”' : ' in your library yet — analyze some music') + '</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      html += '<div class="lib-row" data-hash="' + esc(t.hash) + '">' +
        '<span class="lt" title="' + esc(t.title) + '">' + esc(t.title) + '</span>' +
        '<span class="lg">' + esc(t.style || '—') + '</span>' +
        '<span class="lb">' + (t.bpm != null ? t.bpm : '—') + '</span>' +
        '<span class="lk">' + (keyOf(t) || '—') + (t.camelot ? ' · ' + esc(t.camelot) : '') + '</span>' +
        '</div>';
    }
    rowsEl.innerHTML = html;
  }

  function load(force) {
    if (LIB && !force) { render(); return; }
    rowsEl.innerHTML = '<div class="lib-empty">loading library…</div>';
    fetch('/library').then(function (r) { return r.json(); }).then(function (data) {
      LIB = data || [];
      render();
    }).catch(function () {
      rowsEl.innerHTML = '<div class="lib-empty">failed to load the library</div>';
    });
  }

  function exportTxt() {
    if (!LIB) return;
    var lines = LIB.map(function (t) {
      return [t.title, t.style || '', t.bpm != null ? t.bpm : '', keyOf(t), t.camelot || ''].join('\t');
    });
    lines.unshift(['Title', 'Genre', 'BPM', 'Key', 'Camelot'].join('\t'));
    var blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'vibe-library.txt';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function wire() {
    if (wired) return;
    searchEl = document.getElementById('lib-search');
    rowsEl = document.getElementById('lib-rows');
    countEl = document.getElementById('lib-count');
    headEl = document.querySelector('.lib-head');
    sortEl = document.getElementById('lib-sort');
    dirEl = document.getElementById('lib-dir');
    if (!rowsEl) return;
    wired = true;
    searchEl.addEventListener('input', render);
    headEl.addEventListener('click', function (e) {
      var s = e.target.closest('span[data-sort]'); if (!s) return;
      var k = s.dataset.sort;
      if (k === sortKey) sortDesc = !sortDesc; else { sortKey = k; sortDesc = false; }
      render();
    });
    if (sortEl) sortEl.addEventListener('change', function () {
      if (sortEl.value === sortKey) return;
      sortKey = sortEl.value; sortDesc = (sortKey === 'created');   // newest-first default for dates
      render();
    });
    if (dirEl) dirEl.addEventListener('click', function () { sortDesc = !sortDesc; render(); });
    rowsEl.addEventListener('click', function (e) {
      var r = e.target.closest('.lib-row'); if (!r) return;
      if (window.loadTrackByHash) {
        window.loadTrackByHash(r.dataset.hash);
        var listTab = document.querySelector('.tab[data-view="list"]');
        if (listTab) listTab.click();
      }
    });
    document.getElementById('lib-refresh').addEventListener('click', function () { load(true); });
    document.getElementById('lib-export').addEventListener('click', exportTxt);
  }

  // Called by map.js's switchTo() when the Library tab is opened.
  window.vibeLoadLibrary = function () { wire(); load(false); };
})();

/* Options tab — app status (version, DB, ffmpeg, GPU) + quick links to the manage
   panels. Fetches /status and renders it. Self-contained IIFE. */
(function () {
  var body;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function row(k, vHtml) {
    return '<div class="opt-row"><span class="k">' + esc(k) + '</span><span class="v">' + vHtml + '</span></div>';
  }
  function badge(ok, text) {
    return '<span class="opt-badge ' + (ok ? 'ok' : 'warn') + '">' + esc(text) + '</span>';
  }

  function render(s) {
    var gpuText = s.provider || (s.gpu_available ? 'DirectML available' : 'CPU only');
    var gpuOk = /Dml/i.test(s.provider || '') || s.gpu_available;
    body.innerHTML =
      '<div class="opt-card"><h3>About</h3>' +
        row('Version', esc(s.version)) +
        row('Tracks in library', s.tracks) +
      '</div>' +
      '<div class="opt-card"><h3>Engine</h3>' +
        row('GPU acceleration', badge(gpuOk, gpuText)) +
        row('ffmpeg (audio decode)', badge(s.ffmpeg, s.ffmpeg ? 'installed' : 'missing')) +
        (s.ffmpeg_path ? '<div class="opt-note">' + esc(s.ffmpeg_path) + '</div>' : '') +
      '</div>' +
      '<div class="opt-card"><h3>Database</h3>' +
        row('Location', esc(s.db_path)) +
        '<div class="opt-note">Your library, vibes, tags, and saved playlists all live in ' +
        'this file. Set the <b>GENRE_DB</b> environment variable to point elsewhere.</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Manage</h3>' +
        '<div class="opt-actions">' +
          '<button data-act="library">&#8803; Browse library</button>' +
          '<button data-act="vibes">&#9672; Vibes</button>' +
          '<button data-act="playlist">&#9776; Playlists</button>' +
          '<button data-act="guide">&#9432; User guide</button>' +
        '</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Appearance</h3>' +
        '<div class="opt-note">Light mode is planned for a future update; the app is ' +
        'dark-themed for now.</div>' +
      '</div>';
    body.querySelectorAll('.opt-actions button').forEach(function (b) {
      b.onclick = function () { act(b.dataset.act); };
    });
  }

  function act(a) {
    if (a === 'vibes') { var vb = document.getElementById('vibe-btn'); if (vb) vb.click(); return; }
    if (a === 'playlist') { var pb = document.querySelector('.pl-open'); if (pb) pb.click(); return; }
    var tab = document.querySelector('.tab[data-view="' + a + '"]');   // library / guide
    if (tab) tab.click();
  }

  // Called by map.js's switchTo() when the Options tab is opened.
  window.vibeLoadOptions = function () {
    body = document.getElementById('opt-body');
    if (!body) return;
    body.innerHTML = 'Loading…';
    fetch('/status').then(function (r) { return r.json(); }).then(render).catch(function () {
      body.innerHTML = '<div class="opt-card">Could not load status.</div>';
    });
  };
})();

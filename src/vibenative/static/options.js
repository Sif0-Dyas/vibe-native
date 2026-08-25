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
        row('Location', pathLink('db', s.db_path)) +
        '<div class="opt-actions">' +
          '<button data-reveal="db">&#128193; Open location</button>' +
          '<button data-edit="db">&#9998; Change&hellip;</button>' +
        '</div>' +
        '<div class="opt-edit" id="db-edit" hidden>' +
          '<input type="text" id="db-edit-in" class="opt-input" spellcheck="false" ' +
            'value="' + esc(s.db_path) + '">' +
          '<button id="db-edit-save">save</button>' +
          '<button id="db-edit-cancel">&#10005;</button>' +
        '</div>' +
        '<div class="opt-note" id="db-msg">Your library, vibes, tags, and saved playlists all ' +
        'live in this file. Changing it records the choice and takes effect on the next ' +
        'start &mdash; it does not move the existing database. <b>GENRE_DB</b>, if set, ' +
        'overrides this.</div>' +
      '</div>' +
      (s.log_path ?
        '<div class="opt-card"><h3>Diagnostics</h3>' +
          row('Log file', pathLink('log', s.log_path)) +
          '<div class="opt-actions"><button data-reveal="log">&#128193; Open location</button></div>' +
          '<div class="opt-note">Activity and errors are written here (the previous ' +
          'session is kept alongside as <b>.prev</b>). If something crashes, this file ' +
          'shows what it was doing right before.</div>' +
        '</div>' : '') +
      '<div class="opt-card"><h3>Music file paths</h3>' +
        '<div class="opt-row"><span class="k">Status</span>' +
          '<span class="v" id="fp-stat">checking&hellip;</span></div>' +
        '<div class="opt-note">A track needs a file path for preview, waveforms and ' +
        'Rekordbox export. Drag-and-dropped tracks never got one. Point this at a music ' +
        'folder and it reconnects them by matching audio content &mdash; it never ' +
        're-analyses, and never changes a genre.</div>' +
        '<div class="opt-edit">' +
          '<input type="text" id="fp-folder" class="opt-input" spellcheck="false" ' +
            'placeholder="C:\\Users\\you\\Music  (or a drive, e.g. G:\\)">' +
          '<button id="fp-check">check</button>' +
          '<button id="fp-apply" disabled>repair</button>' +
        '</div>' +
        '<div class="opt-note" id="fp-msg"></div>' +
      '</div>' +
      '<div class="opt-card"><h3>Appearance</h3>' +
        '<div class="opt-note">Light mode is planned for a future update; the app is ' +
        'dark-themed for now.</div>' +
      '</div>';

    body.querySelectorAll('[data-reveal]').forEach(function (b) {
      b.onclick = function () { reveal(b.dataset.reveal); };
    });
    body.querySelectorAll('.opt-path').forEach(function (a) {
      a.onclick = function () { reveal(a.dataset.reveal); };
    });
    wireDbEdit();
    wireFilePaths();
  }

  /* Music file paths: audit on open, then dry-run "check" before any write.
     Repair stays disabled until a check has reported something to do, so the
     destructive-looking button can never fire on an unexamined folder. */
  function wireFilePaths() {
    var folder = document.getElementById('fp-folder');
    var check = document.getElementById('fp-check');
    var apply = document.getElementById('fp-apply');
    if (!folder || !check || !apply) return;

    fetch('/filepaths/audit').then(function (r) { return r.json(); }).then(function (a) {
      var el = document.getElementById('fp-stat');
      if (!el) return;
      var bits = [a.ok + ' linked'];
      if (a.missing) bits.push(a.missing + ' with no path');
      if (a.broken) bits.push(a.broken + ' broken');
      el.textContent = bits.join(' · ');
    }).catch(function () {
      var el = document.getElementById('fp-stat'); if (el) el.textContent = 'unavailable';
    });

    // Hashing reads every file, so a whole-drive scan is minutes. Count first
    // (a cheap directory walk) and make the user confirm anything large, rather
    // than leaving them staring at a button that looks frozen.
    var BIG = 3000;
    var confirmedFor = '';

    function preflight(v) {
      return fetch('/filepaths/count', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: v })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { note('fp-msg', j.error, true); return false; }
        if (j.audio_files > BIG && confirmedFor !== v) {
          confirmedFor = v;
          var mins = Math.max(1, Math.round(j.estimated_seconds / 60));
          note('fp-msg', j.audio_files.toLocaleString() + ' audio files — roughly ' + mins +
            ' min to hash. Click check again to go ahead, or point at a narrower folder.', true);
          return false;
        }
        return true;
      });
    }

    function run(doApply) {
      var v = folder.value.trim();
      if (!v) { note('fp-msg', 'enter a folder to scan', true); return; }
      if (!doApply) {
        preflight(v).then(function (go) { if (go) doRun(v, false); });
        return;
      }
      doRun(v, true);
    }

    function doRun(v, doApply) {
      note('fp-msg', doApply ? 'repairing…' : 'hashing files…');
      fetch('/filepaths/repair', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: v, apply: !!doApply })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { note('fp-msg', j.error, true); apply.disabled = true; return; }
        var todo = (j.filled || 0) + (j.repointed || 0);
        var msg = 'scanned ' + j.audio_files_scanned + ' files · ' +
          (doApply ? 'reconnected ' : 'can reconnect ') + todo +
          ' (' + j.already_ok + ' already fine, ' + j.unanalysed_files + ' not in your library)';
        note('fp-msg', msg, false);
        apply.disabled = doApply || todo === 0;
        if (doApply) window.vibeLoadOptions();     // refresh the status line
      }).catch(function () { note('fp-msg', 'scan failed', true); });
    }
    check.onclick = function () { run(false); };
    apply.onclick = function () { run(true); };
    folder.onkeydown = function (e) { if (e.key === 'Enter') run(false); };
  }

  // A path rendered as a click target that opens its folder.
  function pathLink(what, p) {
    return '<span class="opt-path" data-reveal="' + esc(what) + '" ' +
      'title="open this folder">' + esc(p) + '</span>';
  }

  function reveal(what) {
    fetch('/reveal', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ what: what })
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.error) note('db-msg', j.error, true);
    }).catch(function () { note('db-msg', 'could not open the folder', true); });
  }

  function note(id, text, bad) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '<b class="' + (bad ? 'opt-bad' : 'opt-good') + '">' + esc(text) + '</b>';
  }

  function wireDbEdit() {
    var edit = document.getElementById('db-edit');
    var btn = body.querySelector('[data-edit="db"]');
    if (!edit || !btn) return;
    btn.onclick = function () {
      edit.hidden = !edit.hidden;
      if (!edit.hidden) { var i = document.getElementById('db-edit-in'); i.focus(); i.select(); }
    };
    document.getElementById('db-edit-cancel').onclick = function () { edit.hidden = true; };
    document.getElementById('db-edit-save').onclick = function () {
      var v = document.getElementById('db-edit-in').value.trim();
      if (!v) return;
      fetch('/db-path', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: v })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { note('db-msg', j.error, true); return; }
        edit.hidden = true;
        note('db-msg', j.exists
          ? 'Saved. Restart the app to use this database.'
          : 'Saved. That file does not exist yet — a new, empty library will be ' +
            'created there on the next start.');
      }).catch(function () { note('db-msg', 'could not save the setting', true); });
    };
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

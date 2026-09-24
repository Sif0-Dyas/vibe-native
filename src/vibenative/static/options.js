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
  /* A segmented choice bound to one preference: [[value, label], ...]. */
  function seg(pref, choices) {
    return '<span class="opt-seg" data-pref="' + esc(pref) + '">' + choices.map(function (c) {
      return '<button data-v="' + esc(c[0]) + '"' + (PREFS[pref] === c[0] ? ' class="on"' : '') +
        '>' + esc(c[1]) + '</button>';
    }).join('') + '</span>';
  }
  /* A slider bound to one numeric preference, with a live readout. */
  function slider(pref, min, max, step, fmt) {
    return '<span class="opt-slide"><input type="range" data-pref="' + esc(pref) + '" min="' + min +
      '" max="' + max + '" step="' + step + '" value="' + esc(PREFS[pref]) + '" data-fmt="' + esc(fmt) +
      '"><i>' + esc(String(PREFS[pref]) + fmt) + '</i></span>';
  }
  function check(pref, label) {
    return '<label class="opt-check"><input type="checkbox" data-pref="' + esc(pref) + '"' +
      (PREFS[pref] ? ' checked' : '') + '><span>' + esc(label) + '</span></label>';
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
        '<div class="opt-row"><span class="k">Theme</span>' +
          '<span class="v">' + seg('theme', THEMES) + '</span></div>' +
        '<div class="opt-note"><b>Neon</b> is the app&rsquo;s own look. <b>Light</b> ' +
        'is for daylight; the others are the same dark layout in a different key. The ' +
        'map&rsquo;s sky stays dark in every theme &mdash; it is a sky.</div>' +
        '<div class="opt-row"><span class="k">Key notation</span>' +
          '<span class="v"><span class="opt-seg" id="keyview">' +
            '<button data-k="both">both</button>' +
            '<button data-k="camelot">Camelot</button>' +
            '<button data-k="musical">musical</button>' +
          '</span></span></div>' +
        '<div class="opt-note"><b>Camelot</b> (8A) is what you mix by; <b>musical</b> ' +
        '(A min) is what you read. Both were always shown together &mdash; fine on one ' +
        'row, noise across a library. Applies to the Analyzer, the map and the exported ' +
        'list. The Library tab keeps its own Key and Camelot columns, which you pick ' +
        'under <b>columns</b>.</div>' +
        '<div class="opt-row"><span class="k">Header</span>' +
          '<span class="v">' + seg('eqStyle', EQ_STYLES) + '</span></div>' +
        '<div class="opt-note">The animation behind the name at the top of the window: a ' +
        'spectrum in four styles, a waveform, a starfield, a record, or nothing.</div>' +
        '<div class="opt-row"><span class="k">Size</span>' +
          '<span class="v">' + slider('uiScale', 70, 150, 5, '%') + '</span></div>' +
        '<div class="opt-note">Scales the whole app. Useful on a small laptop screen or a ' +
        'big monitor across the room.</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Playback</h3>' +
        '<div class="opt-row"><span class="k">Sample length</span>' +
          '<span class="v">' + slider('sampleSeconds', 6, 60, 2, 's') + '</span></div>' +
        '<div class="opt-row"><span class="k">Sample starts at</span>' +
          '<span class="v">' + seg('sampleFrom', [['drop', 'the drop'], ['middle', 'the middle'],
                                                 ['start', 'the beginning']]) + '</span></div>' +
        '<div class="opt-note"><b>The drop</b> is the first sustained loud section &mdash; ' +
        'usually the part you would judge a track by. <b>The middle</b> is 40% in; ' +
        '<b>the beginning</b> is the intro.</div>' +
        check('autoSample', 'Play a sample when you select a star on the map') +
        '<div class="opt-note">Off, the map stays silent until you press play in the ' +
        'track&rsquo;s panel.</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Map</h3>' +
        '<div class="opt-row"><span class="k">Opens on</span>' +
          '<span class="v">' + seg('defaultMap', [['regions', 'regions'], ['universe', 'universe'],
                                                 ['solar', 'solar'], ['tree', 'tree']]) + '</span></div>' +
        '<div class="opt-note">The view the Map tab shows first. A link to a specific ' +
        'view or track still wins.</div>' +
        '<div class="opt-actions"><button id="opt-map-reset">reset map settings</button></div>' +
        '<div class="opt-note" id="opt-map-reset-msg">Puts every map control back to its ' +
        'default &mdash; labels, glow, the Universe and Solar sliders, recoloured genres. ' +
        'Your library, ratings and playlists are untouched.</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Analyzer</h3>' +
        '<div class="opt-row"><span class="k">Overall genre</span>' +
          '<span class="v">' + seg('analyzerIdentity', [['v2', 'weight by energy'], ['v1', 'plain average']]) +
          '</span></div>' +
        '<div class="opt-note">Whether the loudest, most characteristic parts of a track ' +
        'count for more than the quiet ones when deciding its genre.</div>' +
        '<div class="opt-row"><span class="k">Genre over time</span>' +
          '<span class="v">' + seg('analyzerSeg', [['raw', 'every change'], ['hysteresis', 'steady'],
              ['sibling', 'merge similar'], ['family', 'families'], ['hyst+sib', 'steady + merged']]) +
          '</span></div>' +
        '<div class="opt-note">How the coloured genre bands along the waveform are smoothed. ' +
        'These are the defaults for every row; the Analyzer&rsquo;s <b>advanced</b> panel ' +
        'sets the same two, and can override them per track.</div>' +
      '</div>' +
      '<div class="opt-card"><h3>Preferences</h3>' +
        '<div class="opt-actions"><button id="opt-prefs-reset">reset everything to defaults</button></div>' +
        '<div class="opt-note">Every setting on this tab and every remembered view state ' +
        '&mdash; map controls, library columns, the sample volume. Nothing in your ' +
        'library is touched. The app reloads.</div>' +
      '</div>' +
      /* Credits. ffmpeg is LGPL and the genre reference is part CC BY-SA; those
         attributions are owed to whoever runs the app, so they belong in the app
         and not only in the repo. Filled in by loadNotices(). */
      '<div class="opt-card"><h3>Credits and licences</h3>' +
        '<div id="notices">loading&hellip;</div>' +
        '<div class="opt-note">This app is built on the work below. ' +
        'Licence terms are the responsibility of whoever redistributes it.</div>' +
      '</div>';

    body.querySelectorAll('[data-reveal]').forEach(function (b) {
      b.onclick = function () { reveal(b.dataset.reveal); };
    });
    body.querySelectorAll('.opt-path').forEach(function (a) {
      a.onclick = function () { reveal(a.dataset.reveal); };
    });
    wireDbEdit();
    wireFilePaths();
    wireKeyView();
    wirePrefs();
    loadNotices();
  }

  /* Third-party attribution, listed from what this build actually ships
     (see src/vibenative/notices.py). */
  function loadNotices() {
    var host = body.querySelector('#notices');
    if (!host) return;
    fetch('/notices').then(function (r) { return r.json(); }).then(function (list) {
      if (!list || !list.length) { host.textContent = 'none recorded'; return; }
      host.innerHTML = list.map(function (n) {
        return '<div class="notice">' +
          '<div class="notice-h"><b>' + esc(n.name) + '</b>' +
            '<span class="notice-lic">' + esc(n.licence) + '</span></div>' +
          '<div class="notice-w">' + esc(n.what) + '</div>' +
          (n.url ? '<a class="notice-u" href="' + esc(n.url) + '" target="_blank" ' +
                   'rel="noopener noreferrer">' + esc(n.url) + '</a>' : '') +
        '</div>';
      }).join('');
    }).catch(function () { host.textContent = 'could not load the credits'; });
  }

  /* Every control that carries data-pref edits that preference in place. */
  function wirePrefs() {
    body.querySelectorAll('.opt-seg[data-pref]').forEach(function (s) {
      s.querySelectorAll('button').forEach(function (b) {
        b.onclick = function () {
          setPref(s.dataset.pref, b.dataset.v);
          s.querySelectorAll('button').forEach(function (x) { x.classList.toggle('on', x === b); });
        };
      });
    });
    body.querySelectorAll('input[type="range"][data-pref]').forEach(function (r) {
      var out = r.nextElementSibling;
      r.oninput = function () {
        setPref(r.dataset.pref, Number(r.value));
        if (out) out.textContent = r.value + (r.dataset.fmt || '');
      };
    });
    body.querySelectorAll('input[type="checkbox"][data-pref]').forEach(function (c) {
      c.onchange = function () { setPref(c.dataset.pref, c.checked); };
    });
    var mapReset = document.getElementById('opt-map-reset');
    if (mapReset) mapReset.onclick = function () {
      ['vibeMapLabels', 'vibeUniverse', 'vibeSolar', 'vibeTree', 'vibeFamHue', 'vibeSubHue',
       'vibeLegend', 'vibeNavKeys'].forEach(function (k) {
        try { localStorage.removeItem(k); } catch (_) { /* private mode */ }
      });
      note('opt-map-reset-msg', 'Map settings reset. Reloading…');
      setTimeout(function () { location.reload(); }, 400);
    };
    var all = document.getElementById('opt-prefs-reset');
    if (all) all.onclick = function () {
      var keys = [];
      try { for (var i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i)); } catch (_) { /* private mode */ }
      keys.filter(function (k) { return k && k.indexOf('vibe') === 0; })
          .forEach(function (k) { try { localStorage.removeItem(k); } catch (_) { /* private mode */ } });
      location.reload();
    };
  }

  /* Key notation. app.js owns the setting and the re-render, so this is only the
     control: mark the live one, hand over the new one. */
  function wireKeyView() {
    var seg = document.getElementById('keyview');
    if (!seg || typeof KEYVIEW === 'undefined') return;
    var mark = function () {
      seg.querySelectorAll('button').forEach(function (b) {
        b.classList.toggle('on', b.dataset.k === KEYVIEW.mode);
      });
    };
    seg.querySelectorAll('button').forEach(function (b) {
      b.onclick = function () { setKeyView(b.dataset.k); mark(); };
    });
    mark();
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

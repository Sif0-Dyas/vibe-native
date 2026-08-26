/* Genres tab — the taxonomy, made visible.

   Three tiers, top to bottom: family → keystone → subgenre. Each keystone shows
   what it is, the tempo it conventionally runs at next to the tempo YOUR tracks
   actually measure, its palette colour, and the most representative tracks you own.

   The two BPM ranges are deliberately side by side. Where they disagree, the
   disagreement is the finding — Drum n Bass reads an octave low here because
   tempo detection resolves 174 as 87, and a single merged number would hide that.

   Also hosts the two library-wide genre actions, both reversible: re-label
   (re-run the head over stored embeddings) and reset (back to stock). */
(function () {
  var body;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function bpmCell(b) {
    if (!b) return '';
    var can = b.canonical ? b.canonical[0] + '–' + b.canonical[1] : '—';
    var o = b.observed;
    var obs = o ? o.p10 + '–' + o.p90 + ' <i>(med ' + o.median + ')</i>' : '—';
    // The flag is the point of showing both: a ~2x gap means the tempo was
    // resolved an octave off, not that the genre is unusual.
    var flag = b.octave_flag
      ? '<span class="gen-warn" title="detected tempo is about ' +
        (b.octave_flag === 'half' ? 'half' : 'double') +
        ' the conventional range — an octave misread, not an unusual genre">' +
        b.octave_flag + '-time</span>'
      : '';
    return '<div class="gen-bpm"><span class="gk">typical</span> ' + esc(can) +
           '<span class="gk">yours</span> ' + obs + flag + '</div>';
  }

  /* A tiny waveform in the genre's own colour. Drawn from the genre name so it
     is stable per genre rather than random noise that changes on every render --
     it should read as that genre's mark, not decoration. */
  function waveSvg(color, seed) {
    var n = 26, bars = [], acc = 0, i;
    for (i = 0; i < String(seed).length; i++) acc = (acc * 31 + String(seed).charCodeAt(i)) % 9973;
    for (i = 0; i < n; i++) {
      acc = (acc * 1103515245 + 12345) % 2147483648;
      var h = 3 + (acc % 100) / 100 * 15;                  // 3..18 of a 22 box
      bars.push('<rect x="' + (i * 2.2) + '" y="' + ((22 - h) / 2).toFixed(1) +
                '" width="1.3" height="' + h.toFixed(1) + '" rx="0.6"/>');
    }
    return '<svg class="gen-wave" viewBox="0 0 58 22" aria-hidden="true" ' +
           'style="color:' + esc(color) + '">' + bars.join('') + '</svg>';
  }

  function keystoneCard(k) {
    var subs = (k.subgenres || []).slice(0, 8).map(function (s) {
      return '<span class="gen-sub">' + esc(s.style) + '<i>' + s.count + '</i></span>';
    }).join('');
    var top = (k.top || []).map(function (t) {
      return '<li>' + esc(t.title) + (t.bpm ? ' <i>' + Math.round(t.bpm) + '</i>' : '') + '</li>';
    }).join('');
    var o = (k.bpm && k.bpm.observed) || null;
    var avg = o ? o.median : null;
    var tr = k.training || { state: 'sparse', files: 0, needs: 20 };
    // Pulse the border on the beat, in the genre's colour. Subtle: a page of 18
    // cards each at its own tempo would strobe if this were high contrast.
    var beat = avg ? (60 / avg).toFixed(3) + 's' : null;
    var pulse = beat ? ' style="--gen-beat:' + beat + ';--gen-col:' + esc(k.color) + '"' : '';

    return '<div class="gen-key' + (beat ? ' pulsing' : '') + '"' + pulse + '>' +
      '<div class="gen-card-top">' +
        '<span class="gen-wavebox" style="border-color:' + esc(k.color) + '33">' +
          waveSvg(k.color, k.keystone) + '</span>' +
        '<div class="gen-titles">' +
          '<h4>' + esc(k.keystone) + '</h4>' +
          '<span class="gen-level" data-g="' + esc(k.keystone) + '" title="tier in the hierarchy">' +
            esc(k.tier || 'keystone') + '</span>' +
        '</div>' +
        '<div class="gen-bpmbig">' + (avg ? Math.round(avg) + '<i>bpm</i>' : '<i>—</i>') + '</div>' +
      '</div>' +
      '<div class="gen-card-stats">' +
        '<span class="vib-state ' + (tr.state === 'ready' ? 'ok' : tr.state === 'thin' ? 'warn' : 'bad') +
          '">' + esc(tr.state) + '</span>' +
        '<span class="gen-statlab">' + tr.files + ' training file' + (tr.files === 1 ? '' : 's') +
          (tr.needs ? ' · needs ' + tr.needs + ' more' : '') + '</span>' +
        '<span class="gen-count">' + k.count + ' track' + (k.count === 1 ? '' : 's') + '</span>' +
      '</div>' +
      (k.blurb ? '<p class="gen-blurb">' + esc(k.blurb) + '</p>' : '') +
      bpmCell(k.bpm) +
      (subs ? '<div class="gen-subs">' + subs + '</div>' : '') +
      (top ? '<div class="gen-toph">top tracks</div><ol class="gen-top">' + top + '</ol>' : '') +
      '<div class="gen-actions">' +
        '<button class="gen-train" data-g="' + esc(k.keystone) + '">train</button>' +
        '<button class="gen-reset-top" data-g="' + esc(k.keystone) + '">reset</button>' +
      '</div>' +
      '<div class="gen-panel" hidden></div>' +
    '</div>';
  }

  /* Per-genre training console. Everything that acts on ONE genre lives here:
     what it has, the tracks to teach it from, and reset/export/import scoped to
     it alone -- so a genre that has been fed the wrong tracks can be cleared
     without discarding every other genre's work. */
  function trainPanel(box, genre) {
    box.innerHTML = '<div class="opt-note">loading…</div>';
    Promise.all([
      fetch('/training/set/' + encodeURIComponent(genre) + '?top=10').then(function (r) { return r.json(); }),
      fetch('/training/status').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (out) {
      var d = out[0], st = out[1] || { thresholds: { ready: 20 } };
      var mine = ((st.genres || []).filter(function (g) { return g.genre === genre; })[0]) || { files: d.files, state: 'sparse', needs: st.thresholds.ready };
      var tracks = (d.top || []).map(function (t) {
        return '<li><label><input type="checkbox" class="gen-pick" value="' + esc(t.hash) + '"' +
          (t.in_training ? ' checked disabled' : '') + '> ' + esc(t.title) +
          ' <i>' + esc(t.style) + (t.bpm ? ' · ' + Math.round(t.bpm) : '') + '</i>' +
          (t.in_training ? ' <span class="gen-in">in training</span>' : '') + '</label></li>';
      }).join('');
      box.innerHTML =
        '<div class="gen-panel-grid">' +
          '<div><span class="gk">files</span> ' + d.files + '</div>' +
          '<div><span class="gk">labelled</span> ' + d.labelled + '</div>' +
          '<div><span class="gk">rejected</span> ' + d.rejected + '</div>' +
          '<div><span class="gk">reads as this</span> ' + d.library_tracks + '</div>' +
          '<div><span class="vib-state ' +
            (mine.state === 'ready' ? 'ok' : mine.state === 'thin' ? 'warn' : 'bad') + '">' +
            mine.state + '</span>' + (mine.needs ? ' needs ' + mine.needs + ' more' : ' ready') + '</div>' +
        '</div>' +
        (tracks ? '<div class="gen-toph">top tracks — tick to add as training examples</div>' +
                  '<ol class="gen-top gen-picks">' + tracks + '</ol>' :
                  '<div class="opt-note">No library tracks read as this genre yet.</div>') +
        '<div class="gen-actions">' +
          '<button class="gen-add">add ticked</button>' +
          '<a class="gen-exp" href="/training/set/' + encodeURIComponent(genre) + '/export" download>export</a>' +
          '<button class="gen-imp">import</button>' +
          '<input type="file" class="gen-imp-file" accept=".json,application/json" hidden>' +
          '<button class="gen-reset">reset this genre</button>' +
        '</div>' +
        '<div class="opt-note gen-msg">Reset archives this genre&rsquo;s audio and clears only ' +
        'its labels — every other genre keeps its training.</div>';

      var msg = box.querySelector('.gen-msg');
      var say = function (t, bad) {
        msg.innerHTML = '<b class="' + (bad ? 'opt-bad' : 'opt-good') + '">' + esc(t) + '</b>';
      };

      box.querySelector('.gen-add').onclick = function () {
        var picks = [].slice.call(box.querySelectorAll('.gen-pick:checked:not(:disabled)'))
          .map(function (i) { return i.value; });
        if (!picks.length) { say('tick some tracks first', true); return; }
        fetch('/training/set/' + encodeURIComponent(genre) + '/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ hashes: picks })
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j.error) { say(j.error, true); return; }
          say('added ' + j.added + ' track(s), ' + j.audio_copied + ' audio file(s) copied');
          trainPanel(box, genre);
        }).catch(function () { say('add failed', true); });
      };

      var file = box.querySelector('.gen-imp-file');
      box.querySelector('.gen-imp').onclick = function () { file.click(); };
      file.onchange = function () {
        var f = file.files[0]; if (!f) return;
        f.text().then(function (txt) {
          var m; try { m = JSON.parse(txt); } catch (_) { say('not valid JSON', true); return; }
          return fetch('/training/set/import', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ manifest: m, genre: genre })
          }).then(function (r) { return r.json(); }).then(function (j) {
            if (j.error) { say(j.error, true); return; }
            say('imported ' + j.labels_added + ' label(s), copied ' + j.audio_copied +
                (j.missing_from_library ? ', ' + j.missing_from_library + ' not in your library' : ''));
            trainPanel(box, genre);
          });
        }).catch(function () { say('import failed', true); });
        file.value = '';
      };

      box.querySelector('.gen-reset').onclick = function () {
        if (!window.confirm('Reset training for "' + genre + '"?\n\nIts audio is archived (not ' +
            'deleted) and only this genre’s labels are cleared. Every other genre keeps its ' +
            'training.')) return;
        fetch('/training/set/' + encodeURIComponent(genre) + '/reset', { method: 'POST' })
          .then(function (r) { return r.json(); }).then(function (j) {
            if (j.error) { say(j.error, true); return; }
            say('cleared ' + j.labels_cleared + ' label(s)' +
                (j.archived_to ? ' · audio archived' : ''));
            trainPanel(box, genre);
          }).catch(function () { say('reset failed', true); });
      };
    }).catch(function () { box.innerHTML = '<div class="opt-note">could not load</div>'; });
  }

  function render(families) {
    var total = families.reduce(function (a, f) { return a + f.count; }, 0);
    body.innerHTML =
      '<div class="opt-card"><h3>Library actions</h3>' +
        '<div class="opt-row"><span class="k">Re-label</span>' +
          '<span class="v" id="gen-rl-stat">—</span></div>' +
        '<div class="opt-note">Re-runs the classifier over stored embeddings, so tracks ' +
        'analysed before you trained a genre get corrected without a re-scan. Preview ' +
        'first — it snapshots before applying, and can be reverted.</div>' +
        '<div class="opt-actions">' +
          '<button id="gen-rl-preview">preview</button>' +
          '<button id="gen-rl-apply" disabled>apply</button>' +
          '<button id="gen-rl-revert">revert</button>' +
          '<button id="gen-snap">snapshot now</button>' +
        '</div>' +
        '<div class="opt-note" id="gen-msg"></div>' +
      '</div>' +
      families.map(function (f) {
        var name = f.archgenre || f.family;
        // A standalone archgenre IS its keystone (House, Techno...), so the
        // heading would just repeat the card title underneath it.
        var solo = f.standalone && f.keystones.length === 1;
        return '<div class="opt-card gen-fam">' +
          (solo ? '' : '<h3>' + esc(name) + ' <span class="gen-n">' + f.count +
            ' · ' + Math.round(f.share * 100) + '% · archgenre</span></h3>') +
          '<div class="gen-keys">' + f.keystones.map(keystoneCard).join('') + '</div>' +
        '</div>';
      }).join('') +
      '<div class="opt-card"><h3>How this works</h3>' +
        '<div class="opt-note">' +
        '<b>Family → keystone → subgenre.</b> A subgenre of house is still house, so the ' +
        'keystone is what a track <i>is</i> and the subgenres are detail. Families group ' +
        'keystones for large-scale sorting; everything non-electronic collapses into ' +
        '<b>Other</b>, because this is a tool for an electronic library.<br><br>' +
        'A track gets <b>two keystones</b> when the runner-up holds at least 35% — measured ' +
        'against this library, where the median track is 84% a single keystone. Where the ' +
        'blend has an established name it is used (Dubstep + Drum n Bass = Drumstep); ' +
        'otherwise the two are joined with a slash rather than inventing one.<br><br>' +
        'Only <b>eight</b> keystones can carry a distinct colour — that is a hard limit of ' +
        'categorical colour, not an oversight. One slot is reserved per electronic family ' +
        'so a small family is never left colourless; the rest use the neutral and read from ' +
        'position and label instead.' +
        '</div>' +
      '</div>';
    wireActions();
    // one console per keystone card, built on demand -- each is several queries
    body.querySelectorAll('.gen-reset-top').forEach(function (b) {
      b.onclick = function () {
        var g = b.dataset.g;
        if (!window.confirm('Reset training for "' + g + '"?\n\n' +
            'Its audio is archived (not deleted) and only this genre’s ' +
            'labels are cleared. Every other genre keeps its training.')) return;
        fetch('/training/set/' + encodeURIComponent(g) + '/reset', { method: 'POST' })
          .then(function () { window.vibeLoadGenres(); }).catch(function () {});
      };
    });
    body.querySelectorAll('.gen-train').forEach(function (b) {
      b.onclick = function () {
        var panel = b.closest('.gen-key').querySelector('.gen-panel');
        if (!panel.hidden) { panel.hidden = true; b.textContent = 'train'; return; }
        panel.hidden = false;
        b.textContent = 'hide';
        trainPanel(panel, b.dataset.g);
      };
    });
    void total;
  }

  function msg(text, bad) {
    var el = document.getElementById('gen-msg');
    if (el) el.innerHTML = '<b class="' + (bad ? 'opt-bad' : 'opt-good') + '">' + esc(text) + '</b>';
  }

  function refreshRelabelStatus() {
    fetch('/relabel/status').then(function (r) { return r.json(); }).then(function (s) {
      var el = document.getElementById('gen-rl-stat');
      if (!el) return;
      el.textContent = s.relabelled
        ? s.relabelled + ' of ' + s.total + ' re-labelled' + (s.stale ? ' (head has changed since)' : '')
        : 'none — tracks read as originally analysed';
    }).catch(function () {});
  }

  function wireActions() {
    refreshRelabelStatus();
    var applyBtn = document.getElementById('gen-rl-apply');

    document.getElementById('gen-rl-preview').onclick = function () {
      msg('checking…');
      fetch('/relabel/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(function (r) { return r.json(); }).then(function (j) {
          if (j.error) { msg(j.error, true); return; }
          if (!j.changed) { msg('nothing would change — the head agrees with the stored reads'); applyBtn.disabled = true; return; }
          var ex = (j.examples || []).slice(0, 3)
            .map(function (e) { return e.from + ' → ' + e.to; }).join(', ');
          // With the stock head there is no new knowledge to apply: any change is
          // just the mean embedding disagreeing with the richer salience read
          // (~13% of tracks), so applying would replace good reads with worse
          // ones. Re-labelling pays off only after training a custom head.
          if (j.head === 'stock') {
            msg(j.changed + ' of ' + j.total + ' would change — but this is the STOCK head, so ' +
                'these are not corrections, just the averaged read disagreeing with the ' +
                'original. Re-label after you train a genre, not before.', true);
            applyBtn.disabled = true;
            return;
          }
          msg(j.changed + ' of ' + j.total + ' tracks would change' + (ex ? ' (e.g. ' + ex + ')' : ''));
          applyBtn.disabled = false;
        }).catch(function () { msg('preview failed', true); });
    };

    applyBtn.onclick = function () {
      msg('applying…');
      fetch('/relabel/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(function (r) { return r.json(); }).then(function (j) {
          if (j.error) { msg(j.error, true); return; }
          msg('re-labelled ' + j.updated + ' tracks (' + j.skipped_override +
              ' manual overrides left alone). Snapshot taken first.');
          applyBtn.disabled = true;
          window.vibeLoadGenres();
        }).catch(function () { msg('apply failed', true); });
    };

    document.getElementById('gen-rl-revert').onclick = function () {
      fetch('/relabel/revert', { method: 'POST' })
        .then(function (r) { return r.json(); }).then(function (j) {
          msg('reverted ' + j.reverted + ' tracks to their original reads');
          window.vibeLoadGenres();
        }).catch(function () { msg('revert failed', true); });
    };

    document.getElementById('gen-snap').onclick = function () {
      fetch('/snapshots', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ label: 'manual' }) })
        .then(function (r) { return r.json(); }).then(function (j) {
          msg('snapshot ' + j.id + ' — ' + j.overrides + ' overrides captured');
        }).catch(function () { msg('snapshot failed', true); });
    };
  }

  window.vibeLoadGenres = function () {
    body = document.getElementById('gen-body');
    if (!body) return;
    body.innerHTML = 'Loading…';
    Promise.all([
      fetch('/genres?top=5&by=archgenre').then(function (r) { return r.json(); }),
      fetch('/training/status').then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
    ]).then(function (out) {
      var groups = out[0] || [], st = out[1];
      // Fold training readiness onto each keystone so a card can show it without
      // a request of its own -- 18 cards would otherwise mean 18 round trips.
      var byGenre = {};
      ((st && st.genres) || []).forEach(function (g) { byGenre[g.genre] = g; });
      var ready = (st && st.thresholds && st.thresholds.ready) || 20;
      groups.forEach(function (grp) {
        grp.keystones.forEach(function (k) {
          k.training = byGenre[k.keystone] || { state: 'sparse', files: 0, needs: ready };
          k.tier = grp.standalone ? 'archgenre' : 'keystone';
        });
      });
      render(groups);
    }).catch(function () {
      body.innerHTML = '<div class="opt-card">Could not load the genre taxonomy.</div>';
    });
  };
})();

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

  function keystoneCard(k) {
    var subs = (k.subgenres || []).slice(0, 8).map(function (s) {
      return '<span class="gen-sub">' + esc(s.style) + '<i>' + s.count + '</i></span>';
    }).join('');
    var top = (k.top || []).map(function (t) {
      return '<li>' + esc(t.title) + (t.bpm ? ' <i>' + Math.round(t.bpm) + '</i>' : '') + '</li>';
    }).join('');
    return '<div class="gen-key">' +
      '<div class="gen-key-head">' +
        '<span class="gen-dot" style="background:' + esc(k.color) + '"></span>' +
        '<b>' + esc(k.keystone) + '</b>' +
        '<span class="gen-n">' + k.count + '</span>' +
        (k.slotted ? '' : '<span class="gen-muted" title="only eight keystones can carry a ' +
          'distinct hue; this one uses the neutral and reads from its position and label' +
          '">no colour</span>') +
      '</div>' +
      (k.blurb ? '<div class="gen-blurb">' + esc(k.blurb) + '</div>' : '') +
      bpmCell(k.bpm) +
      (subs ? '<div class="gen-subs">' + subs + '</div>' : '') +
      (top ? '<div class="gen-toph">most representative</div><ol class="gen-top">' + top + '</ol>' : '') +
    '</div>';
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
        return '<div class="opt-card gen-fam">' +
          '<h3>' + esc(f.family) + ' <span class="gen-n">' + f.count +
          ' · ' + Math.round(f.share * 100) + '%</span></h3>' +
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
    fetch('/genres?top=5').then(function (r) { return r.json(); }).then(render).catch(function () {
      body.innerHTML = '<div class="opt-card">Could not load the genre taxonomy.</div>';
    });
  };
})();

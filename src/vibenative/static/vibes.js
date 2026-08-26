/* Vibes tab — your own categories, with room to say what they mean.

   A vibe is user-created, so unlike a genre nothing external defines it. The
   notes field is the whole point: what belongs in this set, what doesn't, when
   you'd play it. It is unbounded and the textarea grows to fit — a category you
   invented deserves as much explanation as it needs.

   The side panel remains for quick add/remove while working through tracks;
   this tab is the place to sit down and describe them. */
(function () {
  var body;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function card(v) {
    var desc = v.description || '';
    return '<div class="opt-card vib-card" data-id="' + v.id + '">' +
      '<h3>' + esc(v.name) +
        '<span class="gen-n">' + v.count + ' track' + (v.count === 1 ? '' : 's') + '</span>' +
      '</h3>' +
      '<textarea class="vib-note" rows="3" spellcheck="true" ' +
        'placeholder="What is this vibe? What belongs in it, what doesn&rsquo;t, when you&rsquo;d play it…"' +
        '>' + esc(desc) + '</textarea>' +
      '<div class="vib-row">' +
        '<span class="vib-msg">' + (desc ? desc.length + ' characters' : 'no notes yet') + '</span>' +
        '<button class="vib-tracks">tracks</button>' +
        '<button class="vib-save">save notes</button>' +
      '</div>' +
      '<div class="vib-members" hidden></div>' +
    '</div>';
  }

  function trainingCard(t) {
    if (!t) return '';
    var rows = (t.genres || []).map(function (g) {
      var bar = g.state === 'ready' ? 'ok' : (g.state === 'thin' ? 'warn' : 'bad');
      var need = g.needs ? ' · needs ' + g.needs + ' more' : '';
      return '<div class="opt-row">' +
        '<span class="k">' + esc(g.genre) + '</span>' +
        '<span class="v"><span class="vib-state ' + bar + '">' + g.state + '</span> ' +
          g.files + ' file' + (g.files === 1 ? '' : 's') + need + '</span>' +
      '</div>';
    }).join('');
    return '<div class="opt-card"><h3>Training data</h3>' +
      (rows || '<div class="opt-note">Nothing yet. Overriding a track’s genre files its ' +
        'audio here automatically.</div>') +
      '<div class="opt-note">A shallow head over the stored embeddings needs <b>variety</b> ' +
      'more than volume, but one or two tracks cannot represent a genre — it learns those ' +
      'recordings, not the sound. <b>' + t.thresholds.ready + '+</b> files reads as ready, ' +
      '<b>' + t.thresholds.thin + '–' + (t.thresholds.ready - 1) + '</b> as thin. Guidance, ' +
      'not a gate: you can train with less, it just won’t generalise.<br><br>' +
      'Custom head: <b>' + (t.custom_head ? 'trained' : 'not trained yet — running stock') +
      '</b>. Files live in <code>' + esc(t.folder) + '</code>.</div></div>';
  }

  function render(vibes, training) {
    body.innerHTML =
      '<div class="opt-card"><h3>New vibe</h3>' +
        '<div class="opt-edit">' +
          '<input type="text" id="vib-new" class="opt-input" placeholder="e.g. Sunset Warmup" spellcheck="false">' +
          '<button id="vib-create">create</button>' +
        '</div>' +
        '<div class="opt-note" id="vib-top-msg">A vibe is your own category. Add tracks from ' +
        'the map or the list, then describe it here so the reason it exists outlives your memory of it.</div>' +
      '</div>' +
      trainingCard(training) +
      (vibes.length ? vibes.map(card).join('')
        : '<div class="opt-card"><div class="opt-note">No vibes yet.</div></div>');
    wire();
  }

  function wire() {
    var create = document.getElementById('vib-create');
    if (create) create.onclick = function () {
      var el = document.getElementById('vib-new');
      var name = el.value.trim();
      if (!name) return;
      fetch('/vibes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name }) })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok) { document.getElementById('vib-top-msg').innerHTML =
            '<b class="opt-bad">' + esc(res.j.error || 'could not create') + '</b>'; return; }
          el.value = '';
          window.vibeLoadVibes();
        }).catch(function () {});
    };

    body.querySelectorAll('.vib-card').forEach(function (cardEl) {
      var id = cardEl.dataset.id;
      var ta = cardEl.querySelector('.vib-note');
      var msg = cardEl.querySelector('.vib-msg');

      // grow to fit rather than scrolling inside a fixed box
      var grow = function () { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; };
      grow();
      ta.addEventListener('input', grow);

      cardEl.querySelector('.vib-save').onclick = function () {
        fetch('/vibes/' + id + '/description', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ description: ta.value })
        }).then(function (r) { return r.json(); }).then(function (j) {
          msg.innerHTML = '<b class="opt-good">' +
            (j.length ? 'saved · ' + j.length + ' characters' : 'cleared') + '</b>';
        }).catch(function () { msg.innerHTML = '<b class="opt-bad">save failed</b>'; });
      };

      var members = cardEl.querySelector('.vib-members');
      cardEl.querySelector('.vib-tracks').onclick = function () {
        if (!members.hidden) { members.hidden = true; return; }
        members.hidden = false;
        members.innerHTML = '<div class="opt-note">loading…</div>';
        fetch('/vibes/' + id + '/members').then(function (r) { return r.json(); }).then(function (list) {
          var items = (list || []).slice(0, 200);
          members.innerHTML = items.length
            ? '<ol class="gen-top">' + items.map(function (m) {
                return '<li>' + esc(m.title || m.hash) +
                  (m.weight && m.weight !== 1 ? ' <i>x' + m.weight + '</i>' : '') + '</li>';
              }).join('') + '</ol>'
            : '<div class="opt-note">No tracks in this vibe yet.</div>';
        }).catch(function () { members.innerHTML = '<div class="opt-note">could not load tracks</div>'; });
      };
    });
  }

  window.vibeLoadVibes = function () {
    body = document.getElementById('vib-body');
    if (!body) return;
    body.innerHTML = 'Loading…';
    Promise.all([
      fetch('/vibes').then(function (r) { return r.json(); }),
      fetch('/training/status').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (out) { render(out[0] || [], out[1]); })
      .catch(function () {
        body.innerHTML = '<div class="opt-card">Could not load vibes.</div>';
      });
  };
})();

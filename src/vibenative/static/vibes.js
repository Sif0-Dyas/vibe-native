/* Vibes tab — your own categories, laid out the way the Genres tab is.

   A vibe is user-created, so unlike a genre nothing external defines it. That is
   exactly why it needs MORE explanation on screen, not less: a genre card can
   fall back on "this is what dubstep is", a vibe card cannot.

   The layout deliberately mirrors Genres — explain, summarise, show, configure —
   and reuses that tab's tile classes (.gen-keys / .gen-key / .gen-tile) rather
   than restyling them. Two tabs that show "a thing, its size, and its detail on
   click" should not look like two different applications, and sharing the
   classes is what keeps them from drifting apart the next time either changes.

   The side panel remains for quick add/remove while working through tracks;
   this tab is the place to sit down and describe them. */
(function () {
  var body;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* A vibe has no palette entry the way a keystone does -- nothing external
     assigns it a colour -- so derive a stable one from the name (nameHue,
     app.js: the same hue its galaxy gets on the map). */
  function vibeColor(name) {
    return 'hsl(' + nameHue(name) + ' 58% 60%)';
  }

  /* How full a vibe is. A one-track vibe is a note to self, not a category, and
     saying so is kinder than showing "1" with no comment. */
  function vibeState(count) {
    if (!count) return { key: 'bad', word: 'empty', hint: 'No tracks yet' };
    if (count < 10) return { key: 'warn', word: 'growing', hint: 'Add more tracks to make this useful' };
    return { key: 'ok', word: 'solid', hint: 'Enough tracks to find similar music reliably' };
  }

  function howCard() {
    return '<div class="opt-card gen-how opt-fold collapsed"><h3>How this works</h3>' +
      '<div class="opt-note">' +
      'A <b>vibe</b> is a category you invent. Genres are decided for you by the ' +
      'analysis; a vibe is decided by you &mdash; and it can be anything a genre ' +
      'cannot describe:' +
      '<div class="gen-tree-key">' +
        '<span><b>A moment</b><i>e.g. <em>Sunset Warmup</em>, <em>3am Basement</em></i></span>' +
        '<span><b>A feeling</b><i>e.g. <em>Euphoric</em>, <em>Menacing</em></i></span>' +
        '<span><b>A job</b><i>e.g. <em>Opening Set</em>, <em>Needs a Rework</em></i></span>' +
      '</div>' +
      '<b>How to build one.</b> Create it below, then add tracks to it from the ' +
      '<b>Map</b> or the <b>Analyzer</b> &mdash; click any track and pick the vibe. ' +
      'Come back here to write down what it means.<br><br>' +
      '<b>Why the notes matter.</b> In six months you will not remember why a track ' +
      'went into a vibe. The notes box on each card is for exactly that: what belongs, ' +
      'what does not, and when you would play it.<br><br>' +
      '<b>What Vibedentify does with it.</b> Once a vibe has about ten tracks, it learns ' +
      'the sound they have in common and can go find more of it in your library. That is ' +
      'why a card says <span class="vib-state warn">growing</span> until then &mdash; not ' +
      'a rule, just the point where the suggestions start being worth reading.' +
      '</div></div>';
  }

  /* Total vibes -- the same shape as the Genres tab's counter card, so the two
     tabs read as one product. */
  function statsCard(vibes) {
    var total = vibes.reduce(function (a, v) { return a + v.count; }, 0);
    var sorted = vibes.slice().sort(function (a, b) { return b.count - a.count; });
    var top = sorted.length ? sorted[0] : null;
    var described = vibes.filter(function (v) { return (v.description || '').trim(); }).length;

    var list = window.statRowsHtml(sorted.map(function (v) {
      return { name: v.name, count: v.count, color: vibeColor(v.name) };
    }), total);

    return '<div class="opt-card opt-fold"><h3>Total vibes</h3>' +
      '<div class="gen-bigstats">' +
        '<div class="gen-bigstat"><b>' + vibes.length + '</b><i>vibes you have made</i></div>' +
        '<div class="gen-bigstat"><b>' + total + '</b><i>tracks filed into a vibe</i></div>' +
        '<div class="gen-bigstat"><b>' + described + ' / ' + vibes.length +
          '</b><i>have notes written</i></div>' +
        (top ? '<div class="gen-bigstat"><b>' + esc(top.name) + '</b><i>your biggest vibe, ' +
          top.count + ' track' + (top.count === 1 ? '' : 's') + '</i></div>' : '') +
      '</div>' +
      (list ? '<div class="gen-stats">' + list + '</div>'
            : '<div class="opt-note">No vibes yet &mdash; make your first one below.</div>') +
      (total ? '<div class="opt-note">Percentages are shares of the tracks you have filed ' +
        'into vibes, not of your whole library. A track can sit in several vibes at once, ' +
        'so it may be counted more than once.</div>' : '') +
    '</div>';
  }

  /* One vibe tile. Same anatomy as a genre tile -- mark, name, tier chip, big
     number, state, count -- so the eye reads them the same way. */
  function card(v) {
    var desc = v.description || '';
    var col = vibeColor(v.name);
    var st = vibeState(v.count);
    return '<div class="gen-key vib-key" data-id="' + v.id + '" style="--gen-col:' + col + '">' +
      '<button class="gen-tile" type="button">' +
        '<span class="gen-wavebox" style="border-color:' + col + '55">' +
          window.vibeWaveSvg(col, v.name) + '</span>' +
        '<span class="gen-titles">' +
          '<span class="gen-name">' + esc(v.name) + '</span>' +
          '<span class="gen-level" title="A category you created yourself">vibe</span>' +
        '</span>' +
        '<span class="gen-tilemeta">' +
          '<span class="gen-bpmbig">' + v.count + '<i>tracks</i></span>' +
        '</span>' +
        '<span class="gen-tilefoot">' +
          '<span class="vib-state ' + st.key + '" title="' + esc(st.hint) + '">' +
            st.word + '</span>' +
          '<span class="gen-count">' +
            (desc ? desc.trim().length + ' chars of notes' : 'no notes yet') + '</span>' +
        '</span>' +
      '</button>' +
      '<div class="gen-detail" hidden>' +
        '<div class="vib-notewrap">' +
          '<div class="gen-toph">What is this vibe?</div>' +
          '<textarea class="vib-note" rows="3" spellcheck="true" ' +
            'placeholder="What belongs in it, what does not, and when you would play it…"' +
            '>' + esc(desc) + '</textarea>' +
          '<div class="vib-row">' +
            '<button class="vib-save">save notes</button>' +
            '<span class="vib-msg">' + (desc ? 'saved' : 'not written yet') + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="vib-sidewrap">' +
          '<div class="gen-toph">Tracks in this vibe</div>' +
          '<div class="vib-members"><div class="opt-note">loading…</div></div>' +
        '</div>' +
        '<div class="gen-actions">' +
          '<button class="vib-rename">rename</button>' +
          '<button class="vib-clear">remove all tracks</button>' +
          '<button class="vib-delete">delete this vibe</button>' +
          '<span class="vib-act-msg opt-note"></span>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function backupCard() {
    return '<div class="opt-card"><h3>Back up or move your vibes</h3>' +
      '<div class="opt-note">Vibes are yours and nothing else recreates them, so they are ' +
      'worth keeping a copy of. <b>Export</b> saves every vibe and its tracks to one file. ' +
      '<b>Import</b> reads that file back &mdash; on this computer or another one. Importing ' +
      'merges rather than replaces: a vibe with a name you already have gains the imported ' +
      'tracks instead of overwriting them.</div>' +
      '<div class="opt-actions">' +
        '<a class="gen-exp" href="/vibes/export" download="vibes.json">export all vibes</a>' +
        '<button id="vib-imp">import from a file</button>' +
        '<input type="file" id="vib-imp-file" accept=".json,application/json" hidden>' +
      '</div>' +
      '<div class="opt-note" id="vib-imp-msg"></div>' +
    '</div>';
  }

  function render(vibes) {
    body.innerHTML =
      howCard() +
      statsCard(vibes) +
      '<div class="opt-card"><h3>Make a new vibe</h3>' +
        '<div class="opt-note">Give it a name you will recognise later. You can rename it ' +
        'at any time, and nothing is written to your music files.</div>' +
        '<div class="opt-edit">' +
          '<input type="text" id="vib-new" class="opt-input" placeholder="e.g. Sunset Warmup" ' +
            'spellcheck="false">' +
          '<button id="vib-create">create vibe</button>' +
        '</div>' +
        '<div class="opt-note" id="vib-top-msg"></div>' +
      '</div>' +
      '<h2 class="gen-sechd">Your vibes<span>click a card to write its notes and see its ' +
        'tracks</span></h2>' +
      (vibes.length
        ? '<div class="opt-card"><div class="gen-keys">' + vibes.map(card).join('') + '</div></div>'
        : '<div class="opt-card"><div class="opt-note">No vibes yet. Make one above, then add ' +
          'tracks to it from the <b>Map</b> or the <b>Analyzer</b>.</div></div>') +
      '<h2 class="gen-sechd">Library actions<span>backups</span></h2>' +
      backupCard();
    wire();
    window.applyFolds(body);
  }

  function wire() {
    var create = document.getElementById('vib-create');
    var topMsg = document.getElementById('vib-top-msg');
    if (create) create.onclick = function () {
      var el = document.getElementById('vib-new');
      var name = el.value.trim();
      if (!name) { topMsg.innerHTML = '<b class="opt-bad">Type a name first.</b>'; return; }
      fetch('/vibes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name }) })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok) {
            topMsg.innerHTML = '<b class="opt-bad">' +
              esc(res.j.error || 'could not create') + '</b>';
            return;
          }
          el.value = '';
          window.vibeLoadVibes(name);
        }).catch(function () {
          topMsg.innerHTML = '<b class="opt-bad">could not create</b>';
        });
    };

    var impBtn = document.getElementById('vib-imp');
    var impFile = document.getElementById('vib-imp-file');
    var impMsg = document.getElementById('vib-imp-msg');
    if (impBtn) impBtn.onclick = function () { impFile.click(); };
    if (impFile) impFile.onchange = function () {
      var f = impFile.files[0]; if (!f) return;
      f.text().then(function (txt) {
        var m;
        try { m = JSON.parse(txt); } catch (_) {
          impMsg.innerHTML = '<b class="opt-bad">That is not a vibes file.</b>'; return;
        }
        return fetch('/vibes/import', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(m)
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j.error) { impMsg.innerHTML = '<b class="opt-bad">' + esc(j.error) + '</b>'; return; }
          impMsg.innerHTML = '<b class="opt-good">imported — ' + j.created + ' new, ' +
            j.merged + ' merged, ' + j.tracks + ' track link(s)</b>';
          window.vibeLoadVibes();
        });
      }).catch(function () { impMsg.innerHTML = '<b class="opt-bad">import failed</b>'; });
      impFile.value = '';
    };

    // Select a tile to expand it, one at a time, matching the Genres tab
    // (wireTileToggle, app.js).
    window.wireTileToggle(body, body.querySelectorAll('.vib-key .gen-tile'), openCard);
  }

  /* Everything that needs the card to be visible first: sizing the textarea to
     its content only works once it has a layout, and the member list is a
     request we should not make for 40 collapsed cards. */
  function openCard(cardEl) {
    var id = cardEl.dataset.id;
    var ta = cardEl.querySelector('.vib-note');
    var msg = cardEl.querySelector('.vib-msg');
    var actMsg = cardEl.querySelector('.vib-act-msg');
    var name = cardEl.querySelector('.gen-name').textContent;

    // grow to fit rather than scrolling inside a fixed box
    var grow = function () { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; };
    grow();
    ta.oninput = grow;

    cardEl.querySelector('.vib-save').onclick = function () {
      fetch('/vibes/' + id + '/description', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: ta.value })
      }).then(function (r) { return r.json(); }).then(function (j) {
        msg.innerHTML = '<b class="opt-good">' +
          (j.length ? 'saved · ' + j.length + ' characters' : 'cleared') + '</b>';
      }).catch(function () { msg.innerHTML = '<b class="opt-bad">save failed</b>'; });
    };

    cardEl.querySelector('.vib-rename').onclick = function () {
      var next = window.prompt('New name for this vibe:', name);
      if (!next || !next.trim() || next.trim() === name) return;
      fetch('/vibes/rename', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vibe_id: Number(id), name: next.trim() })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { actMsg.innerHTML = '<b class="opt-bad">' + esc(j.error) + '</b>'; return; }
        window.vibeLoadVibes(j.name);
      }).catch(function () { actMsg.innerHTML = '<b class="opt-bad">rename failed</b>'; });
    };

    cardEl.querySelector('.vib-clear').onclick = function () {
      if (!window.confirm('Remove every track from "' + name + '"?\n\nThe vibe itself and its ' +
          'notes are kept, and no music files are touched — only the list of which tracks ' +
          'belong to it.')) return;
      fetch('/vibes/clear', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vibe_id: Number(id) })
      }).then(function (r) { return r.json(); }).then(function () {
        window.vibeLoadVibes(name);
      }).catch(function () { actMsg.innerHTML = '<b class="opt-bad">could not clear</b>'; });
    };

    cardEl.querySelector('.vib-delete').onclick = function () {
      if (!window.confirm('Delete the vibe "' + name + '"?\n\nIts notes and its list of tracks ' +
          'are gone for good. Your music files are not touched, and the tracks stay in your ' +
          'library.')) return;
      fetch('/vibes/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vibe_id: Number(id) })
      }).then(function (r) { return r.json(); }).then(function () {
        window.vibeLoadVibes();
      }).catch(function () { actMsg.innerHTML = '<b class="opt-bad">could not delete</b>'; });
    };

    var members = cardEl.querySelector('.vib-members');
    fetch('/vibes/' + id + '/members').then(function (r) { return r.json(); })
      .then(function (list) {
        var items = (list || []).slice(0, 200);
        if (!items.length) {
          members.innerHTML = '<div class="opt-note">No tracks yet. Add them from the ' +
            '<b>Map</b> or the <b>Analyzer</b> — click a track and pick this vibe.</div>';
          return;
        }
        members.innerHTML = '<ol class="gen-top">' + items.map(function (m) {
          return '<li>' + esc(m.title || m.hash) +
            (m.weight && m.weight !== 1 ? ' <i>×' + m.weight + '</i>' : '') + '</li>';
        }).join('') + '</ol>' +
        (list.length > items.length
          ? '<div class="opt-note">showing the first 200 of ' + list.length + '</div>' : '');
      }).catch(function () {
        members.innerHTML = '<div class="opt-note">could not load tracks</div>';
      });
  }

  /* `keep` re-opens the named card after a reload, so renaming or clearing a
     vibe doesn't drop you back at the top of the page. */
  window.vibeLoadVibes = function (keep) {
    body = document.getElementById('vib-body');
    if (!body) return;
    body.innerHTML = 'Loading…';
    fetch('/vibes').then(function (r) { return r.json(); }).then(function (vibes) {
      render(vibes || []);
      if (!keep) return;
      var tiles = body.querySelectorAll('.vib-key');
      for (var i = 0; i < tiles.length; i++) {
        if (tiles[i].querySelector('.gen-name').textContent === keep) {
          tiles[i].querySelector('.gen-tile').click();
          tiles[i].scrollIntoView({ block: 'nearest' });
          return;
        }
      }
    }).catch(function () {
      body.innerHTML = '<div class="opt-card">Could not load vibes.</div>';
    });
  };
})();

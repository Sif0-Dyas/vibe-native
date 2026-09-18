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

  /* The user's taxonomy edits, loaded alongside the genre list. Held here rather
     than re-fetched per card so a page of 18 cards costs one request. */
  var OVERLAY = { archgenre: {}, colors: {} };
  var ARCHGENRES = [];
  var OVERLAY_PATH = '';
  var PALETTES = { current: 'studio', presets: [] };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function bpmCell(b) {
    if (!b) return '';
    // No canonical range means there is nothing conventional to compare against
    // -- true for every subgenre, and for the non-electronic keystones where
    // tempo is not how the genre is defined. Say nothing rather than "typical —".
    var can = b.canonical ? b.canonical[0] + '–' + b.canonical[1] : null;
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
    return '<div class="gen-bpm">' +
           (can ? '<span class="gk">typical</span> ' + esc(can) : '') +
           '<span class="gk">yours</span> ' + obs + flag + '</div>';
  }

  /* The tile's waveform mark. Lives in app.js so the Vibes tab draws exactly
     the same mark from the same seed -- see vibeWaveSvg there. */
  var waveSvg = window.vibeWaveSvg;

  /* The most representative tracks of a card, as list items. */
  function topList(tracks) {
    return (tracks || []).map(function (t) {
      return '<li>' + esc(t.title) + (t.bpm ? ' <i>' + Math.round(t.bpm) + '</i>' : '') + '</li>';
    }).join('');
  }

  /* Where this genre sits, and what colour it gets -- the two things the built-in
     tables decide that only the person with the library can correct.

     Saved to a JSON file beside settings.ini, NOT to the database: the database
     gets thrown away and rebuilt on every re-scan, and a placement that died
     with it would have to be re-entered each time. */
  function placementRow(k) {
    var opts = ['<option value="">— stands alone (its own archgenre) —</option>'].concat(
      ARCHGENRES.filter(function (a) { return a !== k.keystone; }).map(function (a) {
        return '<option value="' + esc(a) + '"' +
          (OVERLAY.archgenre[k.keystone] === a || (!(k.keystone in OVERLAY.archgenre) && k.archgenre === a && k.tier !== 'archgenre')
            ? ' selected' : '') + '>' + esc(a) + '</option>';
      })
    ).join('');
    var edited = (k.keystone in OVERLAY.archgenre) || (k.keystone in OVERLAY.colors);
    return '<div class="gen-place" data-g="' + esc(k.keystone) + '">' +
      '<span class="gk">sits under</span>' +
      '<select class="place-arch">' + opts + '</select>' +
      '<span class="gk">colour</span>' +
      '<input class="place-col" type="color" value="' + esc(k.color || '#888888') + '">' +
      (edited ? '<button class="place-clear" title="back to the built-in default">reset</button>' : '') +
      '<span class="place-say"></span>' +
    '</div>';
  }

  /* Persist one placement edit, then reload so every tier heading, grouping and
     colour on the page follows -- moving a keystone changes the section it is
     listed under, which a local repaint cannot show. */
  function savePlacement(box) {
    var genre = box.dataset.g;
    var say = box.querySelector('.place-say');
    var patch = { archgenre: {}, colors: {} };
    patch.archgenre[genre] = box.querySelector('.place-arch').value;
    patch.colors[genre] = box.querySelector('.place-col').value;
    say.textContent = 'saving…'; say.className = 'place-say';
    fetch('/taxonomy/overlay', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch)
    }).then(function (r) { return r.json(); }).then(function (j) {
      OVERLAY = j.overlay || OVERLAY;
      load(genre);
    }).catch(function () { say.textContent = 'save failed'; say.className = 'place-say bad'; });
  }

  function clearPlacement(box) {
    var genre = box.dataset.g;
    fetch('/taxonomy/overlay', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archgenre: (function (o) { o[genre] = null; return o; })({}),
                             colors: (function (o) { o[genre] = null; return o; })({}) })
    }).then(function (r) { return r.json(); }).then(function (j) {
      OVERLAY = j.overlay || OVERLAY;
      load(genre);
    }).catch(function () { /* the page is still consistent; the next load retries */ });
  }

  function keystoneCard(k) {
    var kids = k.subgenres || [];
    var chip = function (s) {
      return '<span class="gen-sub">' + esc(s.style) + '<i>' + s.count + '</i></span>';
    };
    var subs = kids.slice(0, 14).map(chip).join('');
    // The first few ride on the COLLAPSED tile. Seeing what is inside a genre is
    // the main reason to look at this tab, and hiding it behind a click made
    // whole archgenres read as childless.
    var TILE_SUBS = 5;
    var tileSubs = (k.tier === 'archgenre') ? '' : kids.length
      ? '<span class="gen-subrow">' + kids.slice(0, TILE_SUBS).map(chip).join('') +
        (kids.length > TILE_SUBS
          ? '<span class="gen-submore">+' + (kids.length - TILE_SUBS) + ' more</span>' : '') +
        '</span>'
      : '';
    var top = topList(k.top);
    var o = (k.bpm && k.bpm.observed) || null;
    var avg = o ? o.median : null;
    var tr = k.training || { state: 'sparse', files: 0, needs: 20 };
    // Pulse the border on the beat, in the genre's colour. Subtle: a page of 18
    // cards each at its own tempo would strobe if this were high contrast.
    var beat = avg ? (60 / avg).toFixed(3) + 's' : null;
    var pulse = beat ? ' style="--gen-beat:' + beat + ';--gen-col:' + esc(k.color) + '"' : '';

    var sig = k.signature || '4/4';
    var feel = k.feel || '';
    // Nearly every electronic genre is 4/4, so the signature alone separates
    // nothing. `feel` is what actually differs -- Dubstep and Drum n Bass are
    // both 4/4 but one is halftime and the other a breakbeat -- so it rides on
    // the tile next to the meter rather than hiding in the opened detail.
    var isArch = (k.tier === 'archgenre');

    // Tile = always visible. Detail = revealed on select, and the tile then
    // spans the full grid row so the detail has real width instead of being
    // squeezed into a column.
    return '<div class="gen-key' + (beat ? ' pulsing' : '') + '"' + pulse +
        ' data-g="' + esc(k.keystone) + '">' +
      '<button class="gen-tile" type="button">' +
        '<span class="gen-wavebox" style="border-color:' + esc(k.color) + '55">' +
          waveSvg(k.color, k.keystone) + '</span>' +
        '<span class="gen-titles">' +
          '<span class="gen-name">' + esc(k.keystone) + '</span>' +
          '<span class="gen-level' + (isArch ? ' is-arch' : '') + '" title="' +
            (isArch ? 'A top-level genre — nothing sits above it in the family tree'
                    : 'A main genre that sits under a broader archgenre') + '">' +
            esc(k.tier || 'keystone') + '</span>' +
        '</span>' +
        '<span class="gen-tilemeta">' +
          '<span class="gen-bpmbig">' + (avg ? Math.round(avg) : '—') + '<i>bpm</i></span>' +
        '</span>' +
        tileSubs +
        '<span class="gen-tilefoot">' +
          '<span class="gen-sig" title="Time signature — how the beats are counted. ' +
            'Almost all dance music is 4/4.">' + esc(sig) + '</span>' +
          (feel ? '<span class="gen-feelchip" title="The rhythm this genre is built on">' +
                    esc(feel) + '</span>' : '') +
          '<span class="vib-state ' +
            (tr.state === 'ready' ? 'ok' : tr.state === 'thin' ? 'warn' : 'bad') + '">' +
            esc(tr.state) + '</span>' +
          '<span class="gen-count">' + k.count + '</span>' +
        '</span>' +
      '</button>' +
      '<div class="gen-detail" hidden>' +
        (k.blurb ? '<p class="gen-blurb">' + esc(k.blurb) + '</p>' : '') +
        (feel ? '<div class="gen-feel"><span class="gk">feel</span> ' + esc(feel) +
                '<span class="gk">signature</span> ' + esc(sig) + '</div>' : '') +
        bpmCell(k.bpm) +
        '<div class="gen-card-stats">' +
          '<span class="gen-statlab">' + tr.files + ' training file' +
            (tr.files === 1 ? '' : 's') +
            (tr.needs ? ' · needs ' + tr.needs + ' more' : ' · ready') + '</span>' +
        '</div>' +
        (subs ? '<div class="gen-block">' +
                  '<div class="gen-toph">subgenres in your library</div>' +
                  '<div class="gen-subs">' + subs + '</div>' +
                '</div>' : '') +
        (top ? '<div class="gen-block">' +
                 '<div class="gen-toph">top tracks</div>' +
                 '<ol class="gen-top">' + top + '</ol>' +
               '</div>' : '') +
        placementRow(k) +
        '<div class="gen-actions">' +
          '<button class="gen-train" data-g="' + esc(k.keystone) + '">train</button>' +
          '<button class="gen-reset-top" data-g="' + esc(k.keystone) + '">reset</button>' +
        '</div>' +
        '<div class="gen-panel" hidden></div>' +
      '</div>' +
    '</div>';
  }

  function subgenreCard(sg, parent) {
    var o = (sg.bpm && sg.bpm.observed) || null;
    var avg = o ? o.median : null;
    var beat = avg ? (60 / avg).toFixed(3) + 's' : null;
    var col = sg.color || parent.color || '#888888';
    var pulse = beat ? ' style="--gen-beat:' + beat + ';--gen-col:' + esc(col) + '"' : '';
    var top = topList(sg.top);
    return '<div class="gen-key gen-subcard' + (beat ? ' pulsing' : '') + '"' + pulse +
        ' data-g="' + esc(sg.style) + '">' +
      '<button class="gen-tile" type="button">' +
        '<span class="gen-wavebox" style="border-color:' + esc(col) + '55">' +
          waveSvg(col, sg.style) + '</span>' +
        '<span class="gen-titles">' +
          '<span class="gen-name">' + esc(sg.style) + '</span>' +
          '<span class="gen-level" title="A subgenre of ' + esc(parent.keystone) +
            '">subgenre</span>' +
        '</span>' +
        '<span class="gen-tilemeta">' +
          '<span class="gen-bpmbig">' + (avg ? Math.round(avg) : '—') + '<i>bpm</i></span>' +
        '</span>' +
        '<span class="gen-tilefoot">' +
          '<span class="gen-sub-parent">in ' + esc(parent.keystone) + '</span>' +
          '<span class="gen-count">' + sg.count + '</span>' +
        '</span>' +
      '</button>' +
      '<div class="gen-detail" hidden>' +
        '<div class="gen-block">' +
          bpmCell(sg.bpm) +
        '</div>' +
        (top ? '<div class="gen-block">' +
                 '<div class="gen-toph">top tracks</div>' +
                 '<ol class="gen-top">' + top + '</ol>' +
               '</div>' : '') +
        '<div class="opt-note gen-subnote">A subgenre of <b>' + esc(parent.keystone) +
          '</b>. Placement, colour and training are set on ' + esc(parent.keystone) +
          '’s own card — everything under it follows.</div>' +
      '</div>' +
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

  /* Plain-language opener. This is the first thing a new user reads on the tab,
     so it explains the words the rest of the page uses before using them. */
  function howCard() {
    return '<div class="opt-card gen-how collapsed"><h3>How this works</h3>' +
      '<div class="opt-note">' +
      'Vibedentify listens to each track and works out what <b>genre</b> it is. ' +
      'Genres are arranged in a tree, from broadest to most specific:' +
      '<div class="gen-tree-key">' +
        '<span><b>Archgenre</b><i>the widest bucket &mdash; e.g. <em>Bass Music</em></i></span>' +
        '<span><b>Genre</b><i>what a track actually <em>is</em> &mdash; e.g. <em>Dubstep</em></i></span>' +
        '<span><b>Subgenre</b><i>the fine detail &mdash; e.g. <em>Riddim</em></i></span>' +
      '</div>' +
      'Some genres are big enough to be an archgenre <em>and</em> a genre at the same ' +
      'time &mdash; House and Trance, for instance. Those are marked ' +
      '<span class="gen-level is-arch">archgenre</span> on their card.<br><br>' +
      '<b>Each card below is one genre.</b> Click it to open it: what the genre is, how ' +
      'fast it normally runs against how fast <em>your</em> copies actually measure, your ' +
      'best tracks in it, and controls to move or recolour it. A card&rsquo;s border blinks ' +
      'in time with that genre&rsquo;s typical tempo.<br><br>' +
      '<b>Why a track can have two genres.</b> A track gets a second genre when the ' +
      'runner-up scores at least 35% &mdash; real records do sit between two sounds. Where ' +
      'the blend has a known name it is used (Dubstep + Drum n Bass = Drumstep); otherwise ' +
      'the two names are joined with a slash.<br><br>' +
      '<b>Why some genres share a colour.</b> Only eight can carry a clearly distinct ' +
      'colour &mdash; past that the eye stops telling them apart reliably. The rest use a ' +
      'neutral tone, and you read them from their position and label instead. Anything ' +
      'that is not electronic music collapses into <b>Other</b>, since this is built for ' +
      'an electronic library.' +
      '</div></div>';
  }

  /* Total genres -- the whole library counted in one place: how many genres you
     have, how many tracks sit in each, and what slice of the collection that is.
     Counted at the keystone tier, because that is the level a person means when
     they say "genre". */
  function statsCard(families) {
    var rows = [];
    families.forEach(function (f) {
      (f.keystones || []).forEach(function (k) {
        rows.push({ name: k.keystone, count: k.count, color: k.color || '#888888',
                    tier: k.tier });
      });
    });
    var total = rows.reduce(function (a, r) { return a + r.count; }, 0);
    rows.sort(function (a, b) { return b.count - a.count; });
    var top = rows.length ? rows[0] : null;
    rows.forEach(function (r) {
      r.badge = r.tier === 'archgenre' ? '<span class="gen-level is-arch">arch</span>' : '';
      r.title = r.name + ' — ' + r.count + ' track' + (r.count === 1 ? '' : 's') + ', ' +
        (total ? (r.count / total) * 100 : 0).toFixed(1) + '% of your library';
    });
    var list = window.statRowsHtml(rows, total);

    return '<div class="opt-card"><h3>Total genres</h3>' +
      '<div class="gen-bigstats">' +
        '<div class="gen-bigstat"><b>' + rows.length + '</b><i>genres in your library</i></div>' +
        '<div class="gen-bigstat"><b>' + total + '</b><i>tracks analysed</i></div>' +
        '<div class="gen-bigstat"><b>' + families.length + '</b><i>archgenre groups</i></div>' +
        (top ? '<div class="gen-bigstat"><b>' + esc(top.name) + '</b><i>your biggest genre, ' +
          (total ? Math.round(top.count / total * 100) : 0) + '% of the library</i></div>' : '') +
      '</div>' +
      (list ? '<div class="gen-stats">' + list + '</div>'
            : '<div class="opt-note">Nothing analysed yet. Drop some music into the ' +
              '<b>Analyzer</b> tab and this fills in.</div>') +
      '<div class="opt-note">Percentages are of every analysed track. A track that reads ' +
      'as two genres counts under whichever one it matches most strongly, so these add up ' +
      'to 100%.</div>' +
    '</div>';
  }

  function render(families) {
    body.innerHTML =
      // Order: explain it, then summarise it, then show it, then let them change
      // it. Actions and appearance sit at the bottom because they are the rarest
      // thing anyone opens this tab to do.
      howCard() +
      statsCard(families) +
      '<h2 class="gen-sechd">Genres<span>every genre found in your library, grouped by ' +
        'archgenre</span></h2>' +
      families.map(function (f) {
        var name = f.archgenre || f.family;
        var solo = f.standalone && f.keystones.length === 1;
        // The heading used to be dropped for a standalone archgenre because it
        // repeats the single card beneath it. But that heading is the ONLY place
        // the archgenre tier is stated, so House and Trance read as ordinary
        // genres. Keep it, and say plainly why the name appears twice.
        return '<div class="opt-card gen-fam">' +
          '<h3>' + esc(name) + ' <span class="gen-n">' + f.count +
            ' \u00b7 ' + Math.round(f.share * 100) + '% \u00b7 archgenre' +
            (solo ? ' &amp; genre' : '') + '</span></h3>' +
          (solo ? '<div class="opt-note gen-solonote">' + esc(name) + ' is broad enough to be ' +
            'a top-level archgenre <em>and</em> a genre in its own right, so it appears at ' +
            'both levels.</div>' : '') +
          '<div class="gen-keys">' +
            f.keystones.map(keystoneCard).join('') +
            // A standalone archgenre IS its only keystone, so the genres it
            // contains are that keystone's subgenres. Promote them to cards so
            // this section lists what it holds, exactly as a multi-keystone
            // archgenre like Bass already does.
            (solo ? (f.keystones[0].subgenres || [])
                      .map(function (sg) { return subgenreCard(sg, f.keystones[0]); })
                      .join('')
                  : '') +
          '</div>' +
        '</div>';
      }).join('') +
      '<h2 class="gen-sechd">Library actions &amp; taxonomy edits' +
        '<span>re-run the classifier, and keep your own corrections</span></h2>' +
      '<div class="opt-card"><h3>Re-label your library</h3>' +
        '<div class="opt-row"><span class="k">Status</span>' +
          '<span class="v" id="gen-rl-stat">—</span></div>' +
        '<div class="opt-note">When you teach Vibedentify a genre (the <b>train</b> button on ' +
        'any genre card), tracks you analysed <i>before</i> that still carry their old genre. ' +
        'Re-labelling re-reads them using what it has learned since. It does not re-scan and ' +
        'it never touches your audio files.<br><br>' +
        '<b>Always press preview first.</b> It reports how many tracks would change without ' +
        'changing anything. Applying takes a snapshot first, and <b>undo</b> puts everything ' +
        'back.</div>' +
        '<div class="opt-actions">' +
          '<button id="gen-rl-preview">1 \u00b7 preview</button>' +
          '<button id="gen-rl-apply" disabled>2 \u00b7 apply</button>' +
          '<button id="gen-rl-revert">undo</button>' +
          '<button id="gen-snap">snapshot now</button>' +
        '</div>' +
        '<div class="opt-note" id="gen-msg"></div>' +
      '</div>' +
      // Where the edits live. Worth stating plainly: this file is the reason a
      // placement survives nuking the database, and it can be edited by hand or
      // copied to another machine -- neither of which is discoverable otherwise.
      '<div class="opt-card"><h3>Your taxonomy edits</h3>' +
        '<div class="opt-note">Moved a genre under a different archgenre, or given it your own ' +
        'colour? Those changes are yours, and they live in a plain text file at ' +
        '<code>' + esc(OVERLAY_PATH || 'taxonomy.json') + '</code> &mdash; <i>outside</i> the ' +
        'database, so re-scanning your whole collection will not wipe them. It stores only what ' +
        'you changed; everything else follows the built-in tables. Safe to open in a text ' +
        'editor, back up, or copy to another computer.</div>' +
        '<div class="opt-actions"><button id="gen-tax-reset">reset all my edits</button></div>' +
        '<div class="opt-note" id="gen-tax-msg"></div>' +
      '</div>' +
      paletteCard();
    wireActions();
    // one console per keystone card, built on demand -- each is several queries
    // Select a tile to expand it, one at a time (wireTileToggle, app.js).
    window.wireTileToggle(body, body.querySelectorAll('.gen-tile'));
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
    body.querySelectorAll('.pal').forEach(function (b2) {
      b2.onclick = function () {
        if (b2.dataset.p === PALETTES.current) return;
        fetch('/palettes/' + encodeURIComponent(b2.dataset.p), { method: 'POST' })
          .then(function (r) { return r.json(); }).then(function (j) {
            if (j.current) PALETTES.current = j.current;
            load();
          }).catch(function () {});
      };
    });
    var taxReset = document.getElementById('gen-tax-reset');
    if (taxReset) taxReset.onclick = function () {
      var el = document.getElementById('gen-tax-msg');
      var word = window.prompt(
        'Discard every taxonomy edit and go back to the built-in tables?' +
        '\n\nThe file is renamed, not deleted, so this is recoverable.' +
        '\n\nType RESET to confirm:');
      if (!word) return;
      fetch('/taxonomy/overlay/reset', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: word })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { el.innerHTML = '<b class="opt-bad">' + esc(j.error) + '</b>'; return; }
        load();
      }).catch(function () { el.innerHTML = '<b class="opt-bad">reset failed</b>'; });
    };

    // Placement: the archgenre a keystone sits under and the colour it carries.
    // Both save on change -- there is no Save button because there is nothing to
    // batch, and a forgotten one would silently lose the edit.
    body.querySelectorAll('.gen-place').forEach(function (box) {
      box.querySelector('.place-arch').onchange = function () { savePlacement(box); };
      box.querySelector('.place-col').onchange = function () { savePlacement(box); };
      var clr = box.querySelector('.place-clear');
      if (clr) clr.onclick = function () { clearPlacement(box); };
      // Clicking inside the row must not toggle the card shut underneath it.
      box.onclick = function (e) { e.stopPropagation(); };
    });
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

  /* The colour-scheme picker. Each preset shows its swatches and how well it
     actually separates -- the schemes are NOT equally readable, and a picker
     that hid that would be pretending otherwise. Nothing here is destructive:
     switching back is one click, and per-genre colours survive a switch. */
  function paletteCard() {
    var rows = (PALETTES.presets || []).map(function (p) {
      var sep = p.separation || {};
      var swatches = (p.colors || []).map(function (c) {
        return '<i title="' + esc(c.keystone) + '" style="background:' + esc(c.color) + '"></i>';
      }).join('');
      var on = p.name === PALETTES.current;
      return '<button class="pal' + (on ? ' on' : '') + '" data-p="' + esc(p.name) + '">' +
        '<span class="pal-head">' +
          '<span class="pal-name">' + esc(p.label) + '</span>' +
          (on ? '<span class="pal-on">in use</span>' : '') +
          '<span class="pal-sep ' + esc(sep.verdict || '') + '">' +
            (sep.worst == null ? '—' : 'ΔE ' + sep.worst) +
            (sep.verdict ? ' · ' + esc(sep.verdict) : '') + '</span>' +
        '</span>' +
        '<span class="pal-swatches">' + swatches + '</span>' +
        '<span class="pal-blurb">' + esc(p.blurb) + '</span>' +
      '</button>';
    }).join('');
    return '<div class="opt-card"><h3>Colour scheme</h3>' +
      '<div class="opt-note">Applies to every genre at once. A colour you set on a ' +
      'single card overrides the scheme and survives switching between them. ' +
      '<b>ΔE</b> is how far apart the closest two colours are — bigger is easier to ' +
      'tell apart, and the verdict compares each scheme to the default rather than ' +
      'to an absolute line (no scheme separates every pair; that is a property of ' +
      'colour, not a bug).</div>' +
      '<div class="pals">' + rows + '</div>' +
    '</div>';
  }

  /* Reload the whole tab. `keep` re-opens the card that was just edited, so
     changing a genre's placement doesn't drop you back at the top of the page. */
  function load(keep) {
    body = document.getElementById('gen-body');
    if (!body) return;
    body.innerHTML = 'Loading…';
    Promise.all([
      fetch('/genres?top=5&by=archgenre').then(function (r) { return r.json(); }),
      fetch('/training/status').then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; }),
      fetch('/taxonomy/overlay').then(function (r) { return r.json(); })
        .catch(function () { return null; }),
      fetch('/palettes').then(function (r) { return r.json(); })
        .catch(function () { return null; })
    ]).then(function (out) {
      var groups = out[0] || [], st = out[1], tx = out[2], pal = out[3];
      if (pal) PALETTES = pal;
      if (tx) {
        OVERLAY = tx.overlay || OVERLAY;
        OVERLAY.archgenre = OVERLAY.archgenre || {};
        OVERLAY.colors = OVERLAY.colors || {};
        ARCHGENRES = tx.archgenres || ARCHGENRES;
        OVERLAY_PATH = tx.path || '';
      }
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
      if (keep) {
        var card = body.querySelector('.gen-key[data-g="' + keep.replace(/"/g, '\\"') + '"]');
        if (card) {
          var tile = card.querySelector('.gen-tile');
          if (tile) tile.click();
          card.scrollIntoView({ block: 'nearest' });
        }
      }
    }).catch(function () {
      body.innerHTML = '<div class="opt-card">Could not load the genre taxonomy.</div>';
    });
  }

  window.vibeLoadGenres = function () { load(); };
})();

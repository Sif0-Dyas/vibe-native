/* ---- the Correct panel ------------------------------------------------------
   The one place a track's genre is corrected: the same panel on every Analyzer
   row and in the Map popup. Three tools, each showing its current value, with a
   Reset and a hint that says what it does and how it differs from the others:

     Whole track  one genre, replaces the read   POST / DELETE /override/<h>
     Sections     a genre for a time range       POST /override_segment,
                                                 DELETE /override_segment/<id>
     Balance      nudge several genres           GET / POST /weights/<h>

   There used to be three ways in -- an override box, a Shift-drag on the
   waveform, an adjust panel -- each with its own idea of undo (none at all,
   Shift-click, pressing every button back). This is all of them.

   `wireCorrectPanel(btn, box, opts)` -> {open(prefill), close()}. What each
   place supplies:
     hashOf()            the track's hash, or null (a just-dropped row learns it later)
     onIdentity(fields)  the server's identity after any change (style.identity_fields)
     onSegments(list)    the sections changed: [{id, start_s, end_s, genre}]
     drawRange(done)     optional: arm the host's own waveform for one drag, then
                         done(start_s, end_s), or done(null) for a click that was
                         not a drag. Returns a function that disarms it. Without
                         it the panel draws its own strip to drag on.
     cands()             the runner-up reads, offered as one-click Whole-track choices
     genres()            extra names for the genre boxes' completion
     complete(text)      a completer for Tab in the genre boxes
     afterWhole(g, j)    after a Whole-track set (the Analyzer files a dropped
                         track's training copy, which the server cannot)
     onOpen(), onClose() */

import { escapeHtml, fillGenreList, fmtTime } from './app.js';
import { hooks } from './hooks.js';

// The words the panel shows, and the words docs/USAGE.md uses for the same tools.
const HINTS = {
  whole: 'One genre for the whole track. Replaces the read everywhere — use Balance if the read is mostly right.',
  sections: 'A genre for part of the track, drawn on the waveform. Several allowed; the rest of the track keeps its read.',
  balance: 'Nudge several genres up or down. The track stays multi-genre — nothing is replaced.',
};

const genreInput = (cls, placeholder) =>
  `<input class="${cls}" type="text" list="ovr-genre-list" autocomplete="off" spellcheck="false"` +
  ` placeholder="${placeholder}">`;

const head = title =>
  `<div class="cor-head"><span class="cor-title">${title}</span><span class="cor-now"></span>` +
  `<button class="cor-reset" type="button" disabled>Reset</button></div>`;

function correctPanelHtml(){
  return `
    <section class="cor-sec cor-whole">
      ${head('Whole track')}
      <div class="cor-hint">${HINTS.whole}</div>
      <div class="cor-cands"></div>
      <div class="cor-line">${genreInput('cor-in cor-whole-in', 'a genre, e.g. Riddim')}
        <button class="cor-btn cor-whole-set" type="button">Set</button></div>
      <div class="cor-msg"></div>
    </section>
    <section class="cor-sec cor-sections">
      ${head('Sections')}
      <div class="cor-hint">${HINTS.sections}</div>
      <div class="cor-seglist"></div>
      <canvas class="cor-strip" hidden></canvas>
      <div class="cor-line cor-seg-new" hidden><span class="cor-range"></span>
        ${genreInput('cor-in cor-seg-in', 'genre for this section')}
        <button class="cor-btn cor-seg-apply" type="button">Apply</button>
        <button class="cor-btn cor-seg-cancel" type="button">Cancel</button></div>
      <div class="cor-line"><button class="cor-btn cor-seg-add" type="button">＋ add section</button></div>
      <div class="cor-msg"></div>
    </section>
    <section class="cor-sec cor-balance">
      ${head('Balance')}
      <div class="cor-hint">${HINTS.balance}</div>
      <div class="cor-note" hidden>Whole track is set, so the track reads as that one genre.
        Balance is kept, and shows again once Whole track is reset.</div>
      <div class="adj-rows"><span class="pop-bar">…</span></div>
      <div class="cor-line">${genreInput('cor-in adj-add-in', 'add a genre it missed…')}
        <button class="cor-btn adj-add" type="button">add</button></div>
      <div class="cor-msg"></div>
    </section>
    <div class="cor-foot"><button class="cor-btn cor-close" type="button">Done</button></div>`;
}

const api = (url, init) => fetch(url, init).then(async r => {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
});
const postJson = (url, body) => api(url, {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

// Tab completes to the first known genre that starts with what's typed -- only
// when there is one, so Tab still moves focus otherwise.
function tabComplete(input, complete){
  input.addEventListener('keydown', e => {
    if (e.key !== 'Tab' || !input.value.trim() || !complete) return;
    const hit = complete(input.value);
    if (hit && hit.toLowerCase() !== input.value.trim().toLowerCase()){
      e.preventDefault(); input.value = hit; input.setSelectionRange(hit.length, hit.length);
    }
  });
}

/* Run `repaint` without moving `el` on screen. The host repaints what sits above
   the panel after every change -- an adjusted read lists each of its genres, so
   the row's genre summary can gain a line -- and that pushed the panel, and the
   +/- button under a still cursor, down one row between two clicks. Whatever
   scrolls (the page, the popup) scrolls back by the same amount. */
function holdStill(el, repaint){
  const before = el.getBoundingClientRect().top;
  repaint();
  const shift = el.getBoundingClientRect().top - before;
  if (Math.abs(shift) < 1) return;
  for (let p = el.parentElement; p; p = p.parentElement){
    const oy = getComputedStyle(p).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight){ p.scrollTop += shift; return; }
  }
  window.scrollBy(0, shift);
}

/* ---- Balance: each genre carries a step you raise or lower -----------------
   "This is a VERY house track" and "that Tech Trance is a misread" are both
   sayable without flattening the rest to zero. The step is what's stored, never
   the multiplier it computes -- the server can retune the curve without
   silently rewriting what you meant by it. */
function wireBalance(sec, ctx){
  const rowsEl = sec.querySelector('.adj-rows');
  const addIn = sec.querySelector('.adj-add-in');
  let state = null;      // {steps, drops, base, adjusted, max_step, words}
  let saving = null;     // in-flight POST, so rapid presses coalesce in order
  // The row order, fixed when the panel opens. Sorting by share after every
  // press slid a different genre under the cursor between two clicks; the
  // percentages move, the rows don't, and reopening re-sorts.
  let order = [];

  const wordFor = st => (state && state.words && state.words[String(st)]) || 'as read';
  const edited = () => !!state && (Object.keys(state.steps || {}).length > 0 || (state.drops || []).length > 0);

  function render(){
    ctx.changed();
    if (!state){ rowsEl.innerHTML = `<span class="pop-bar">…</span>`; return; }
    const drops = state.drops || [];
    const shown = new Map();
    for (const e of state.adjusted || []) shown.set(e.style, e.score);
    // A genre pushed all the way down falls out of the top-N. Keep its row on
    // screen anyway, or the press that removed it leaves nothing to undo it with.
    for (const g of Object.keys(state.steps || {})) if (!shown.has(g)) shown.set(g, 0);
    for (const g of drops) shown.delete(g);          // removed: listed below instead
    for (const g of shown.keys()) if (!order.includes(g)) order.push(g);   // new ones go last
    const max = state.max_step || 3;
    const rowsHtml = order.filter(g => shown.has(g)).map(g => [g, shown.get(g)]).map(([style, score]) => {
      const step = (state.steps || {})[style] || 0;
      const pct = Math.round((score || 0) * 100);
      return `<div class="adj-row${step ? ' moved' : ''}" data-g="${escapeHtml(style)}">
        <button class="adj-step" data-d="-1" ${step <= -max ? 'disabled' : ''} title="less">−</button>
        <button class="adj-step" data-d="1" ${step >= max ? 'disabled' : ''} title="more">＋</button>
        <span class="adj-meter" title="${escapeHtml(style)} — ${escapeHtml(wordFor(step))}">
          <i style="width:${pct}%"></i>
          <b>${escapeHtml(style)}</b>${step ? `<em>${escapeHtml(wordFor(step))}</em>` : ''}
        </span>
        <span class="adj-pct">${pct}%</span>
        <button class="adj-drop" title="remove ${escapeHtml(style)} from this track">✕</button>
      </div>`;
    }).join('');
    // Removed genres are named, not merely gone: a remove you cannot see is a
    // remove you cannot undo.
    const dropHtml = drops.length
      ? `<div class="adj-dropped"><span class="ovr-h">removed</span>` +
        drops.map(g => `<button class="adj-restore" data-g="${escapeHtml(g)}"` +
          ` title="put ${escapeHtml(g)} back on this track">${escapeHtml(g)} ↩</button>`).join('') +
        `</div>`
      : '';
    if (!shown.size && !drops.length){
      rowsEl.innerHTML = `<div class="ovr-h">nothing read for this track</div>`;
      return;
    }
    rowsEl.innerHTML = rowsHtml + dropHtml;
    for (const b of rowsEl.querySelectorAll('.adj-step')){
      b.onclick = () => bump(b.closest('.adj-row').dataset.g, Number(b.dataset.d));
    }
    for (const b of rowsEl.querySelectorAll('.adj-drop')) b.onclick = () => drop(b.closest('.adj-row').dataset.g);
    for (const b of rowsEl.querySelectorAll('.adj-restore')) b.onclick = () => restore(b.dataset.g);
  }

  // Remove a genre outright. Not the same press as -3: "not at all" leaves it in
  // the read at a trace, this takes it off the track entirely.
  function drop(style){
    if (!state || (state.drops || []).includes(style)) return;
    state.drops = [...(state.drops || []), style];
    state.steps = {...(state.steps || {})};
    delete state.steps[style];             // "more of this" and "none of this" cannot both be meant
    render(); save();
  }
  function restore(style){
    if (!state) return;
    state.drops = (state.drops || []).filter(g => g !== style);
    render(); save();
  }
  // Optimistic: the meter moves on the press and the server's answer replaces it.
  function bump(style, delta){
    if (!state) return;
    const max = state.max_step || 3;
    const next = Math.max(-max, Math.min(max, ((state.steps || {})[style] || 0) + delta));
    state.steps = {...(state.steps || {})};
    if (next) state.steps[style] = next; else delete state.steps[style];
    render(); save();
  }
  function save(){
    const hash = ctx.hashOf();
    if (!hash || !state) return Promise.resolve();
    const steps = state.steps || {};
    const drops = state.drops || [];
    saving = (saving || Promise.resolve()).then(async () => {
      try {
        const body = await postJson(`/api/v1/weights/${hash}`, {steps, drops});
        ctx.identity(body);
        // Identity, not equality: a press during the round-trip replaced both
        // objects, and its own save is already queued behind this one.
        if (steps !== state.steps || drops !== state.drops) return;
        state.steps = body.steps || {};
        state.drops = body.drops || [];
        state.adjusted = (body.adjusted && body.adjusted.length) ? body.adjusted : state.base;
        render();
      } catch(err){ ctx.say(`couldn't save: ${err.message}`); }
    });
    return saving;
  }

  const addGenre = () => {
    const g = (ctx.complete && ctx.complete(addIn.value)) || (addIn.value || '').trim();
    if (!g || !state) return;
    addIn.value = '';
    // Enters at "moderately": a genre you had to type out is one you mean.
    if (!(state.steps || {})[g]){ state.steps = {...(state.steps || {}), [g]: 2}; render(); save(); }
  };
  sec.querySelector('.adj-add').onclick = addGenre;
  addIn.addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); addGenre(); } });
  tabComplete(addIn, ctx.complete);

  return {
    set(s){ state = s; order = []; render(); },      // on open: sorted by share, once
    edited,
    summary(){
      if (!state) return '';
      const moved = Object.keys(state.steps || {}).length, gone = (state.drops || []).length;
      if (!moved && !gone) return 'as read';
      return [moved && `${moved} nudged`, gone && `${gone} removed`].filter(Boolean).join(' · ');
    },
    steps: () => Object.keys((state && state.steps) || {}),
    reset(){
      if (!state) return Promise.resolve();
      state.steps = {}; state.drops = [];
      state.adjusted = state.base;
      render();
      return save();
    },
  };
}

/* The Map popup has no waveform of its own, so Sections brings one: the
   track's stored min/max envelope, its sections painted on top, and one drag
   to mark a new range. */
function stripDrawer(canvas, hashOf){
  let mm = null, dur = 0, spans = [], sel = null, done = null;
  const W = () => canvas.clientWidth || 280, H = () => canvas.clientHeight || 44;
  function paint(){
    const dpr = window.devicePixelRatio || 1, w = W(), h = H();
    canvas.width = w * dpr; canvas.height = h * dpr;
    const g = canvas.getContext('2d');
    g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
    const css = getComputedStyle(canvas);
    g.fillStyle = css.getPropertyValue('--dim').trim() || '#888';
    const mid = h / 2;
    if (mm && mm.max && mm.max.length){
      const n = mm.max.length;
      for (let x = 0; x < w; x++){
        const i = Math.min(n - 1, Math.floor(x / w * n));
        const top = Math.max(0, mm.max[i]), bot = Math.min(0, mm.min[i]);
        g.fillRect(x, mid - top * mid, 1, Math.max(1, (top - bot) * mid));
      }
    } else {
      g.fillRect(0, mid - 1, w, 2);         // no envelope reachable: a time line still works
    }
    g.globalAlpha = 0.35; g.fillStyle = css.getPropertyValue('--accent-a').trim() || '#56b4e9';
    if (dur) for (const s of spans) g.fillRect(s.start_s / dur * w, 0, Math.max(1, (s.end_s - s.start_s) / dur * w), h);
    if (sel){
      g.globalAlpha = 0.22; g.fillStyle = '#78c8ff';
      const a = Math.min(sel.a, sel.b) * w, b = Math.max(sel.a, sel.b) * w;
      g.fillRect(a, 0, Math.max(1, b - a), h);
    }
    g.globalAlpha = 1;
  }
  const frac = x => { const r = canvas.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)); };
  canvas.addEventListener('pointerdown', e => {
    if (!done) return;
    canvas.setPointerCapture(e.pointerId);
    sel = {a: frac(e.clientX), b: frac(e.clientX)}; paint();
  });
  canvas.addEventListener('pointermove', e => { if (sel){ sel.b = frac(e.clientX); paint(); } });
  canvas.addEventListener('pointerup', e => {
    if (!sel || !done) return;
    sel.b = frac(e.clientX);
    const a = Math.min(sel.a, sel.b), b = Math.max(sel.a, sel.b), cb = done;
    sel = null; done = null; canvas.classList.remove('drawing'); paint();
    cb((b - a) * dur < 0.5 ? null : a * dur, b * dur);
  });
  return {
    async show(duration, sections){
      dur = duration || 0; spans = sections; canvas.hidden = false; paint();
      if (mm) return;
      const h = hashOf();
      try { const r = await fetch(`/api/v1/waveform/${h}`); if (r.ok) mm = await r.json(); }
      catch(_){ /* the time line stands */ }
      paint();
    },
    sections(list){ spans = list; if (!canvas.hidden) paint(); },
    arm(cb){ done = cb; canvas.classList.add('drawing'); },
    disarm(){ if (done){ const cb = done; done = null; sel = null; canvas.classList.remove('drawing'); paint(); cb(null); } },
  };
}

function wireCorrectPanel(btn, box, opts){
  box.classList.add('cor');
  box.innerHTML = correctPanelHtml();
  const call = (k, ...a) => (typeof opts[k] === 'function' ? opts[k](...a) : undefined);
  const q = s => box.querySelector(s);
  const whole = q('.cor-whole'), secs = q('.cor-sections'), bal = q('.cor-balance');
  const wholeIn = q('.cor-whole-in'), segIn = q('.cor-seg-in');
  const say = (sec, text, err) => {
    const m = sec.querySelector('.cor-msg');
    m.textContent = text || ''; m.classList.toggle('err', !!err);
  };

  let override = null;       // the Whole-track genre, or null
  let sections = [];         // [{id, start_s, end_s, genre}]
  let duration = 0;
  let pending = null;        // {start_s, end_s} drawn, waiting for its genre
  let drawing = false;
  let disarm = null;         // the host's, while its waveform is armed

  const balance = wireBalance(bal, {
    hashOf: () => opts.hashOf(),
    complete: opts.complete,
    identity: j => identity(j),
    changed: () => paintHeads(),
    say: t => say(bal, t, true),
  });
  const strip = opts.drawRange ? null : stripDrawer(q('.cor-strip'), () => opts.hashOf());

  // Every change answers with the track's identity: the host repaints from it,
  // and the Library tab -- which lists tracks by that style -- reloads, as it
  // does after a key correction.
  function identity(j){
    if (!j || j.dominant_source === undefined) return;
    override = j.dominant_source === 'override' ? j.dominant_style : null;
    paintHeads();
    holdStill(box, () => call('onIdentity', j));
    paintCands();                          // the one-click choices follow the read
    // Once a burst of Balance presses settles, not per press: a reload is the
    // whole library.
    clearTimeout(libTimer);
    libTimer = setTimeout(() => { if (hooks.reloadLibrary) hooks.reloadLibrary(); }, 800);
  }
  let libTimer = null;

  function paintHeads(){
    const set = (sec, now, can) => {
      sec.querySelector('.cor-now').textContent = now;
      sec.querySelector('.cor-reset').disabled = !can;
    };
    set(whole, override || 'none', !!override);
    set(secs, sections.length ? `${sections.length}` : 'none', sections.length > 0);
    set(bal, balance.summary(), balance.edited());
    bal.querySelector('.cor-note').hidden = !override;
  }

  function paintSections(){
    const list = q('.cor-seglist');
    list.innerHTML = sections.length
      ? sections.map(s => `<div class="cor-seg" data-id="${s.id}">` +
          `<span class="cor-seg-t">${fmtTime(s.start_s)}–${fmtTime(s.end_s)}</span>` +
          `<b>${escapeHtml(s.genre)}</b>` +
          `<button class="cor-seg-x" type="button" title="remove this section (and its training clip)">✕</button></div>`).join('')
      : '';
    for (const b of list.querySelectorAll('.cor-seg-x')){
      b.onclick = () => removeSection(Number(b.closest('.cor-seg').dataset.id));
    }
    if (strip) strip.sections(sections);
    paintHeads();
  }
  const sectionsChanged = () => { paintSections(); call('onSegments', sections.slice()); };

  function paintCands(){
    const cands = (call('cands') || []).filter(c => c && c.style && c.style !== override);
    const box_ = q('.cor-cands');
    box_.innerHTML = cands.length
      ? `<span class="ovr-h">already reads as</span>` + cands.slice(0, 6).map(c =>
          `<button class="ovr-cand" type="button" data-g="${escapeHtml(c.style)}">${escapeHtml(c.style)}` +
          `<i>${Math.round((c.score || 0) * 100)}%</i></button>`).join('')
      : '';
    for (const b of box_.querySelectorAll('.ovr-cand')) b.onclick = () => setWhole(b.dataset.g);
  }

  // --- Whole track ---
  async function setWhole(genre){
    genre = (genre || '').trim();
    const hash = opts.hashOf();
    if (!genre){ wholeIn.focus(); return; }
    if (!hash){ say(whole, 'this track has no hash yet', true); return; }
    say(whole, 'saving…');
    try {
      const j = await postJson(`/api/v1/override/${hash}`, {genre});
      wholeIn.value = genre;
      identity(j);
      const filed = await call('afterWhole', genre, j);
      say(whole, ((j.trained || filed) ? `set · training copy filed under ${genre}` : 'set') +
        (j.previous_copy_removed ? ` · ${j.replaced}'s copy removed` : ''));
      paintCands();
    } catch(err){ say(whole, err.message, true); }
  }
  async function resetWhole(){
    const hash = opts.hashOf();
    if (!hash) return;
    say(whole, 'resetting…');
    try {
      const j = await api(`/api/v1/override/${hash}`, {method: 'DELETE'});
      wholeIn.value = '';
      identity(j);
      say(whole, 'reset · the read is back' + (j.copy_removed ? ' · training copy removed' : ''));
      paintCands();
    } catch(err){ say(whole, err.message, true); }
  }
  q('.cor-whole-set').onclick = () => setWhole(wholeIn.value);
  wholeIn.addEventListener('keydown', e => { if (e.key === 'Enter') setWhole(wholeIn.value); });
  tabComplete(wholeIn, opts.complete);
  whole.querySelector('.cor-reset').onclick = resetWhole;

  // --- Sections ---
  const newRow = q('.cor-seg-new'), addBtn = q('.cor-seg-add');
  function endDraw(){
    drawing = false; addBtn.disabled = false;
    if (disarm){ const d = disarm; disarm = null; d(); }
    else if (strip) strip.disarm();
  }
  function onRange(start, end){
    drawing = false; disarm = null; addBtn.disabled = false;
    if (start == null){ say(secs, ''); return; }
    pending = {start_s: start, end_s: end};
    q('.cor-range').textContent = `${fmtTime(start)}–${fmtTime(end)} as`;
    newRow.hidden = false; say(secs, '');
    segIn.value = ''; segIn.focus();
  }
  addBtn.onclick = () => {
    if (!opts.hashOf()){ say(secs, 'this track has no hash yet', true); return; }
    if (!duration){ say(secs, 'this track has no duration to mark a range on', true); return; }
    newRow.hidden = true; pending = null;
    drawing = true; addBtn.disabled = true;
    say(secs, opts.drawRange
      ? 'drag across the waveform above to mark the section · Esc cancels'
      : 'drag across the strip to mark the section · Esc cancels');
    if (opts.drawRange) disarm = opts.drawRange(onRange);
    else { strip.show(duration, sections); strip.arm(onRange); }
  };
  async function applySection(){
    const genre = segIn.value.trim();
    if (!pending) return;
    if (!genre){ segIn.focus(); return; }
    say(secs, 'extracting section…');
    try {
      const j = await postJson('/api/v1/override_segment',
        {hash: opts.hashOf(), start: pending.start_s, end: pending.end_s, genre});
      sections = [...sections, {id: j.id, start_s: j.start, end_s: j.end, genre}]
        .sort((a, b) => a.start_s - b.start_s);
      pending = null; newRow.hidden = true;
      say(secs, j.extracted ? `added · clip filed under ${genre}` : 'added');
      sectionsChanged();
    } catch(err){ say(secs, err.message, true); }
  }
  async function removeSection(id){
    try {
      const j = await api(`/api/v1/override_segment/${id}`, {method: 'DELETE'});
      sections = sections.filter(s => s.id !== id);
      say(secs, j.clip_removed ? 'removed · its training clip too' : 'removed');
      sectionsChanged();
    } catch(err){ say(secs, err.message, true); }
  }
  q('.cor-seg-apply').onclick = applySection;
  q('.cor-seg-cancel').onclick = () => { pending = null; newRow.hidden = true; say(secs, ''); };
  segIn.addEventListener('keydown', e => {
    if (e.key === 'Enter') applySection();
    if (e.key === 'Escape'){ pending = null; newRow.hidden = true; }
  });
  tabComplete(segIn, opts.complete);
  secs.querySelector('.cor-reset').onclick = async () => {
    for (const s of sections.slice()) await removeSection(s.id);
    if (!sections.length) say(secs, 'reset · every section removed, with its clip');
  };

  // --- Balance ---
  bal.querySelector('.cor-reset').onclick = async () => {
    await balance.reset();
    say(bal, 'reset · the read is back as the model heard it');
  };

  // --- open / close ---
  const onKey = e => { if (e.key === 'Escape' && drawing){ endDraw(); say(secs, ''); } };
  async function open(prefill){
    box.hidden = false;
    call('onOpen');
    document.addEventListener('keydown', onKey);
    for (const s of [whole, secs, bal]) say(s, '');
    newRow.hidden = true; pending = null;
    const hash = opts.hashOf();
    if (!hash){ say(whole, 'this track has no hash yet — wait for its analysis to finish', true); return; }
    fillGenreList([...(call('genres') || []), ...balance.steps()]);
    try {
      const [t, w] = await Promise.all([api(`/api/v1/track/${hash}`), api(`/api/v1/weights/${hash}`)]);
      duration = t.duration || 0;
      sections = (t.segment_overrides || []).slice();
      override = t.dominant_source === 'override' ? t.dominant_style : null;
      wholeIn.value = prefill || override || '';
      balance.set(w);
      paintSections(); paintCands();
      if (strip && sections.length) strip.show(duration, sections);
    } catch(err){ say(whole, `couldn't load this track: ${err.message}`, true); }
    if (prefill) wholeIn.focus();
  }
  function close(){
    if (drawing) endDraw();
    document.removeEventListener('keydown', onKey);
    box.hidden = true;
    call('onClose');
  }
  btn.onclick = () => (box.hidden ? open() : close());
  q('.cor-close').onclick = close;
  return {open, close};
}

export { HINTS, wireCorrectPanel };

/* Vibedentify front-end — List / analyzer, plus the shared helpers used by
   the whole UI.

   LOAD ORDER: app.js loads FIRST (see index.html). It defines the shared
   helpers — escapeHtml, colorFor, styleInfo, familyOf, fmtTime, the lens
   functions, etc. — plus the row state (results, GLOBAL, SIBLING_MAP,
   SIBLING_GROUPS) that panels.js, player.js and map.js reference at runtime.
   Those files load after this one. The side panels live in panels.js; the row
   builder here (finishRow) calls its renderTags / renderLookup /
   renderVibeMatches — a cross-file reference in the shared <script> scope. */

/* ---- diagnostics: ship frontend breadcrumbs to the backend log ------------
   The WebView renderer can crash on its own (e.g. OOM during a big batch),
   taking its console with it — so POST milestones + uncaught errors to the
   backend, where they persist in the log file. */
/* The little waveform mark that fronts a tile on the Genres and Vibes tabs.

   Drawn deterministically FROM THE NAME rather than from random noise, so it is
   that genre's mark -- stable across reloads and identical on every machine --
   instead of decoration that reshuffles on each render.

   Shared rather than copied into both tabs: the two tabs are supposed to look
   like one product, and a duplicated drawing primitive is exactly what drifts
   apart the next time either side is touched. */
function vibeWaveSvg(color, seed){
  var n = 26, bars = [], acc = 0, i;
  for (i = 0; i < String(seed).length; i++) acc = (acc * 31 + String(seed).charCodeAt(i)) % 9973;
  for (i = 0; i < n; i++){
    acc = (acc * 1103515245 + 12345) % 2147483648;
    var h = 3 + (acc % 100) / 100 * 15;                    // 3..18 of a 22 box
    bars.push('<rect x="' + (i * 2.2) + '" y="' + ((22 - h) / 2).toFixed(1) +
              '" width="1.3" height="' + h.toFixed(1) + '" rx="0.6"/>');
  }
  return '<svg class="gen-wave" viewBox="0 0 58 22" aria-hidden="true" ' +
         'style="color:' + escapeHtml(color == null ? '' : color) + '">' + bars.join('') + '</svg>';
}
window.vibeWaveSvg = vibeWaveSvg;

/* A stable hue (0..359) from a name. Anything with no palette entry -- a
   genre family the palette does not slot, a vibe -- is coloured by this, and
   it is one function so a vibe's swatch on the Vibes tab and its galaxy in
   the Universe are the same colour by construction, not by coincidence. */
/* exported nameHue */ // used by map.js and vibes.js (shared scope)
function nameHue(name){
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return ((h % 360) + 360) % 360;
}

/* The Genres and Vibes tabs share one card grid: select a tile to expand its
   card, one at a time -- an open card spans the full grid row, so several at
   once undoes the grid. `onOpen(cardEl)` runs for the card that just opened. */
function wireTileToggle(body, tiles, onOpen){
  tiles.forEach(function (t) {
    t.onclick = function () {
      var cardEl = t.closest('.gen-key');
      var wasOpen = cardEl.classList.contains('open');
      body.querySelectorAll('.gen-key.open').forEach(function (o) {
        o.classList.remove('open');
        o.querySelector('.gen-detail').hidden = true;
      });
      if (wasOpen) return;
      cardEl.classList.add('open');
      cardEl.querySelector('.gen-detail').hidden = false;
      if (onOpen) onOpen(cardEl);
    };
  });
}
window.wireTileToggle = wireTileToggle;

/* Folding cards. Any .opt-fold card closes and opens from its heading; the
   state is remembered per heading so a tab comes back the way you left it.
   "How this works" starts closed (the class is in its markup), everything
   else starts open. Wired once, on the document, so a card re-rendered by its
   tab needs nothing further -- the tab calls applyFolds() after rendering. */
let FOLDS = {};
try { FOLDS = JSON.parse(localStorage.getItem('vibeFolds') || '{}') || {}; } catch (_) { /* private mode */ }
// Keyed on the heading's own words, not its count badge: "House 2472 · 40%"
// changes with the library, and the fold should survive that.
const foldKey = card => {
  const h = card.querySelector('h3');
  if (!h) return '';
  const t = h.firstChild && h.firstChild.nodeType === 3 ? h.firstChild.textContent : h.textContent;
  return t.trim();
};
document.addEventListener('click', e => {
  const h = e.target.closest('.opt-fold > h3');
  if (!h) return;
  const card = h.parentElement;
  const closed = card.classList.toggle('collapsed');
  FOLDS[foldKey(card)] = closed;
  try { localStorage.setItem('vibeFolds', JSON.stringify(FOLDS)); } catch (_) { /* private mode */ }
});
window.applyFolds = root => {
  for (const card of root.querySelectorAll('.opt-fold')){
    const k = foldKey(card);
    if (k in FOLDS) card.classList.toggle('collapsed', !!FOLDS[k]);
  }
};

/* The counter card's ranked bars, shared by the Genres and Vibes tabs so the
   two read as one product. `rows` is [{name, count, color, badge?, title?}],
   biggest first; the bar is scaled against the BIGGEST row, not against 100%,
   or in a library with one dominant genre every other row renders as a
   sliver. `badge` is extra markup after the name; `title` the row's tooltip. */
function statRowsHtml(rows, total){
  var max = rows.length ? Math.max(1, rows[0].count) : 1;
  return rows.map(function (r) {
    var pct = total ? (r.count / total) * 100 : 0;
    var title = r.title || (r.name + ' — ' + r.count + ' track' + (r.count === 1 ? '' : 's'));
    return '<div class="gen-stat-row" title="' + escapeHtml(title) + '">' +
      '<span class="gen-stat-name"><i class="gen-stat-dot" style="background:' +
        escapeHtml(r.color) + '"></i>' + escapeHtml(r.name) + (r.badge || '') + '</span>' +
      '<span class="gen-stat-bar"><span style="width:' + ((r.count / max) * 100).toFixed(1) +
        '%;background:' + escapeHtml(r.color) + '"></span></span>' +
      '<span class="gen-stat-n">' + r.count + '</span>' +
      '<span class="gen-stat-pct">' + pct.toFixed(1) + '%</span>' +
    '</div>';
  }).join('');
}
window.statRowsHtml = statRowsHtml;

function clientLog(msg, level){
  try {
    fetch('/clientlog', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({msg: String(msg), level: level || 'info'}),
      keepalive: true,          // still sent if the page is tearing down
    }).catch(()=>{});
  } catch(_){ /* never let logging throw */ }
}
function jsHeapMB(){
  const m = performance && performance.memory;   // Chromium/WebView2 only
  return m ? Math.round(m.usedJSHeapSize / 1e6) + '/' + Math.round(m.jsHeapSizeLimit / 1e6) : '?';
}
window.addEventListener('error', e =>
  clientLog(`window.error: ${e.message || ''} @ ${e.filename || ''}:${e.lineno || ''}:${e.colno || ''}`, 'error'));
window.addEventListener('unhandledrejection', e =>
  clientLog('unhandledrejection: ' + ((e.reason && (e.reason.stack || e.reason.message || e.reason)) || ''), 'error'));

const rowsEl  = document.getElementById('rows');
const emptyEl = document.getElementById('empty');
const drop    = document.getElementById('drop');
const picker  = document.getElementById('picker');
const exportB = document.getElementById('export');
const clearB  = document.getElementById('clear');
const countEl = document.getElementById('count');

let results = [];          // {title, filename, genreLabel, ok}
let queue = [];
let busy = false;

/* Okabe-Ito palette (color-blind safe) + shape + texture per genre.
   Focus genres are pre-registered with fixed identities; everything else
   gets the next most-distinct combination on first appearance.
   (Grey is intentionally NOT here -- it's reserved for the "Other" bucket.) */
const PALETTE = ["#009E73","#F0E442","#D55E00","#0072B2","#E69F00",
                 "#56B4E9","#CC79A7","#7FCDBB","#B79AE3","#C44E78"];
const SHAPES  = ["sq","ci","tr","di","hx"];
const TEXTURES = ["none",
  "repeating-linear-gradient(45deg, rgba(0,0,0,.35) 0 2px, transparent 2px 6px)",
  "repeating-linear-gradient(-45deg, rgba(0,0,0,.35) 0 2px, transparent 2px 6px)",
  "repeating-linear-gradient(0deg, rgba(0,0,0,.35) 0 2px, transparent 2px 6px)",
  "radial-gradient(rgba(0,0,0,.45) 1px, transparent 1.5px)"];
const OTHER_COLOR = "#5A6472";      // deliberate neutral slate = "Other"
const TOP_N_COARSE = 3;             // coarse view: name top-3 genres, rest -> Other
const REG = new Map([
  ["drum n bass", {color:"#E69F00", shape:"sq", tex:TEXTURES[0]}],
  ["trance",      {color:"#56B4E9", shape:"ci", tex:TEXTURES[1]}],
  ["dubstep",     {color:"#CC79A7", shape:"tr", tex:TEXTURES[2]}],
]);
let regCount = 0;
function styleInfo(style){
  const k = (style||'').toLowerCase();
  if (k === 'other') return {color:OTHER_COLOR, shape:'hx', tex:'none'};
  if (!REG.has(k)){
    const i = regCount++;
    REG.set(k, {color: PALETTE[i % PALETTE.length],
                shape: SHAPES[(i + 3) % SHAPES.length],
                tex:   TEXTURES[(i + 3) % TEXTURES.length]});
  }
  return REG.get(k);
}
function colorFor(style){ return styleInfo(style).color; }


/* recolor a genre everywhere (canvas + breakdown, all rows) for the session */
function recolorGenre(key, hex){
  const info = styleInfo(key);   // registers it if new
  info.color = hex;
  for (const r of results){
    if (!r.ok || !r.row) continue;
    if (r.row._renderGenre) r.row._renderGenre();
    if (r.row._redrawWave) r.row._redrawWave();
  }
}
// one shared <input type=color>, repositioned and reused per click
let _picker = null;
function openColorPicker(key, currentHex, anchorEl){
  if (!_picker){
    _picker = document.createElement('input');
    _picker.type = 'color';
    _picker.style.cssText = 'position:fixed;width:0;height:0;opacity:0;border:0;padding:0;pointer-events:none';
    document.body.appendChild(_picker);
  }
  _picker.value = /^#[0-9a-fA-F]{6}$/.test(currentHex) ? currentHex : '#888888';
  _picker.oninput = () => recolorGenre(key, _picker.value);
  const r = anchorEl.getBoundingClientRect();
  _picker.style.left = r.left + 'px';
  _picker.style.top = r.bottom + 'px';
  _picker.click();
}

/* In coarse view the top-N genres by track time stay named; the rest are
   collapsed into a single "Other" bucket -- used identically by the waveform and
   the side breakdown so the two always agree. */
/* In coarse view the top-N genres by track time stay named; the rest collapse
   to "Other". When expand=true (fine detail) every genre is named -- no Other.
   Used identically by the waveform and the side breakdown so they always agree. */
function mainGenreSet(segments, expand){
  if (!segments || !segments.length) return null;
  const counts = {}; for (const s of segments) counts[s] = (counts[s] || 0) + 1;
  if (expand) return new Set(Object.keys(counts));        // name everything
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return new Set(ranked.slice(0, TOP_N_COARSE).map(e => e[0]));
}
function bandColor(g, mainSet){ return (mainSet && !mainSet.has(g)) ? OTHER_COLOR : colorFor(g); }
function bandLabel(g, mainSet){ return (mainSet && !mainSet.has(g)) ? 'Other' : g; }

/* ===================== PREFERENCES ================================
   The app-wide settings the Options tab edits, in one persisted object. Each
   screen keeps its own view state (map labels, the Universe sliders, the
   library columns) under its own key; these are the choices that cut across
   screens or that a screen has no natural place to ask about. Read them
   through PREFS; change them through setPref, which persists and applies. */
const PREFS_DEFAULTS = {
  sampleSeconds: 22,        // how long a preview clip runs
  sampleFrom: 'drop',       // 'drop' | 'middle' | 'start' -- where it starts
  autoSample: true,         // cue a clip when a star is selected on the map
  defaultMap: 'regions',    // the map view the Map tab opens on
  uiScale: 100,             // whole-app zoom, percent
  theme: 'neon',            // see THEMES at the end of app.css
  eqStyle: 'bars',          // the header graphic: bars | blocks | dots | glow | wave | stars | vinyl | off
  analyzerIdentity: 'v2',   // the Analyzer's default lenses (see GLOBAL)
  analyzerSeg: 'hysteresis',
};
const PREFS = Object.assign({}, PREFS_DEFAULTS);
try { Object.assign(PREFS, JSON.parse(localStorage.getItem('vibePrefs') || '{}') || {}); } catch (_) { /* private mode */ }
const PREF_LISTENERS = [];        // (key, value) => void, for screens that react live
function setPref(key, value){
  if (!(key in PREFS_DEFAULTS)) return;
  PREFS[key] = value;
  try { localStorage.setItem('vibePrefs', JSON.stringify(PREFS)); } catch (_) { /* private mode */ }
  if (key === 'uiScale') applyUiScale();
  if (key === 'theme') applyTheme();
  if (key === 'eqStyle') applyEqStyle();
  for (const fn of PREF_LISTENERS) fn(key, value);
}
/* UI scale is a CSS zoom on the body: the app is laid out in pixels, so a
   root font-size would only scale the text. Chromium honours zoom, and both
   the browser and the desktop shell are Chromium. */
function applyUiScale(){
  const z = Math.max(60, Math.min(160, Number(PREFS.uiScale) || 100));
  document.body.style.zoom = z === 100 ? '' : (z / 100);
}
applyUiScale();
/* The theme is a data attribute on the root; the stylesheet does the rest.
   The page head applies it before the first paint from the same preference. */
const THEMES = [['neon', 'Neon'], ['light', 'Light'], ['midnight', 'Midnight'],
                ['synthwave', 'Synthwave'], ['forest', 'Forest'], ['ember', 'Ember']];
function applyTheme(){
  const t = THEMES.some(([k]) => k === PREFS.theme) ? PREFS.theme : 'neon';
  if (t === 'neon') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}
applyTheme();

/* ===================== ANALYZER LENSES ===========================
   Two independent switches, both recomputed from the per-frame top-k data:
     identity  : 'v2' (salience) | 'v1' (flat % of track)   -> side breakdown
     seg       : 'raw' | 'hysteresis' | 'sibling'           -> waveform stream
   GLOBAL holds the defaults (from PREFS, so they survive a restart and the
   Options tab can set them); each row may override either. */
const GLOBAL = {identity: PREFS.analyzerIdentity, seg: PREFS.analyzerSeg};

// near-synonym clusters that flicker; member -> canonical name. Editable.
const SIBLING_GROUPS = {
  "House":       ["House","Tribal House","Deep House","Tech House","Progressive House",
                  "Electro House","Garage House","Italo House","Euro House","Hard House",
                  "Ghetto House","Speed Garage"],
  "Trance":      ["Trance","Tech Trance","Hard Trance","Progressive Trance","Goa Trance",
                  "Psy-Trance","Hands Up"],
  "Techno":      ["Techno","Hard Techno","Minimal Techno","Dub Techno","Deep Techno","Schranz"],
  "Drum n Bass": ["Drum n Bass","Jungle","Halftime","Breakcore","Neurofunk"],
  "Hardcore":    ["Hardcore","Gabber","Speedcore","Happy Hardcore","Makina","Jumpstyle",
                  "Hardstyle","Terrorcore"],
  "Breaks":      ["Breaks","Progressive Breaks","Breakbeat"],
  "Dubstep":     ["Dubstep","Brostep"],
  "Ambient":     ["Ambient","Dark Ambient","Drone","Berlin-School","New Age"],
};
const SIBLING_MAP = (() => {
  const m = {};
  for (const canon in SIBLING_GROUPS) for (const mem of SIBLING_GROUPS[canon]) m[mem.toLowerCase()] = canon;
  return m;
})();

/* PulseRoots family roll-up: map each Discogs style to a broad family
   (mendiak.github.io/pulse.roots, MIT-licensed hierarchy). Resolution falls
   back through the editable sibling groups, then to the style itself, so
   coverage stays high even where PulseRoots has no direct entry. */
let STYLE_FAMILY = {};
fetch('/static/genre_families.json')
  .then(r => r.ok ? r.json() : null)
  .then(d => { if (d && d.style_family) STYLE_FAMILY = d.style_family; })
  .catch(() => {});
function familyOf(style){
  const k = (style || '').toLowerCase();
  if (STYLE_FAMILY[k]) return STYLE_FAMILY[k];
  const canon = SIBLING_MAP[k];                 // editable near-synonym group
  if (canon) return STYLE_FAMILY[canon.toLowerCase()] || canon;
  return style;
}
/* family-merge: pool each frame's scores by family, take the winner */
function segsFamily(frames){
  return frames.map(f => {
    const agg = {};
    for (const [s, p] of f){ const fam = familyOf(s); agg[fam] = (agg[fam] || 0) + p; }
    let best = null, bp = -1;
    for (const k in agg){ if (agg[k] > bp){ bp = agg[k]; best = k; } }
    return best;
  });
}

const HYST_MARGIN = 0.08;   // challenger must beat the held genre by this to switch
const HYST_HOLD   = 2;      // ...for this many consecutive frames

/* winners-only stream straight from frames */
function segsRaw(frames){ return frames.map(f => f[0][0]); }

/* hysteresis: stay on the current genre until a challenger decisively wins */
function segsHysteresis(frames, margin, hold){
  margin = margin ?? HYST_MARGIN; hold = hold ?? HYST_HOLD;
  const out = []; let cur = null, cand = null, count = 0;
  for (const f of frames){
    const top = f[0][0], topP = f[0][1];
    if (cur === null){ cur = top; out.push(cur); continue; }
    let curP = 0;                                   // current genre's score this frame
    for (const [s, p] of f){ if (s === cur){ curP = p; break; } }
    if (top === cur){ cand = null; count = 0; }
    else {
      if (top === cand) count++; else { cand = top; count = 1; }
      if (count >= hold && (topP - curP) >= margin){ cur = cand; cand = null; count = 0; }
    }
    out.push(cur);
  }
  return out;
}

/* sibling-merge: sum near-synonym scores per frame, then take the winner */
function segsSibling(frames){
  return frames.map(f => {
    const agg = {};
    for (const [s, p] of f){
      const canon = SIBLING_MAP[s.toLowerCase()] || s;
      agg[canon] = (agg[canon] || 0) + p;
    }
    let best = null, bp = -1;
    for (const k in agg){ if (agg[k] > bp){ bp = agg[k]; best = k; } }
    return best;
  });
}

function segsForMode(frames, mode){
  if (!frames || !frames.length) return null;
  if (mode === 'hysteresis') return segsHysteresis(frames);
  if (mode === 'sibling')    return segsSibling(frames);
  if (mode === 'family')     return segsFamily(frames);
  if (mode === 'hyst+sib'){
    // sibling first (score-pooling per frame), then hysteresis on the resulting stream
    const sibSegs = segsSibling(frames);
    // re-wrap as minimal frames for hysteresis: [[genre, 1.0]]
    const sibFrames = sibSegs.map(g => [[g, 1.0]]);
    return segsHysteresis(sibFrames);
  }
  return segsRaw(frames);
}
function refreshFooter(){
  const done = results.filter(r => r.ok).length;
  countEl.textContent = `${done} track${done===1?'':'s'}`;
  exportB.disabled = done === 0;
}

/* Load a cached track into the List by content hash (used by the Library tab's
   click-to-load). Reuses the exact path /batch uses: a stand-in file object + a
   finishRow() call with the cached payload, so no re-analysis and all row actions work. */
window.loadTrackByHash = async (hash) => {
  if (results.some(r => r.hash === hash)){          // already in the list -> just reveal it
    const ex = results.find(r => r.hash === hash);
    if (ex && ex.row) ex.row.scrollIntoView({behavior:'smooth', block:'center'});
    return true;
  }
  try{
    const d = await fetch(`/track/${encodeURIComponent(hash)}`).then(r => r.json());
    if (!d || d.error) return false;
    const row = addRow({name: d.filename || d.title || 'track'});
    finishRow(row, d, null);
    row.scrollIntoView({behavior:'smooth', block:'center'});
    return true;
  }catch(_){ return false; }
};

/* How a key is written. Camelot ("8A") is what you mix by; the musical name
   ("A min") is what you read. The app showed both, everywhere, always -- fine on
   one row and noise across a library -- so which of them you see is a choice.
   Per browser, not per track: it is a reading preference, not data. */
const KEYVIEW = { mode: 'both' };                  // 'both' | 'camelot' | 'musical'
const KEYVIEW_MODES = ['both', 'camelot', 'musical'];
try {
  const m = localStorage.getItem('vibeKeyView');
  if (KEYVIEW_MODES.includes(m)) KEYVIEW.mode = m;
} catch (_) { /* private mode */ }

/* One track's key, written the way you asked to read it. `t` is anything
   carrying camelot / key / scale: an analysis payload, a map node, a saved row.
   Each mode falls back to the other notation rather than rendering blank -- a
   track the analyser found a key for but no Camelot code still has a key, and
   showing nothing would read as "no key" instead of "not in that notation".
   keyParts() decides which notations to show ({cam, mus}, either may be
   empty); keyText() joins them, and the Analyzer row marks them up. */
function keyParts(t){
  const cam = (t && t.camelot) ? String(t.camelot) : '';
  const mus = (t && t.key) ? `${t.key} ${(t.scale || '').slice(0, 3)}`.trim() : '';
  if (KEYVIEW.mode === 'camelot') return { cam, mus: cam ? '' : mus };
  if (KEYVIEW.mode === 'musical') return { cam: mus ? '' : cam, mus };
  return { cam, mus };
}
/* Correcting a key. The detector is a trained model (docs/KEY_SPEC.md) and its
   training set is whatever music it was fitted on -- public EDM key sets
   disagree with each other by several points, so the labels that describe THIS
   library best are the ones its owner makes. Every correction here is stored
   apart from the analysis (so re-analysis cannot wipe it) and is a training
   example `tools/train_key_templates.py --dataset library` can learn from.
   Picking the same key again clears the correction, restoring the detector's. */
const KEY_CHOICES = ['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B'];
let keyMenu = null;
function closeKeyMenu(){ if (keyMenu){ keyMenu.remove(); keyMenu = null; } }
document.addEventListener('click', e => {
  if (keyMenu && !keyMenu.contains(e.target) && !e.target.closest('.keyrow')) closeKeyMenu();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeKeyMenu(); });

function openKeyMenu(anchorEl, track, repaint){
  if (keyMenu && keyMenu._anchor === anchorEl){ closeKeyMenu(); return; }
  closeKeyMenu();
  if (!track || !track.hash) return;
  keyMenu = document.createElement('div');
  keyMenu._anchor = anchorEl;
  keyMenu.className = 'keymenu';
  const cells = mode => KEY_CHOICES.map(k => {
    const on = track.key === k && track.scale === mode;
    return `<button type="button" class="keypick${on ? ' on' : ''}" data-key="${k}" data-scale="${mode}">` +
      `${escapeHtml(k)}</button>`;
  }).join('');
  keyMenu.innerHTML =
    `<div class="keymenu-lbl">minor</div><div class="keymenu-grid">${cells('minor')}</div>` +
    `<div class="keymenu-lbl">major</div><div class="keymenu-grid">${cells('major')}</div>` +
    (track.key_source === 'manual'
      ? `<button type="button" class="keymenu-clear">use the detector's key</button>` : '') +
    `<div class="keymenu-msg"></div>`;
  document.body.appendChild(keyMenu);
  const r = anchorEl.getBoundingClientRect();
  keyMenu.style.left = Math.max(4, Math.min(window.innerWidth - keyMenu.offsetWidth - 4, r.left)) + 'px';
  keyMenu.style.top = (window.scrollY + r.bottom + 4) + 'px';

  const msg = keyMenu.querySelector('.keymenu-msg');
  async function send(body){
    msg.textContent = 'saving\u2026';
    try {
      const res = await fetch(`/key/${track.hash}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
      });
      const j = await res.json();
      if (!res.ok) { msg.textContent = j.error || 'could not save'; return; }
      track.key = j.key; track.scale = j.scale; track.camelot = j.camelot; track.key_source = j.key_source;
      closeKeyMenu();
      if (repaint) repaint();
      if (window.reloadLibrary) window.reloadLibrary();
    } catch (_) { msg.textContent = 'could not reach the app'; }
  }
  keyMenu.querySelectorAll('.keypick').forEach(b => b.addEventListener('click', () => {
    const same = b.classList.contains('on') && track.key_source === 'manual';
    send(same ? {key: null} : {key: b.dataset.key, scale: b.dataset.scale});
  }));
  const clear = keyMenu.querySelector('.keymenu-clear');
  if (clear) clear.addEventListener('click', () => send({key: null}));
}

function keyText(t){
  const k = keyParts(t);
  return [k.cam, k.mus].filter(Boolean).join(' ');
}

/* exported setKeyView */ // called from options.js's Appearance card (shared scope)
/* Change it everywhere at once. The rows re-render in place; the map is told so
   an open popup and the hover label stop disagreeing with the setting. */
function setKeyView(mode){
  if (!KEYVIEW_MODES.includes(mode) || mode === KEYVIEW.mode) return;
  KEYVIEW.mode = mode;
  try { localStorage.setItem('vibeKeyView', mode); } catch (_) { /* private mode */ }
  for (const r of results) if (r.row && r.row._renderKey) r.row._renderKey();
  if (typeof window.vibeKeyViewChanged === 'function') window.vibeKeyViewChanged();
}

/* Mark a row you were just pointed at. A track that was already analysed does
   no work when you drop it again, so without this the list looks identical and
   the drop reads as ignored. Self-clearing, or a session's worth of drops would
   leave every row you ever re-added wearing the marker. */
function flashRow(row){
  if (!row || !row.isConnected) return;
  row.classList.remove('justfound');
  void row.offsetWidth;                       // restart the animation
  row.classList.add('justfound');
  clearTimeout(row._flashT);
  row._flashT = setTimeout(() => row.classList.remove('justfound'), 2000);
}

function addRow(file){
  emptyEl.style.display = 'none';
  const row = document.createElement('div');
  row.className = 'row pending';
  row.innerHTML = `
    <div>
      <div class="title">${escapeHtml(file.name.replace(/\.[^.]+$/,''))}</div>
      <div class="file">${escapeHtml(file.name)}</div>
    </div>
    <div class="musical"></div>
    <div>
      <span class="chip"><span class="dot"></span>analyzing&hellip;</span>
    </div>`;
  rowsEl.appendChild(row);
  row.scrollIntoView({block:'nearest'});
  return row;
}

/* Fisheye waveform. When focus (0..1) is set, the area under the cursor bulges
   larger and tapers toward normal at the edges -- like the macOS Dock. With
   focus null it draws flat. Returns nothing; purely visual.
   STRENGTH controls bulge amount; ZONE is how wide (in track-fraction) the lens
   reaches before it's back to ~1x. */
function drawWave(canvas, peaks, fallbackColor, segments, focus, mainSet, overrides, mm){
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 300, h = canvas.clientHeight || 60;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const mid = h / 2;
  const segN = segments ? segments.length : 0;
  const STRENGTH = 0.85, ZONE = 0.14;

  // map a screen fraction sx (0..1) -> source track fraction (0..1) through lens
  function lens(sx){
    if (focus == null) return sx;
    const d = sx - focus;
    const g = Math.exp(-(d * d) / (2 * ZONE * ZONE));   // 1 at cursor -> 0 far
    return sx - STRENGTH * d * g;                        // compress toward focus
  }

  const cols = Math.max(Math.floor(w), 1);
  const mmN = (mm && mm.max && mm.min && mm.rms) ? mm.max.length : 0;
  let lastLabel = null;
  for (let px = 0; px < cols; px++){
    const sx = px / (cols - 1);
    const f = Math.max(0, Math.min(1, lens(sx)));
    let color = fallbackColor, label = null;
    if (segN){
      const segIdx = Math.min(Math.floor(f * segN), segN - 1);
      const raw = segments[Math.max(segIdx, 0)];
      color = bandColor(raw, mainSet);
      label = bandLabel(raw, mainSet);
    }
    // a manual segment override wins this column: paint it the override genre's
    // colour and flag it (label change forces a boundary tick at the span edge).
    let ov = null;
    if (overrides && overrides.length){
      for (const o of overrides){ if (f >= o.a && f < o.b){ ov = o; break; } }
    }
    if (ov){ color = colorFor(ov.genre); label = 'ovr\u0000' + ov.genre; }
    // boundary tick where the displayed genre changes (Other counts as one genre)
    if (label !== lastLabel && lastLabel !== null){
      ctx.globalAlpha = 1; ctx.fillStyle = 'rgba(255,255,255,.20)';
      ctx.fillRect(px, 0, 1, h);
    }
    lastLabel = label;

    if (mmN){
      // DAW-style: pool min/max/rms over the source span this pixel covers (so
      // transients spike), then draw a translucent peak outline + a solid RMS core.
      const g1 = Math.max(0, Math.min(1, lens((px + 1) / (cols - 1))));
      const a = Math.floor(Math.min(f, g1) * (mmN - 1));
      const b = Math.max(a, Math.ceil(Math.max(f, g1) * (mmN - 1)));
      let mn = 1, mx = -1, rm = 0;
      for (let k = a; k <= b; k++){
        if (mm.min[k] < mn) mn = mm.min[k];
        if (mm.max[k] > mx) mx = mm.max[k];
        if (mm.rms[k] > rm) rm = mm.rms[k];
      }
      if (mx < mn){ mn = 0; mx = 0; }
      ctx.fillStyle = color;
      ctx.globalAlpha = focus == null ? 0.5 : 0.55;                     // peak outline (min..max)
      ctx.fillRect(px, mid - mx * mid, 1.05, Math.max((mx - mn) * mid, 1));
      ctx.globalAlpha = focus == null ? 0.95 : 1;                       // RMS core (loudness body)
      ctx.fillRect(px, mid - rm * mid, 1.05, Math.max(rm * 2 * mid, 1));
    } else {
      // fallback: the stored peak envelope, interpolated so it isn't blocky
      const fp = f * (peaks.length - 1);
      const i0 = Math.floor(fp), i1 = Math.min(i0 + 1, peaks.length - 1);
      const val = peaks[i0] + (peaks[i1] - peaks[i0]) * (fp - i0);
      const amp = Math.max(val * mid, 1.0);
      ctx.globalAlpha = focus == null ? 0.9 : 0.94;
      ctx.fillStyle = color;
      ctx.fillRect(px, mid - amp, 1.05, amp * 2);
    }
    if (ov){                                   // manual-override treatment: wash + top accent bar
      ctx.globalAlpha = 0.12; ctx.fillStyle = '#ffffff';
      ctx.fillRect(px, 0, 1.05, h);
      ctx.globalAlpha = 0.95; ctx.fillStyle = 'rgba(120,200,255,0.95)';
      ctx.fillRect(px, 0, 1.05, 2);
    }
  }
  ctx.globalAlpha = 1;
}

function fmtDur(sec){
  if (sec == null) return '';
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2,'0')}`;
}

/* genre detected at fractional position f (0..1) along the track */
function genreAt(segments, f){
  if (!segments || !segments.length) return null;
  const i = Math.min(Math.floor(f * segments.length), segments.length - 1);
  return segments[Math.max(i, 0)];
}

/* Temporal smoothing of the per-frame genre stream.
   secs = strength in seconds; hop = seconds per frame (2.0 coarse / ~0.5 fine).
   Two passes: (1) median/majority filter over a window, (2) absorb any run
   shorter than the threshold into its larger neighbor. Pure display cleanup;
   the raw array is never mutated (we return a new one). */
function smoothSegments(segments, secs, hop){
  if (!segments || segments.length < 3 || secs <= 0) return segments ? segments.slice() : segments;
  const win = Math.max(1, Math.round(secs / (hop || 2.0)));   // frames in window
  const n = segments.length;

  // pass 1: majority vote in a +/- win neighborhood
  let out = new Array(n);
  for (let i = 0; i < n; i++){
    const counts = {};
    for (let j = Math.max(0, i - win); j <= Math.min(n - 1, i + win); j++){
      counts[segments[j]] = (counts[segments[j]] || 0) + 1;
    }
    let best = segments[i], bn = -1;
    for (const k in counts){ if (counts[k] > bn){ bn = counts[k]; best = k; } }
    out[i] = best;
  }

  // pass 2: merge runs shorter than the window into a neighbor
  const minRun = win;
  let changed = true, guard = 0;
  while (changed && guard++ < 20){
    changed = false;
    let i = 0;
    while (i < n){
      let j = i;
      while (j < n && out[j] === out[i]) j++;
      const len = j - i;
      if (len < minRun && (i > 0 || j < n)){
        const left = i > 0 ? out[i - 1] : null;
        const right = j < n ? out[j] : null;
        const repl = left !== null ? left : right;   // prefer left neighbor
        if (repl !== null && repl !== out[i]){
          for (let k = i; k < j; k++) out[k] = repl;
          changed = true;
        }
      }
      i = j;
    }
  }
  return out;
}

/* Percentages from the smoothed TIMELINE: what fraction of the track each
   genre actually occupies. Returns [{style, score}] sorted desc, score in 0..1. */
function timelinePercents(segments){
  if (!segments || !segments.length) return [];
  const counts = {};
  for (const s of segments) counts[s] = (counts[s] || 0) + 1;
  const n = segments.length;
  return Object.entries(counts)
    .map(([style, c]) => ({style, score: c / n}))
    .sort((a, b) => b.score - a.score);
}

function fmtTime(sec){
  if (sec == null || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2,'0')}`;
}


function finishRow(row, data, file){
  row.classList.remove('pending');
  // remember a dropped/browsed file by hash so it stays playable after Clear
  // (these have no server-side copy — the in-memory File is the only source).
  if (file && data.hash) HASH_FILES.set(data.hash, file);
  const styles = data.styles || [];
  const primary = styles[0] || {style: '?', score: 0};   // guard: model returned no styles
  const pcol = colorFor(primary.style);
  row.querySelector('.title').textContent = data.title;

  /* The genre cell is a rendered body plus a fixed strip of controls. They were
     the same element, so every re-render of the blend -- a recolour, a lens
     change, an adjustment -- wiped the buttons underneath it. Splitting them
     means the read can redraw as often as it likes and the controls stay put. */
  const genreCell = row.children[2];
  genreCell.innerHTML = '';
  const genreBody = document.createElement('div');
  genreBody.className = 'genre-body';
  genreCell.appendChild(genreBody);

  // A blend the user has bent by hand (see wireRowAdjust). Sent with the payload
  // so a track adjusted on the map already reads adjusted here, with no round-trip.
  row._adjusted = (data.adjusted && data.adjusted.length) ? data.adjusted : null;
  // A manual override outranks both, which is the server's own precedence
  // (routes/_shared.py: override > adjustments > relabel > salience). It was
  // never read here, so a track you overrode last week came back to the Analyzer
  // still showing the model's read -- the Map and the Library called it one thing
  // and this screen called it another.
  row._override = data.override || null;

  /* waveform under the title, painted by per-segment genre, with magnifier */
  let renderGenreCell = () => {};   // assigned below; called on smoothing change
  if (data.waveform && data.waveform.length){
    const waveState = {
      peaks: data.waveform,
      frames: data.frames || null,        // per-frame top-k (for lenses)
      winners: data.segments,             // raw argmax winners (coarse)
      raw: data.segments,                 // seg-lens output (starts = winners)
      segments: data.segments,            // smoothed view of raw
      fine: false,
      hop: 2.0,                           // seconds per frame (coarse default)
      smooth: 1.0,                        // medium default (~1s)
      mm: null,                           // DAW-style min/max/rms (fetched below)
    };
    const container = document.createElement('div');
    container.className = 'wavecontainer';
    const c = document.createElement('canvas');
    c.className = 'wave';
    c.title = 'click to play from here · hover to magnify';
    const tip = document.createElement('div');
    tip.className = 'wavetip';
    container.appendChild(c);
    container.appendChild(tip);

    const controls = document.createElement('div');
    controls.className = 'wavehint';
    controls.innerHTML = `<span class="restag" title="Each coloured band along the waveform covers about two seconds of audio.">2s bands</span>` +
      `<button class="finebtn" type="button" title="Re-read this track in finer slices (~0.5s). Slower, but catches short sections.">\u2295 closer look</button>` +
      `<span class="smoothnote" title="One-off single-frame genre flickers are ignored, so the bands do not strobe.">steady view</span>`;
    const resTag = controls.querySelector('.restag');
    const fineBtn = controls.querySelector('.finebtn');

    row.children[0].appendChild(container);
    row.children[0].appendChild(controls);

    // per-row lens override controls (inherit global until changed)
    const rowlens = document.createElement('div');
    rowlens.className = 'rowlens';
    rowlens.innerHTML =
      `<span>lens:</span>` +
      `<select class="rl-id" title="identity (this track)">` +
        `<option value="">identity: global</option>` +
        `<option value="v2">v2 · salience</option><option value="v1">v1 · flat %</option></select>` +
      `<select class="rl-seg" title="segmentation (this track)">` +
        `<option value="">segment: global</option>` +
        `<option value="raw">raw</option><option value="hysteresis">hysteresis</option>` +
        `<option value="sibling">sibling-merge</option><option value="family">family</option></select>` +
      `<span class="ovr"></span>`;
    const rlId = rowlens.querySelector('.rl-id');
    const rlSeg = rowlens.querySelector('.rl-seg');
    const ovr = rowlens.querySelector('.ovr');
    row.children[0].appendChild(rowlens);

    function syncOvrTag(){
      const tags = [];
      if (row._idOverride) tags.push('id*');
      if (row._segOverride) tags.push('seg*');
      ovr.textContent = tags.length ? tags.join(' ') : '';
    }
    rlId.addEventListener('change', () => { row._idOverride = rlId.value || null; syncOvrTag(); row._applyModes(); });
    rlSeg.addEventListener('change', () => { row._segOverride = rlSeg.value || null; syncOvrTag(); row._applyModes(); });

    const dur = data.duration || 0;

    // persisted segment overrides (shipped with the payload on cache hits). Kept
    // as raw {start_s,end_s,genre}; converted to 0..1 fractions for drawWave.
    let segOverrides = (data.segment_overrides || []).slice();
    function ovFracs(){
      if (!dur) return [];
      return segOverrides.map(o => ({a: o.start_s / dur, b: o.end_s / dur, genre: o.genre}));
    }

    // effective mode = per-row override (if set) else the global default
    function segMode(){ return row._segOverride || GLOBAL.seg; }

    function applySmoothing(){
      // 1) segmentation lens turns per-frame top-k into the genre stream
      const lensed = waveState.frames ? segsForMode(waveState.frames, segMode()) : null;
      waveState.raw = lensed || waveState.winners;
      // 2) temporal smoothing
      waveState.segments = waveState.smooth > 0
        ? smoothSegments(waveState.raw, waveState.smooth, waveState.hop)
        : waveState.raw.slice();
      waveState.mainSet = mainGenreSet(waveState.segments, waveState.fine);
    }
    function redraw(focus){
      drawWave(c, waveState.peaks, pcol, waveState.segments, focus ?? null, waveState.mainSet, ovFracs(), waveState.mm);
    }
    applySmoothing();
    requestAnimationFrame(() => redraw(null));

    // Upgrade to the DAW-style min/max/rms waveform: render the stored envelope
    // instantly, then fetch the detailed one (pre-cached for new tracks, decoded
    // once for older ones) and repaint.
    //
    // A 404 means the server can't reach this track's audio -- no cached
    // waveform and no file path, which is every track that was dragged in and
    // analysed without ever being linked to a folder. Those used to be stuck on
    // the coarse envelope permanently. When the drop is what put the row here we
    // are holding the audio, so send it: one decode, cached for good, and the
    // row redraws at full detail. Without a file in hand the envelope stands.
    row._fetchWave = async () => {
      try {
        let r = await fetch(`/waveform/${data.hash}`);
        if (r.status === 404 && file){
          const fd = new FormData();
          fd.append('file', file);
          r = await fetch(`/waveform/${data.hash}`, {method: 'POST', body: fd});
        }
        if (!r.ok) return;
        const mm = await r.json();
        if (mm && mm.max && mm.max.length){ waveState.mm = mm; redraw(null); }
      } catch (_) { /* offline, or the row went away -- the envelope stands */ }
    };

    function showAt(clientX){
      const rect = c.getBoundingClientRect();
      let f = (clientX - rect.left) / rect.width;
      f = Math.max(0, Math.min(1, f));
      redraw(f);
      const g = genreAt(waveState.segments, f);
      // a manual segment override at this position wins the tooltip label
      let ovg = null;
      if (dur) for (const o of segOverrides){ if (f >= o.start_s / dur && f < o.end_s / dur){ ovg = o.genre; break; } }
      const isOther = g && waveState.mainSet && !waveState.mainSet.has(g);
      const shown = ovg || g;
      const swatch = shown ? (ovg ? colorFor(ovg) : bandColor(g, waveState.mainSet)) : null;
      const text = ovg ? `${ovg} \u00b7 override` : (g ? (isOther ? `${g} \u00b7 other` : g) : '');
      tip.style.left = (f * rect.width) + 'px';
      tip.style.display = 'block';
      tip.innerHTML = `${fmtTime(f * dur)}` +
        (shown ? `<span class="sw" style="background:${swatch}"></span>${escapeHtml(text)}` : '');
    }

    // ---- shift-drag to override a time RANGE as a genre (segment override) ----
    // A modifier keeps this from fighting the hover magnifier / click-to-play:
    // shift-drag selects a span; a plain drag still magnifies. See the guide.
    const fracFromX = cx => { const r = c.getBoundingClientRect(); return Math.max(0, Math.min(1, (cx - r.left) / r.width)); };
    let sel = null;   // {a, b} fractions while a shift-drag is in progress

    function paintSel(){
      redraw(null);
      if (!sel) return;
      const rect = c.getBoundingClientRect();
      const x0 = Math.min(sel.a, sel.b) * rect.width, x1 = Math.max(sel.a, sel.b) * rect.width;
      const ctx = c.getContext('2d');                 // transform already dpr-scaled by drawWave
      ctx.globalAlpha = 0.22; ctx.fillStyle = '#78c8ff';
      ctx.fillRect(x0, 0, Math.max(1, x1 - x0), c.clientHeight || 60);
      ctx.globalAlpha = 1;
    }

    c.addEventListener('pointermove', e => {
      if (sel){ sel.b = fracFromX(e.clientX); paintSel(); return; }
      showAt(e.clientX);
    });
    c.addEventListener('pointerdown', e => {
      if (e.shiftKey){                                // begin a range selection
        e.preventDefault();
        closeSegMenu();
        c.setPointerCapture(e.pointerId);
        const f = fracFromX(e.clientX);
        sel = {a: f, b: f};
        paintSel();
        return;                                       // don't magnify or start playback
      }
      c.setPointerCapture(e.pointerId); showAt(e.clientX);
    });
    c.addEventListener('pointerup', e => {
      if (!sel) return;
      sel.b = fracFromX(e.clientX);
      const a = Math.min(sel.a, sel.b), b = Math.max(sel.a, sel.b);
      sel = null;
      redraw(null);
      if ((b - a) * dur < 0.5){                       // a shift-CLICK (not a drag)...
        if (dur){                                     // ...on an existing override -> offer to remove it
          const o = segOverrides.find(x => x.id != null && a >= x.start_s / dur && a < x.end_s / dur);
          if (o) openRemoveMenu(o);
        }
        return;
      }
      openSegMenu(a, b);
    });
    c.addEventListener('pointerleave', () => { if (sel) return; tip.style.display = 'none'; redraw(null); });

    // ---- floating "override section as [genre]" menu ----
    let segMenu = null;
    function closeSegMenu(){ if (segMenu){ segMenu.remove(); segMenu = null; } }
    function openSegMenu(a, b){
      closeSegMenu();
      const s = a * dur, e = b * dur;
      segMenu = document.createElement('div');
      segMenu.className = 'segmenu';
      segMenu.innerHTML =
        `<div class="segmenu-lbl">override <b>${fmtTime(s)}\u2013${fmtTime(e)}</b> as</div>` +
        `<div class="segmenu-row"><input class="segmenu-genre" type="text" autocomplete="off" spellcheck="false" placeholder="genre (e.g. Riddim)">` +
        `<button class="segmenu-apply" type="button">apply</button>` +
        `<button class="segmenu-cancel" type="button" title="cancel">\u2715</button></div>` +
        `<div class="segmenu-msg"></div>`;
      const rect = c.getBoundingClientRect();
      const mid = ((a + b) / 2) * rect.width;
      segMenu.style.left = Math.max(4, Math.min(rect.width - 220, mid - 110)) + 'px';
      container.appendChild(segMenu);
      const input = segMenu.querySelector('.segmenu-genre');
      const msg = segMenu.querySelector('.segmenu-msg');
      const apply = segMenu.querySelector('.segmenu-apply');
      input.focus();
      segMenu.querySelector('.segmenu-cancel').addEventListener('click', closeSegMenu);
      async function submit(){
        const genre = input.value.trim();
        if (!genre){ input.focus(); return; }
        if (!data.hash){ msg.textContent = 'this track has no hash yet'; return; }
        apply.disabled = true; msg.textContent = 'extracting section\u2026';
        let j;
        try {
          const resp = await fetch('/override_segment', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({hash: data.hash, start: s, end: e, genre})});
          j = await resp.json();
          if (!resp.ok){ msg.textContent = j.error || 'failed'; apply.disabled = false; return; }
        } catch(_){ msg.textContent = 'request failed'; apply.disabled = false; return; }
        // persist locally + repaint the span in the manual-override style
        segOverrides.push({id: j.id, start_s: s, end_s: e, genre});
        redraw(null);
        if (renderGenreCell) renderGenreCell();
        closeSegMenu();
      }
      apply.addEventListener('click', submit);
      input.addEventListener('keydown', ev => { if (ev.key === 'Enter') submit(); if (ev.key === 'Escape') closeSegMenu(); });
    }

    // ---- remove an existing override: a two-step CONFIRMATION wall (shift-click
    // the span, then click the red Remove). Deletes the record AND its clip. ----
    function openRemoveMenu(o){
      closeSegMenu();
      segMenu = document.createElement('div');
      segMenu.className = 'segmenu';
      segMenu.innerHTML =
        `<div class="segmenu-lbl">remove override <b>${escapeHtml(o.genre)}</b> ` +
          `${fmtTime(o.start_s)}–${fmtTime(o.end_s)}?</div>` +
        `<div class="segmenu-warn">this also deletes the extracted training clip.</div>` +
        `<div class="segmenu-row"><button class="segmenu-remove" type="button">remove</button>` +
        `<button class="segmenu-cancel" type="button" title="keep it">cancel</button></div>` +
        `<div class="segmenu-msg"></div>`;
      const rect = c.getBoundingClientRect();
      const mid = dur ? ((o.start_s + o.end_s) / 2 / dur) * rect.width : rect.width / 2;
      segMenu.style.left = Math.max(4, Math.min(rect.width - 220, mid - 110)) + 'px';
      container.appendChild(segMenu);
      const msg = segMenu.querySelector('.segmenu-msg');
      const rm = segMenu.querySelector('.segmenu-remove');
      segMenu.querySelector('.segmenu-cancel').addEventListener('click', closeSegMenu);
      rm.addEventListener('click', async () => {
        rm.disabled = true; msg.textContent = 'removing…';
        try {
          const resp = await fetch('/override_segment/delete', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({id: o.id})});
          const j = await resp.json();
          if (!resp.ok){ msg.textContent = j.error || 'failed'; rm.disabled = false; return; }
        } catch(_){ msg.textContent = 'request failed'; rm.disabled = false; return; }
        segOverrides = segOverrides.filter(x => x.id !== o.id);
        redraw(null);
        if (renderGenreCell) renderGenreCell();
        closeSegMenu();
      });
    }

    /* fine-detail: re-analyze just this track at ~0.5s resolution on demand */
    fineBtn.addEventListener('click', async () => {
      if (waveState.fine || !file) return;
      fineBtn.disabled = true;
      fineBtn.textContent = 'refining\u2026';
      try{
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch('/refine', {method:'POST', body:fd});
        const j = await resp.json();
        if (!resp.ok) throw new Error(j.error || resp.statusText);
        waveState.winners = j.segments;
        waveState.frames = j.frames || null;
        waveState.fine = true;
        waveState.hop = j.hop_seconds ?? 0.5;
        resTag.textContent = `~${waveState.hop}s`;
        applySmoothing();
        redraw(null);
        renderGenreCell();
        fineBtn.textContent = 'fine \u2713';
        fineBtn.classList.add('done');
      }catch(err){
        fineBtn.textContent = 'retry';
        fineBtn.disabled = false;
        fineBtn.title = 'refine failed: ' + err.message;
      }
    });

    attachPlayer(row, container, controls, c, file, data, dur);

    // expose for the genre cell renderer defined below
    row._waveState = waveState;
    row._redrawWave = () => redraw(null);
    row._applyModes = () => { applySmoothing(); redraw(null); renderGenreCell(); };
  }

  /* BPM / key cell */
  // bpm_confidence is the native TempoCNN engine's mean peak-softmax, range 0..1
  // (Phase 5 cutover). Below this cutoff the beat read is octave-ambiguous, so we
  // show the half/double-time alternate. Cutoff 0.4 sits in the empirical gap
  // between octave-confused oracle tracks (<=0.37) and the confident cluster
  // (>=0.46). Was < 1.5 when bpm_confidence came from Essentia RhythmExtractor2013
  // on its ~0..5 scale; TempoCNN's 0..1 scale needs this lower threshold.
  const lowConf = data.bpm_confidence != null && data.bpm_confidence < 0.4;
  const alt = data.bpm != null ? (data.bpm < 100 ? data.bpm * 2 : data.bpm / 2) : null;
  let bpmText = data.bpm != null ? data.bpm.toFixed(1) : '---';
  let bpmHtml;
  if (data.bpm == null){
    bpmHtml = `<div class="keyrow">no BPM</div>`;
  } else if (lowConf){
    bpmText = `${data.bpm.toFixed(1)}/${alt.toFixed(1)}`;
    bpmHtml = `<div><span class="bpm">${data.bpm.toFixed(1)}</span>` +
      `<span class="altbpm"> / ${alt.toFixed(1)}</span><span class="unit">BPM</span>` +
      `<span class="unit warn" title="low beat-tracking confidence \u2014 the second number is the half/double-time alternate">?</span></div>`;
  } else {
    bpmHtml = `<div><span class="bpm">${data.bpm.toFixed(1)}</span><span class="unit">BPM</span></div>`;
  }
  // Split so the notation can change under a row that is already on screen --
  // rebuilding the whole cell would take the waveform's neighbours with it.
  const keyHtmlFor = () => {
    const k = keyParts(data);              // same notation rule as keyText
    const fixed = data.key_source === 'manual';
    const title = fixed ? 'key corrected by hand \u2014 click to change' : 'click to correct the key';
    const inner = (!k.cam && !k.mus) ? 'no key'
      : (k.cam ? `<span class="camelot">${escapeHtml(k.cam)}</span>` : '') + escapeHtml(k.mus);
    return `<div class="keyrow${fixed ? ' keyfixed' : ''}" title="${title}" role="button" tabindex="0">` +
      inner + `</div>`;
  };
  const paintMusical = () => {
    row.children[1].innerHTML = bpmHtml + keyHtmlFor() +
      `<div class="dur">${fmtDur(data.duration)}</div>`;
    const kr = row.children[1].querySelector('.keyrow');
    if (kr) kr.addEventListener('click', () => openKeyMenu(kr, data, paintMusical));
  };
  paintMusical();
  row._renderKey = paintMusical;

  /* genre cell -- driven by the smoothed timeline when segments exist, else
     by the model's averaged confidences. Re-runs when the smoothing changes. */
  renderGenreCell = () => {
    const ws = row._waveState;
    const useTimeline = ws && ws.segments && ws.segments.length;
    let shown, srcLabel;
    if (row._override){
      // One word, by your own hand. No blend to draw: the whole point of an
      // override is that it replaced the read rather than bending it.
      const oc = colorFor(row._override), oi = styleInfo(row._override);
      genreBody.innerHTML =
        `<div class="genre-src">manual override</div>` +
        `<span class="chip overridden" style="--c:${oc}" title="manually set">` +
        `<span class="dot ${oi.shape}" style="background:${oc}"></span>` +
        `${escapeHtml(row._override)}</span>`;
      row._genreList = [{style: row._override, score: 1}];
      return;
    }
    const idMode = (row._idOverride || GLOBAL.identity);
    if (row._adjusted && row._adjusted.length){
      // Hand adjustments outrank every automatic read: they ARE the read now.
      // Shown whole rather than thresholded -- a genre you pushed down to 1%
      // disappearing from the list makes the press look like it did nothing.
      shown = row._adjusted.map(s => ({style:s.style, score:s.score, other:false}));
      srcLabel = 'genre · adjusted by hand';
    } else if (idMode === 'v2' && data.salience && data.salience.length){
      const named = data.salience.filter(s => s.score >= 0.03);
      const namedSum = named.reduce((a, s) => a + s.score, 0);
      const otherSum = Math.max(0, 1 - namedSum);
      shown = named.map(s => ({style:s.style, score:s.score, other:false}));
      if (otherSum > 0.005) shown.push({style:'Other', score:otherSum, other:true});
      srcLabel = 'genre · weighted by energy';
    } else if (useTimeline){
      // v1: flat % of track by frame count, over the lens-processed stream
      const all = timelinePercents(ws.segments);
      const named = all.filter(s => s.score >= 0.03);
      const otherSum = all.filter(s => s.score < 0.03).reduce((a, s) => a + s.score, 0);
      shown = named.map(s => ({style:s.style, score:s.score, other:false}));
      if (otherSum > 0.005) shown.push({style:'Other', score:otherSum, other:true});
      srcLabel = 'v1 · % of track (flat)';
    } else {
      shown = styles.slice(0, 5).filter(s => s.score >= 0.02)
                    .map(s => ({style:s.style, score:s.score, other:false}));
      if (!shown.length) shown = styles.slice(0, 1).map(s => ({style:s.style, score:s.score}));
      srcLabel = 'model confidence';
    }
    const tot = shown.reduce((a, s) => a + s.score, 0) || 1;
    const pct = v => (v * 100 < 0.5 && v > 0) ? '<1' : (v * 100).toFixed(0);
    // headline = top non-Other genre (never lead with "Other")
    const head = shown.find(s => !s.other) || shown[0];
    const hcol = head.other ? OTHER_COLOR : colorFor(head.style);
    const hshape = head.other ? 'hx' : styleInfo(head.style).shape;

    const segHtml = shown.map(s => {
      const col = s.other ? OTHER_COLOR : colorFor(s.style);
      const inf = s.other ? {tex:'none'} : styleInfo(s.style);
      const tex = inf.tex !== 'none' ? `background-image:${inf.tex};background-size:5px 5px;` : '';
      return `<i style="width:${(s.score/tot*100).toFixed(1)}%;background-color:${col};${tex}"
          title="${escapeHtml(s.style)} ${(s.score*100).toFixed(0)}%"></i>`;
    }).join('');
    const itemsHtml = shown.map((s, i) => {
      const col = s.other ? OTHER_COLOR : colorFor(s.style);
      const shp = s.other ? 'hx' : styleInfo(s.style).shape;
      const click = s.other ? ''
        : ` class="sw ${shp} swc" data-genre="${escapeHtml(s.style)}" data-hex="${col}" title="click to recolor"`;
      const sw = s.other ? `<span class="sw ${shp}" style="background:${col}"></span>`
                         : `<span${click} style="background:${col}"></span>`;
      // top-3 non-Other styles get descending emphasis (#1 largest → #3 smallest)
      const rank = (!s.other && i < 3) ? ` rank-${i + 1}` : '';
      return `<span class="bd-item${rank}">${sw}<b>${escapeHtml(s.style)}</b> ${pct(s.score)}%</span>`;
    }).join('');

    let customHtml = '';
    if (data.custom && data.custom.length){
      const cs = data.custom.filter(s => s.score >= 0.05).slice(0,4);
      const citems = (cs.length ? cs : data.custom.slice(0,1)).map(s => {
        const inf = styleInfo(s.style);
        return `<span><span class="sw ${inf.shape}" style="background:${inf.color}"></span>` +
          `<b>${escapeHtml(s.style)}</b> ${(s.score*100).toFixed(0)}%</span>`;
      }).join('');
      customHtml = `<div class="customrow"><span class="ctag">custom</span>` +
                   `<span class="breakdown" style="display:inline-flex">${citems}</span></div>`;
    }

    const headFam = head.other ? null : familyOf(head.style);
    const famHtml = (headFam && headFam.toLowerCase() !== head.style.toLowerCase())
      ? `<span class="famtag" title="PulseRoots family roll-up">\u25c7 ${escapeHtml(headFam)}</span>` : '';
    genreBody.innerHTML =
      `<div class="genre-src">${srcLabel}</div>` +
      `<span class="chip" style="--c:${hcol}"
        title="${escapeHtml(head.style)} \u2014 ${srcLabel}">
        <span class="dot ${hshape}" style="background:${hcol}"></span>${escapeHtml(head.style)}</span>${famHtml}
      <div class="blend">${segHtml}</div>
      <div class="breakdown">${itemsHtml}</div>${customHtml}`;

    row._genreList = shown;
  };
  renderGenreCell();
  row._renderGenre = renderGenreCell;

  // click a genre swatch to recolor it everywhere (delegated; survives re-renders)
  if (!genreCell._recolorBound){
    genreCell._recolorBound = true;
    genreCell.addEventListener('click', e => {
      const sw = e.target.closest('.swc');
      if (!sw) return;
      openColorPicker(sw.dataset.genre.toLowerCase(), sw.dataset.hex, sw);
    });
  }

  /* ---- adjust: bend the blend instead of replacing it ----
     An override answers "what is this track" with one word and throws away
     everything the model got right. This nudges each genre's share up or down
     and renormalises, so "this is a VERY house track" and "that Tech Trance is a
     misread" are both sayable without flattening the rest to zero. Same endpoint
     and the same stored steps the map's popup writes, so a track adjusted on one
     screen reads identically on the other. */
  const adjBtn = document.createElement('button');
  adjBtn.className = 'override-btn adj-btn';
  adjBtn.textContent = '⚖ adjust';
  adjBtn.title = 'nudge how much of each genre this track is — keeps the rest of the read';
  genreCell.appendChild(adjBtn);

  const adjBox = document.createElement('div');
  adjBox.className = 'pop-adj row-adj';
  adjBox.hidden = true;
  adjBox.innerHTML = adjustPanelHtml();

  /* ---- manual genre override ---- */
  const overrideBtn = document.createElement('button');
  overrideBtn.className = 'override-btn';
  overrideBtn.textContent = '✎ override';
  overrideBtn.title = 'set the genre yourself — persists across reloads + saved as training data';
  genreCell.appendChild(overrideBtn);

  /* ---- omit: delete this analysis entirely (e.g. a bogus read) ---- */
  const omitBtn = document.createElement('button');
  omitBtn.className = 'override-btn omit-btn';
  omitBtn.textContent = '✕ omit';
  omitBtn.title = 'delete this analysis — remove the track from your library (audio untouched)';
  genreCell.appendChild(omitBtn);
  omitBtn.addEventListener('click', async () => {
    if (!window.confirm(`Remove "${data.title}" from your library?\n\n`
      + `Deletes its analysis (genre, BPM, key) and takes it off the map. `
      + `The audio file is untouched.`)) return;
    const res = getResult();
    if (res && res.hash){ try{ await fetch(`/forget/${res.hash}`, {method:'POST'}); }catch(_){} }
    results = results.filter(r => r.row !== row);
    EXTRAS.forget(row); row.remove();
    if (!rowsEl.querySelector('.row')) emptyEl.style.display = '';
    refreshFooter();
  });

  /* ---- 🔎 external metadata lookup (Discogs / MusicBrainz / Last.fm) ---- */
  const lookupBtn = document.createElement('button');
  lookupBtn.className = 'override-btn lookup-btn';
  lookupBtn.textContent = '🔎 lookup';
  lookupBtn.title = 'look up genres/tags for this track from Discogs, MusicBrainz & Last.fm';
  genreCell.appendChild(lookupBtn);

  const lookupPanel = document.createElement('div');
  lookupPanel.className = 'lookup-panel';
  lookupPanel.style.display = 'none';
  genreCell.appendChild(lookupPanel);

  let lookupLoaded = false;
  lookupBtn.addEventListener('click', async () => {
    if (lookupPanel.style.display !== 'none'){ lookupPanel.style.display = 'none'; return; }
    lookupPanel.style.display = '';
    if (lookupLoaded) return;
    const res = getResult();
    const hash = data.hash || (res && res.hash);
    if (!hash){ lookupPanel.innerHTML = '<div class="lk-note">no hash for this track yet</div>'; return; }
    lookupPanel.innerHTML = '<div class="lk-note">searching Discogs · MusicBrainz · Last.fm…</div>';
    let j;
    try { j = await fetch(`/lookup/${hash}`).then(r => r.json()); }
    catch(_){ lookupPanel.innerHTML = '<div class="lk-note">lookup failed</div>'; return; }
    lookupLoaded = true;
    renderLookup(lookupPanel, row, hash, j);
  });

  const editor = document.createElement('div');
  editor.className = 'override-editor';
  editor.style.display = 'none';
  const oInput = document.createElement('input');
  oInput.type = 'text'; oInput.placeholder = 'e.g. Riddim, Tearout, Colour Bass…';
  const oSave = document.createElement('button');
  oSave.className = 'ovr-save'; oSave.textContent = 'save + train';
  const oCancel = document.createElement('button');
  oCancel.className = 'ovr-cancel'; oCancel.textContent = 'cancel';
  editor.append(oInput, oSave, oCancel);
  genreCell.appendChild(editor);

  const trainBadge = document.createElement('div');
  trainBadge.className = 'train-badge';
  genreCell.appendChild(trainBadge);

  // Appended after the whole button strip so opening it drops a panel below the
  // controls rather than shoving half of them onto the next line.
  genreCell.appendChild(adjBox);

  /* Vibes and tags share one wrapping strip. They used to be two separate
     blocks, each claiming a full-width band of a column only 300px wide, so a
     track with two vibes and three tags spent five short lines saying very
     little and pushed everything under it down the row. As one flow they fill
     each line before starting another. Both holders are created here, in a
     fixed order, because panels.js fills them from two independent fetches --
     whichever landed first used to decide which appeared on top. */
  const chipsRow = document.createElement('div');
  chipsRow.className = 'rowchips';
  const vibesHolder = document.createElement('div');
  vibesHolder.className = 'vibematches';
  const tagsHolder = document.createElement('div');
  tagsHolder.className = 'tagchips';
  chipsRow.append(vibesHolder, tagsHolder);
  genreCell.appendChild(chipsRow);
  /* The row's adjust panel: same widget as the map popup's (wireAdjustPanel),
     same /weights endpoint, same stored steps, so a track nudged on either
     screen reads the same on both. `hashOf` is a getter because a just-dropped
     row gets its hash from the server a moment after the row exists;
     re-rendering the genre cell is what makes the percentages move as you
     press. */
  const showAdjusted = state => { applyAdjusted(row, state); renderGenreCell(); };
  wireAdjustPanel(adjBtn, adjBox, {
    hashOf: () => data.hash || ((getResult() || {}).hash || null),
    // Only redraw the cell when there is actually an adjustment to show.
    // Merely opening the panel must not repaint a row -- on an overridden
    // track that would swap the override chip for the model read nobody asked
    // to see again.
    onLoaded: state => { if (row._adjusted || adjustHasEdits(state)) showAdjusted(state); },
    onSaved: showAdjusted,
  });

  overrideBtn.addEventListener('click', () => {
    editor.style.display = 'flex';
    overrideBtn.style.display = 'none';
    oInput.value = '';
    oInput.focus();
  });
  oCancel.addEventListener('click', () => {
    editor.style.display = 'none';
    overrideBtn.style.display = '';
  });
  oInput.addEventListener('keydown', e => { if (e.key === 'Enter') oSave.click(); });

  // likely-misread hint: click to override with the neighbour-suggested genre
  const nc = data.neighbor_check;
  if (nc && nc.flag){
    const warn = document.createElement('div');
    warn.className = 'row-flag';
    warn.innerHTML = `⚠ low-confidence — sounds like <b>${escapeHtml(nc.suggested_style)}</b>`;
    warn.title = 'nearest tracks disagree with this read · click to override to the suggestion';
    warn.addEventListener('click', () => {
      overrideBtn.click();                 // opens + clears the editor
      oInput.value = nc.suggested_style;
      oInput.focus();
    });
    genreCell.appendChild(warn);
  }

  // find this track's result entry so we can use the stored file/filepath
  function getResult(){ return results.find(r => r.row === row); }

  oSave.addEventListener('click', async () => {
    const genre = oInput.value.trim();
    if (!genre) return;

    // 1. show it. Through renderGenreCell like every other read, so a saved
    //    override and one loaded from the database can't drift apart.
    row._override = genre;
    renderGenreCell();
    // An override supersedes any hand adjustment -- the steps stay on the server,
    // but this row now reads as the one word you gave it. Only the body is
    // rewritten, so adjust / omit / lookup stay where they were: changing your
    // mind afterwards doesn't mean reloading the track to get the controls back.
    row._adjusted = null;
    adjBox.hidden = true;
    editor.style.display = 'none';
    overrideBtn.style.display = '';

    // update results so export uses the override label
    const res = getResult();
    if (res) res.overrideGenre = genre;

    // 2. persist the override to the DB (survives reload, same as the map's
    //    ✎ override) + save a training copy to ~/genre_training/<genre>/.
    oSave.disabled = true; oSave.textContent = 'saving…';
    try {
      const res2 = getResult();
      const hash = res2 && res2.hash;
      let trained = false;
      if (hash){
        // /override sets payload["override"] so the dominant style sticks; it
        // also files the audio for training when the DB has a server-side path.
        const r = await fetch(`/override/${hash}`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({genre}),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || 'override failed');
        trained = !!j.trained;
      }
      // dropped files have no server-side path -> re-upload the file so the
      // training copy still gets saved (the override above already persisted).
      if (!trained && file){
        const fd = new FormData();
        fd.append('genre', genre); fd.append('file', file);
        const r = await fetch('/save_training', {method:'POST', body:fd});
        if (r.ok) trained = true;
      }
      trainBadge.textContent = trained
        ? `✓ saved · training copy in ~/genre_training/${escapeHtml(genre)}/`
        : '✓ override saved (persists across reloads)';
      trainBadge.classList.add('show');
    } catch(err){
      trainBadge.textContent = `⚠ save failed: ${err.message}`;
      trainBadge.classList.add('show');
    }
  });

  /* ---- compare engines: EffNet vs MAEST vs merged (on-demand) ---- */
  const cmpBtn = document.createElement('button');
  cmpBtn.className = 'compare-btn';
  cmpBtn.textContent = '⚖ compare engines';
  cmpBtn.title = 'run MAEST (transformer) alongside EffNet and merge them — slower (~15s), on demand';
  const cmpBox = document.createElement('div');
  cmpBox.className = 'compare-box';
  cmpBox.style.display = 'none';
  genreCell.appendChild(cmpBtn);
  genreCell.appendChild(cmpBox);

  cmpBtn.addEventListener('click', async () => {
    if (cmpBox.style.display !== 'none' && cmpBox.dataset.done){   // toggle closed
      cmpBox.style.display = 'none'; cmpBox.dataset.done = ''; return;
    }
    cmpBtn.disabled = true; cmpBtn.textContent = 'running MAEST…';
    cmpBox.style.display = 'block';
    cmpBox.innerHTML = '<div class="cmp-wait">running MAEST transformer (~15s on CPU)…</div>';
    try {
      const fd = new FormData();
      const res = getResult();
      if (res && res.filepath) fd.append('filepath', res.filepath);
      else if (file) fd.append('file', file);
      else { cmpBox.innerHTML = '<div class="cmp-wait">no file available to compare</div>'; return; }
      const r = await fetch('/compare', {method:'POST', body:fd});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      renderCompareInto(cmpBox, j);
      cmpBox.dataset.done = '1';
    } catch(err){
      cmpBox.innerHTML = `<div class="cmp-wait">compare failed: ${escapeHtml(err.message)}</div>`;
    } finally {
      cmpBtn.disabled = false; cmpBtn.textContent = '⚖ compare engines';
    }
  });

  /* details panel + toggle button */
  const t = (data.tags && data.tags.tag) || {};
  const tech = (data.tags && data.tags.tech) || {};
  const order = ["title","artist","album","albumartist","genre","date","tracknumber","discnumber","composer","bpm"];
  const nice = {albumartist:"album artist", tracknumber:"track", discnumber:"disc", bpm:"bpm (tag)"};
  let dhtml = '';
  const tagRows = order.filter(k => t[k])
    .map(k => `<div>${escapeHtml(nice[k]||k)}: <b>${escapeHtml(t[k])}</b></div>`).join('');
  dhtml += `<div class="sect">File tags</div>` +
           (tagRows || `<div>no tags in this file</div>`);
  dhtml += `<div class="sect">Technical</div>`;
  dhtml += `<div>file: <b>${escapeHtml(data.filename)}</b></div>`;
  for (const k of ["format","bitrate","sample rate","channels"]){
    if (tech[k]) dhtml += `<div>${escapeHtml(k)}: <b>${escapeHtml(tech[k])}</b></div>`;
  }
  const det = document.createElement('div');
  det.className = 'details';
  det.innerHTML = dhtml;
  const btn = document.createElement('button');
  btn.className = 'info'; btn.type = 'button';
  btn.textContent = 'i'; btn.title = 'show file tags & details';
  btn.addEventListener('click', () => det.classList.toggle('open'));
  row.appendChild(btn);
  row.appendChild(det);

  results.push({title:data.title, filename:data.filename, filepath:data.filepath||null,
                hash:data.hash||null,
                styles:styles, row:row, custom:data.custom||null,
                bpm:data.bpm, bpmText:bpmText, camelot:data.camelot,
                key:data.key, scale:data.scale,
                duration:data.duration, ok:true});

  /* cached badge: this analysis came from the DB, no compute happened */
  if (data.cached){
    const t = row.querySelector('.file');
    if (t){
      const tag = document.createElement('span');
      tag.className = 'cached-tag'; tag.textContent = '· cached';
      tag.title = 'previously analyzed -- served instantly from the database';
      t.appendChild(tag);
    }
  }

  /* vibe matches, tags and the detailed waveform: asked for when the row
     scrolls into view, batched with whatever else comes into view with it. */
  if (data.hash) EXTRAS.want(row, data.hash);
  refreshFooter();
}

/* ---- per-row extras, fetched on sight --------------------------------------
   Every finished row wants three things the server has to be asked for: its
   tags, which vibes it matches, and the detailed waveform. Asked per row the
   moment the row existed, re-dropping a folder of already-analysed tracks was
   three requests per row -- nine thousand for a big folder -- almost all for
   rows below the bottom of the screen. So a row registers what it wants and
   is asked for it when it comes into view, and the rows that come into view
   together share one /tags/for and one /vibes/match request between them. */
const EXTRAS = (() => {
  const pending = new Map();       // row -> hash, registered but not yet seen
  const due = [];                  // [row, hash] seen and waiting for the next flush
  let timer = null;
  const io = ('IntersectionObserver' in window) ? new IntersectionObserver(entries => {
    for (const e of entries){
      if (!e.isIntersecting || !pending.has(e.target)) continue;
      due.push([e.target, pending.get(e.target)]);
      pending.delete(e.target); io.unobserve(e.target);
    }
    if (due.length && !timer) timer = setTimeout(flush, 40);   // let the scroll settle
  }, { rootMargin: '240px 0px' }) : null;

  async function flush(){
    timer = null;
    const batch = due.splice(0).filter(([row]) => row.isConnected);
    if (!batch.length) return;
    const q = encodeURIComponent([...new Set(batch.map(([, h]) => h))].join(','));
    const grab = url => fetch(url).then(r => r.ok ? r.json() : {}).catch(() => ({}));
    const [tags, vibes] = await Promise.all([grab(`/tags/for?hashes=${q}`), grab(`/vibes/match?hashes=${q}`)]);
    for (const [row, h] of batch){
      if (!row.isConnected) continue;
      renderVibeMatches(row, h, vibes[h] || []);
      renderTags(row, h, tags[h] || []);
      if (row._fetchWave) row._fetchWave();
    }
  }
  return {
    want(row, hash){
      if (!io){ due.push([row, hash]); if (!timer) timer = setTimeout(flush, 0); return; }
      pending.set(row, hash); io.observe(row);
    },
    forget(row){ pending.delete(row); if (io) io.unobserve(row); },
  };
})();

/* Every genre name the app can offer: the library's own keystones and their
   subgenres, fetched once, plus whatever the rows on screen actually read as.
   Feeds the shared <datalist> behind "add a genre it missed" -- the same list
   the map's override box uses, so both screens complete the same names. */
let GENRE_NAMES = null;
async function fillGenreList(extra){
  const dl = document.getElementById('ovr-genre-list');
  if (!dl) return;
  // Painted twice on the first call: once now, from what is already known (the
  // caller's names and the rows on screen), and again when the library's own
  // list lands -- that fetch is a whole-library pass and the box should
  // complete something while it runs.
  const paint = () => {
    const set = new Set([...(GENRE_NAMES || []), ...(extra || [])]);
    for (const r of results) for (const st of (r.styles || [])) if (st && st.style) set.add(st.style);
    dl.innerHTML = [...set].sort((a, b) => a.localeCompare(b))
      .map(g => `<option value="${escapeHtml(g)}"></option>`).join('');
  };
  paint();
  if (GENRE_NAMES !== null) return;
  GENRE_NAMES = [];                         // set first: a slow fetch shouldn't
  try {                                     // start a second one on the next click
    const j = await fetch('/genres?flat=1&top=0').then(r => r.json());
    if (Array.isArray(j)){
      const set = new Set();
      for (const g of j){
        if (g && g.keystone) set.add(g.keystone);
        for (const sg of (g.subgenres || [])) if (sg && sg.style) set.add(sg.style);
      }
      GENRE_NAMES = [...set];
    }
  } catch(_){ /* offline, or an empty library -- typing a name still works */ }
  paint();
}

/* Hand a row its adjusted blend, or take it away again. Cleared when no step is
   left, so undoing every adjustment restores exactly what the model said rather
   than freezing the last adjusted numbers in place. */
function applyAdjusted(row, state){
  row._adjusted = (adjustHasEdits(state) && state.adjusted && state.adjusted.length)
    ? state.adjusted.map(e => ({style: e.style, score: e.score}))
    : null;
}

/* ---- the adjust panel -----------------------------------------------------
   One widget, used by the map popup and by every Analyzer row. An override
   answers "what is this" with one word and throws away everything the model
   got right; this bends the read instead: each genre carries a step you raise
   or lower, so "this is a VERY house track" and "that Tech Trance is a
   misread" are both sayable without flattening the rest to zero. The step is
   what's stored, never the multiplier it computes -- the server can retune
   the curve without silently rewriting what you meant by it.

   `wireAdjustPanel(btn, box, opts)`:
     hashOf()          the track's hash, or null if it has none yet (a getter,
                       because a just-dropped row learns its hash later)
     genres()          extra names to offer in the "add a genre" completion
     complete(text)    a completer for the add box (Tab / on add); optional
     onOpen/onClose()  the panel showed / hid -- for chrome around it
     onLoaded(state)   the track's read arrived
     onSaved(state)    the server accepted a press; state.adjusted is current */
function adjustPanelHtml(){
  return `<div class="ovr-h">how much of each genre is this?</div>
    <div class="adj-rows"><span class="pop-bar">\u2026</span></div>
    <div class="ovr-typed">
      <input class="adj-add-in" type="text" placeholder="add a genre it missed\u2026" list="ovr-genre-list"
             autocomplete="off" spellcheck="false">
      <button class="adj-add">add</button>
      <button class="adj-close" title="done">\u2715</button>
    </div>
    <div class="ovr-hint">Nudges the read instead of replacing it \u2014 use <b>override</b> if it's flat wrong.</div>`;
}

/* Whether a panel state carries any edit at all. */
function adjustHasEdits(state){
  return !!(state && ((state.steps && Object.keys(state.steps).length)
                   || (state.drops && state.drops.length)));
}

function wireAdjustPanel(btn, box, opts){
  const rowsEl_ = box.querySelector('.adj-rows');
  const addIn = box.querySelector('.adj-add-in');
  const call = (k, ...a) => { if (typeof opts[k] === 'function') return opts[k](...a); };
  let state = null;      // {steps, drops, base, adjusted, max_step, words}
  let saving = null;     // in-flight POST, so rapid presses coalesce in order

  const wordFor = st => (state && state.words && state.words[String(st)]) || 'as read';

  function render(){
    if (!state){ rowsEl_.innerHTML = `<span class="pop-bar">\u2026</span>`; return; }
    const drops = state.drops || [];
    const shown = new Map();
    for (const e of state.adjusted || []) shown.set(e.style, e.score);
    // A genre pushed all the way down falls out of the top-N. Keep its row on
    // screen anyway, or the press that removed it leaves nothing to undo it with.
    for (const g of Object.keys(state.steps || {})) if (!shown.has(g)) shown.set(g, 0);
    for (const g of drops) shown.delete(g);          // removed: listed below instead
    const max = state.max_step || 3;
    const rowsHtml = [...shown.entries()].map(([style, score]) => {
      const step = (state.steps || {})[style] || 0;
      const pct = Math.round((score || 0) * 100);
      return `<div class="adj-row${step ? ' moved' : ''}" data-g="${escapeHtml(style)}">
        <button class="adj-step" data-d="-1" ${step <= -max ? 'disabled' : ''} title="less">\u2212</button>
        <button class="adj-step" data-d="1" ${step >= max ? 'disabled' : ''} title="more">\uff0b</button>
        <span class="adj-meter" title="${escapeHtml(style)} \u2014 ${escapeHtml(wordFor(step))}">
          <i style="width:${pct}%"></i>
          <b>${escapeHtml(style)}</b>${step ? `<em>${escapeHtml(wordFor(step))}</em>` : ''}
        </span>
        <span class="adj-pct">${pct}%</span>
        <button class="adj-drop" title="remove ${escapeHtml(style)} from this track">\u2715</button>
      </div>`;
    }).join('');
    // Removed genres are named, not merely gone. A remove you cannot see is a
    // remove you cannot undo, and "why is this track missing a genre" is a
    // question the panel should still be able to answer a week later.
    const dropHtml = drops.length
      ? `<div class="adj-dropped"><span class="ovr-h">removed</span>` +
        drops.map(g => `<button class="adj-restore" data-g="${escapeHtml(g)}"` +
          ` title="put ${escapeHtml(g)} back on this track">${escapeHtml(g)} \u21a9</button>`).join('') +
        `</div>`
      : '';
    if (!shown.size && !drops.length){
      rowsEl_.innerHTML = `<div class="ovr-h">nothing read for this track</div>`;
      return;
    }
    rowsEl_.innerHTML = rowsHtml + dropHtml;
    for (const b of rowsEl_.querySelectorAll('.adj-step')){
      b.onclick = () => bump(b.closest('.adj-row').dataset.g, Number(b.dataset.d));
    }
    for (const b of rowsEl_.querySelectorAll('.adj-drop')){
      b.onclick = () => drop(b.closest('.adj-row').dataset.g);
    }
    for (const b of rowsEl_.querySelectorAll('.adj-restore')){
      b.onclick = () => restore(b.dataset.g);
    }
  }

  // Remove a genre outright. Not the same press as -3: "not at all" leaves it in
  // the read at a trace, this takes it off the track entirely. The share it held
  // is redistributed by the server, so the rest of the blend closes the gap.
  function drop(style){
    if (!state) return;
    const drops = state.drops || [];
    if (drops.includes(style)) return;
    state.drops = [...drops, style];
    state.steps = {...(state.steps || {})};
    delete state.steps[style];             // "more of this" and "none of this"
    render();                              //  cannot both be what you meant
    save();
  }

  function restore(style){
    if (!state) return;
    state.drops = (state.drops || []).filter(g => g !== style);
    render();
    save();
  }

  // Optimistic: the meter moves on the press and the server's answer replaces it
  // a moment later. Waiting for the round-trip made +/- feel broken.
  function bump(style, delta){
    if (!state) return;
    const max = state.max_step || 3;
    const next = Math.max(-max, Math.min(max, ((state.steps || {})[style] || 0) + delta));
    state.steps = {...(state.steps || {})};
    if (next) state.steps[style] = next; else delete state.steps[style];
    render();
    save();
  }

  function save(){
    const hash = opts.hashOf();
    if (!hash) return;
    const steps = state.steps || {};
    const drops = state.drops || [];
    saving = (saving || Promise.resolve()).then(async () => {
      try {
        const r = await fetch(`/weights/${hash}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({steps, drops})});
        const body = await r.json();
        // Identity, not equality: a press during the round-trip replaced both
        // objects, and its own save is already queued behind this one.
        if (steps !== state.steps || drops !== state.drops) return;
        state.steps = body.steps || {};
        state.drops = body.drops || [];
        state.adjusted = (body.adjusted && body.adjusted.length) ? body.adjusted : state.base;
        render();
        call('onSaved', state);
      } catch(_){ /* the meter already moved; the next press retries */ }
    });
  }

  const close = () => { box.hidden = true; call('onClose'); };

  btn.onclick = async () => {
    if (!box.hidden){ close(); return; }
    box.hidden = false;
    call('onOpen');
    fillGenreList([...(call('genres') || []), ...Object.keys((state && state.steps) || {})]);
    const hash = opts.hashOf();
    if (!hash){ rowsEl_.innerHTML = `<div class="ovr-h">no hash for this track yet</div>`; return; }
    rowsEl_.innerHTML = `<span class="pop-bar">\u2026</span>`;
    try { state = await (await fetch(`/weights/${hash}`)).json(); }
    catch(_){ rowsEl_.innerHTML = `<div class="ovr-h">couldn't load this track's read</div>`; return; }
    if (state && state.error){
      rowsEl_.innerHTML = `<div class="ovr-h">${escapeHtml(state.error)}</div>`;
      state = null; return;
    }
    render();
    call('onLoaded', state);
  };
  box.querySelector('.adj-close').onclick = close;

  const complete = text => (opts.complete ? opts.complete(text) : null);
  const addGenre = () => {
    const g = complete(addIn.value) || (addIn.value || '').trim();
    if (!g || !state) return;
    addIn.value = '';
    // Enters at "moderately": a genre you had to type out is one you mean, and
    // +1 read as barely-there next to everything the model already found.
    if (!(state.steps || {})[g]){
      state.steps = {...(state.steps || {}), [g]: 2};
      render(); save();
    }
  };
  box.querySelector('.adj-add').onclick = addGenre;
  addIn.addEventListener('keydown', e => {
    if (e.key === 'Enter'){ e.preventDefault(); addGenre(); }
    else if (e.key === 'Escape'){ close(); }
    else if (e.key === 'Tab' && addIn.value.trim()){
      const hit = complete(addIn.value);
      if (hit && hit.toLowerCase() !== addIn.value.trim().toLowerCase()){
        e.preventDefault(); addIn.value = hit;
        addIn.setSelectionRange(hit.length, hit.length);
      }
    }
  });
}

function failRow(row, msg){
  row.classList.remove('pending');
  row.classList.add('error');
  row.children[2].innerHTML = `<span class="chip">failed: ${escapeHtml(msg)}</span>`;
  refreshFooter();
}

async function pump(){
  if (busy) return;
  busy = true;
  let known = 0;
  while (queue.length){
    const {file, handle, row} = queue.shift();
    const fd = new FormData();
    fd.append('file', file);
    try{
      const resp = await fetch('/analyze', {method:'POST', body:fd});
      const data = await resp.json();
      // Persist a file handle (drag-drop / native picker) so this track stays
      // playable across restarts — even on a cache hit, which has no other source.
      if (handle && data.hash) FSH.put(data.hash, handle);
      if (resp.ok && data.cached){
        // Already analyzed, this session or a previous one. It used to be pulled
        // out of the list entirely, which read as "nothing happened": you dropped
        // a track in and got back the same empty screen. It stays now, marked
        // `· cached`, carrying every row control a fresh analysis gets --
        // which is the only way to reach adjust / override / omit for a track you
        // already know about without going hunting for it in the Library.
        const dupe = data.hash && results.find(r => r.hash === data.hash);
        if (dupe && dupe.row){
          // Same audio under a second filename. One row, revealed, rather than
          // two rows of the same track disagreeing about which one you edited.
          row.remove();
          dupe.row.scrollIntoView({behavior: 'smooth', block: 'center'});
          flashRow(dupe.row);
        } else {
          finishRow(row, data, file);
          flashRow(row);
        }
        known++;
        continue;
      }
      if (!resp.ok) failRow(row, data.error || resp.statusText);
      else finishRow(row, data, file);
    }catch(e){
      failRow(row, 'server unreachable');
    }
  }
  busy = false;
  if (!rowsEl.querySelector('.row')) emptyEl.style.display = '';   // list went empty
  if (known){
    const bs = document.getElementById('batch-status');
    if (bs){
      bs.textContent = `✓ ${known} already analyzed · loaded from your library`;
      setTimeout(() => { if (bs.textContent.startsWith('✓')) bs.textContent = ''; }, 4000);
    }
  }
  refreshFooter();
}

/* dedupe the drop/browse list by name+size, so re-dropping a file already in
   the list is a no-op (the server would cache-hit it anyway; this just avoids a
   redundant row). Cleared by "Clear list". */
// key -> the row it produced, so re-dropping a file already on screen can point
// at it instead of reporting a silent "skipped 1 duplicate" and doing nothing.
const listKeys = new Map();
const fileKey = f => `${f.name}::${f.size}`;

// Accepts a list of File objects, or {file, handle} pairs where handle is a
// FileSystemFileHandle (from drag-drop / the native picker) we persist for replay.
function enqueue(items){
  let skipped = 0;
  for (const it of items){
    const f = it.file || it;                 // File, or {file, handle}
    const handle = it.handle || null;
    const key = fileKey(f);
    if (listKeys.has(key)){                          // already in the list
      skipped++;
      const prev = listKeys.get(key);
      if (prev && prev.isConnected){
        prev.scrollIntoView({behavior: 'smooth', block: 'center'});
        flashRow(prev);
      }
      continue;
    }
    const newRow = addRow(f);
    listKeys.set(key, newRow);
    queue.push({file:f, handle, row:newRow});
  }
  if (skipped){
    const bs = document.getElementById('batch-status');
    if (bs){
      bs.textContent = `${skipped} already on this list`;
      setTimeout(() => { if (bs.textContent.includes('already on this list')) bs.textContent = ''; }, 2600);
    }
  }
  pump();
}

/* drag & drop -- the whole main window is the drop target */
['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('over');
}));
drop.addEventListener('dragleave', e => {
  // only clear when the cursor actually leaves the window, not its children
  if (!drop.contains(e.relatedTarget)) drop.classList.remove('over');
});
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('over');
  const items = [...(e.dataTransfer.items || [])].filter(it => it.kind === 'file');
  if (items.length && typeof items[0].getAsFileSystemHandle === 'function'){
    // Grab both the File and the persistable handle. Both getters must be called
    // synchronously while the DataTransfer is still alive, so kick them off now.
    const files = items.map(it => it.getAsFile());
    const handleP = items.map(it => {
      try { return Promise.resolve(it.getAsFileSystemHandle()).catch(() => null); }
      catch(_){ return Promise.resolve(null); }
    });
    Promise.all(handleP).then(handles => {
      const pairs = files.map((f, i) => {
        let h = handles[i]; if (h && h.kind !== 'file') h = null;   // ignore dropped folders
        return f ? {file:f, handle:h} : null;
      }).filter(Boolean);
      if (pairs.length) enqueue(pairs);
    });
  } else {
    const files = [...e.dataTransfer.files];
    if (files.length) enqueue(files);
  }
});
picker.addEventListener('change', () => {
  if (picker.files.length) enqueue([...picker.files]);
  picker.value = '';
});
// The Browse button is a <label for="picker">. Where the File System Access API
// exists (WebView2/Chromium), intercept it and use the native picker instead, so
// we get a persistable handle; otherwise the plain <input> default runs.
const AUDIO_EXTS = ['.mp3','.flac','.m4a','.mp4','.aac','.ogg','.oga','.opus','.wav',
  '.aif','.aiff','.aifc','.wma','.alac','.wv','.ape','.mpc','.dsf'];
async function browseWithPicker(){
  try{
    const handles = await window.showOpenFilePicker({
      multiple: true,
      types: [{ description: 'Audio files', accept: { 'audio/*': AUDIO_EXTS } }],
    });
    const pairs = (await Promise.all(handles.map(async h => {
      try { return {file: await h.getFile(), handle: h}; } catch(_){ return null; }
    }))).filter(Boolean);
    if (pairs.length) enqueue(pairs);
  }catch(err){
    if (err && err.name === 'AbortError') return;   // user cancelled the dialog
    picker.click();                                  // any other failure -> plain input
  }
}
const browseLabel = document.querySelector('label.browse[for="picker"]');
if (browseLabel && window.showOpenFilePicker){
  browseLabel.addEventListener('click', e => { e.preventDefault(); browseWithPicker(); });
}
// click the empty hero to browse (the Browse button in the footer also opens it)
if (emptyEl) emptyEl.addEventListener('click', () => {
  if (window.showOpenFilePicker) browseWithPicker(); else picker.click();
});

/* export */
exportB.addEventListener('click', () => {
  const ok = results.filter(r => r.ok);
  const stamp = new Date().toISOString().slice(0,16).replace('T',' ');
  const lines = [
    `Genre v2 export \u2014 ${stamp}`,
    `${ok.length} track${ok.length===1?'':'s'}`,
    ''.padEnd(46,'-'),
    ...ok.map(r => {
      const glist = (r.row && r.row._genreList) ? r.row._genreList : r.styles;
      const blend = r.overrideGenre
        ? `${r.overrideGenre} [manual]`
        : glist.map(s => `${s.style} ${(s.score*100).toFixed(0)}%`).join(' | ');
      const custom = (r.custom && r.custom.length)
        ? '  \u2014  Custom: ' + r.custom.filter(s => s.score >= 0.05).slice(0,4)
            .map(s => `${s.style} ${(s.score*100).toFixed(0)}%`).join(' | ')
        : '';
      const bpm = r.bpm != null ? `${r.bpmText} BPM` : '--- BPM';
      // The file is for reading, so it is written in the notation you read in.
      const key = keyText(r) || '---';
      return `${r.title}  \u2014  ${bpm}  \u2014  ${key}  \u2014  ${fmtDur(r.duration)}  \u2014  ${blend}${custom}`;
    }),
    ''
  ];
  const blob = new Blob([lines.join('\n')], {type:'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `genre_list_${stamp.replace(/[: ]/g,'-')}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
});

clearB.addEventListener('click', () => {
  PLAYER.audio.pause();
  PLAYER.audio.removeAttribute('src');
  PLAYER.audio.load();
  if (PLAYER.ctl){ PLAYER.ctl.stopVisual(); PLAYER.ctl = null; }
  while (OBJ_URLS.length) URL.revokeObjectURL(OBJ_URLS.pop());
  // NOTE: HASH_FILES is intentionally kept — it lets tracks dropped this session
  // still play after the list is cleared (playSrc recreates a fresh blob URL).
  results = []; queue = [];
  listKeys.clear();
  rowsEl.querySelectorAll('.row').forEach(r => { EXTRAS.forget(r); r.remove(); });
  emptyEl.style.display = '';
  refreshFooter();
});

/* ---- the header graphic: the strip behind the app's name ----------------
   One of several small scenes, chosen under Options -> Appearance. The bar
   styles share one set of 48 animated spans and differ only in the paint; the
   wave, starfield and record are their own markup. Rebuilt on every change,
   so a style is never a leftover of the one before it. */
const EQ_STYLES = [['bars', 'bars'], ['blocks', 'LED blocks'], ['dots', 'bubbles'], ['glow', 'soft glow'],
                   ['wave', 'waveform'], ['stars', 'starfield'], ['vinyl', 'vinyl'], ['off', 'off']];
const EQ_COLORS = ['#22D3EE','#5DE9FF','#38BDF8','#7C5CFF','#67E8F9','#818CF8','#22D3EE'];
function applyEqStyle(){
  const el = document.getElementById('eq-bars');
  if (!el) return;
  const s = EQ_STYLES.some(([k]) => k === PREFS.eqStyle) ? PREFS.eqStyle : 'bars';
  el.className = 'eq-bars eq-' + s;
  el.innerHTML = '';
  // Seeded, so the scene is the same one every time the header is built.
  let seed = 7; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  if (s === 'bars' || s === 'blocks' || s === 'dots' || s === 'glow'){
    for (let i = 0; i < 48; i++){
      const b = document.createElement('span');
      const lo = Math.round(8 + rnd()*20), hi = Math.round(35 + rnd()*60);
      b.style.cssText = `--lo:${lo}%;--hi:${hi}%;--d:${(0.5 + rnd()*1.2).toFixed(2)}s;` +
        `--dl:${rnd().toFixed(2)}s;--c:${EQ_COLORS[i % EQ_COLORS.length]}`;
      el.appendChild(b);
    }
  } else if (s === 'wave'){
    // Two periods of a sine across half the width; the CSS slides it by one.
    let d = '';
    for (let i = 0; i <= 400; i++){
      const x = i / 400 * 2000, y = 27 + Math.sin(i / 400 * Math.PI * 8) * 14 + Math.sin(i / 400 * Math.PI * 26) * 4;
      d += (i ? ' L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
    }
    el.innerHTML = `<svg viewBox="0 0 2000 54" preserveAspectRatio="none">
      <defs><linearGradient id="eq-wave-grad" x1="0" x2="1"><stop offset="0" stop-color="${EQ_COLORS[0]}"/>
      <stop offset=".5" stop-color="${EQ_COLORS[3]}"/><stop offset="1" stop-color="${EQ_COLORS[0]}"/></linearGradient></defs>
      <path d="${d}"/></svg>`;
  } else if (s === 'stars'){
    for (let i = 0; i < 70; i++){
      const st = document.createElement('i');
      st.style.cssText = `left:${(rnd()*100).toFixed(1)}%;top:${(rnd()*100).toFixed(1)}%;` +
        `--d:${(1.5 + rnd()*3).toFixed(2)}s;--dl:${(rnd()*3).toFixed(2)}s;--c:${EQ_COLORS[i % EQ_COLORS.length]};` +
        `transform:scale(${(0.6 + rnd()).toFixed(2)})`;
      el.appendChild(st);
    }
  } else if (s === 'vinyl'){
    el.appendChild(document.createElement('i'));
  }
}
applyEqStyle();

/* ---- Batch folder analysis ---- */
const batchBtn = document.getElementById('batch-btn');
const batchStatus = document.getElementById('batch-status');
let batchRunning = false;
const BATCH_ROW_CAP = 250;   // most recent rows to keep on screen during a batch

batchBtn.addEventListener('click', () => {
  if (batchRunning){ return; }
  const path = prompt(
    'Enter the path to your music folder:\n(e.g. C:\\Users\\you\\Music)',
    'C:\\Users\\'
  );
  if (!path || !path.trim()) return;
  runBatch(path.trim());
});

async function runBatch(folderPath){
  batchRunning = true;
  batchBtn.classList.add('active');
  batchBtn.textContent = '⏸ running…';
  batchStatus.textContent = 'scanning…';
  clientLog(`batch start: ${folderPath}  (jsHeap=${jsHeapMB()}MB)`);

  try {
    const resp = await fetch('/batch', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path: folderPath, workers: 3})
    });
    if (!resp.ok){
      const j = await resp.json().catch(()=>({}));
      alert('Batch error: ' + (j.error || resp.statusText));
      return;
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '', total = 0, done = 0;
    // Keep the List light so a huge folder can't blow up the WebView: only newly
    // analyzed tracks get a (heavy, waveform-bearing) row, capped to the most
    // recent BATCH_ROW_CAP; already-in-library and failed tracks are just counted.
    let added = 0, skipped = 0, failed = 0;
    const shown = [];
    const trimRow = r => { r.remove(); const i = results.findIndex(x => x.row === r); if (i !== -1) results.splice(i, 1); };
    const updateStatus = () => {
      const pct = total ? Math.round(done / total * 100) : 0;
      const extra = [skipped ? `${skipped} skipped` : '', failed ? `${failed} failed` : ''].filter(Boolean).join(' · ');
      batchStatus.textContent = `⟳ ${done} / ${total} · ${pct}%` + (extra ? `  (${extra})` : '');
    };
    while (true){
      const {value, done: eof} = await reader.read();
      if (eof) break;
      buf += dec.decode(value, {stream:true});
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines){
        if (!line.trim()) continue;
        let d; try { d = JSON.parse(line); } catch(e){ continue; }
        if (d.total){ total = d.total; updateStatus(); continue; }
        done = d.progress || done + 1;
        if (d.ok && d.cached){
          skipped++;                              // already analyzed -> don't render
        } else if (d.ok){
          const row = addRow({name: d.filename});
          finishRow(row, d, null);
          shown.push(row);
          if (shown.length > BATCH_ROW_CAP) trimRow(shown.shift());
          added++;
        } else {
          failed++;                               // count failures; keep the List light
        }
        updateStatus();
        if (done % 100 === 0){
          const rows = rowsEl.querySelectorAll('.row').length;
          clientLog(`batch ${done}/${total} · added=${added} skipped=${skipped} failed=${failed} · domRows=${rows} · jsHeap=${jsHeapMB()}MB`);
        }
      }
    }
    clientLog(`batch done: added=${added} skipped=${skipped} failed=${failed} · jsHeap=${jsHeapMB()}MB`);
    const bits = [`✓ ${added} added`];
    if (skipped) bits.push(`${skipped} already in library`);
    if (failed) bits.push(`${failed} failed`);
    if (added > BATCH_ROW_CAP) bits.push(`showing last ${BATCH_ROW_CAP} — see the Library tab`);
    batchStatus.textContent = bits.join(' · ');
    refreshFooter();
  } catch(err){
    batchStatus.textContent = 'error';
    clientLog('batch error: ' + (err && (err.stack || err.message || err)), 'error');
    alert('Batch failed: ' + err.message);
  } finally {
    batchRunning = false;
    batchBtn.classList.remove('active');
    batchBtn.textContent = '⊕ batch folder';
  }
}

/* The Analyzer's two popovers.

   Both hold things that used to sit permanently on screen: the genre-reading
   switches (once pinned to the header, in vocabulary that only made sense if
   you already understood the system) and the specialist tools (once four
   equal-weight buttons in a row with "add music", so nothing signalled which
   was the thing to press first).

   Wired the same way the map's panels are: the button toggles, clicks inside
   do not close it, a click anywhere else does. */
function wirePopover(btnId, panelId){
  const btn = document.getElementById(btnId);
  const panel = document.getElementById(panelId);
  if (!btn || !panel) return;
  btn.addEventListener('click', e => {
    e.stopPropagation();
    // Close any other open Analyzer popover first -- two at once overlap.
    document.querySelectorAll('.an-advwrap .map-panel, .an-morewrap .map-panel')
      .forEach(o => { if (o !== panel) o.hidden = true; });
    panel.hidden = !panel.hidden;
    btn.classList.toggle('on', !panel.hidden);
  });
  panel.addEventListener('click', e => e.stopPropagation());
  document.addEventListener('click', () => {
    panel.hidden = true;
    btn.classList.remove('on');
  });
}
wirePopover('an-adv-btn', 'an-adv-panel');
wirePopover('an-more-btn', 'an-more-panel');

/* Per-track lens overrides, off by default.

   They were on every row permanently, reading "identity: global / segment:
   global" -- two selectors per track whose whole message was "this track
   follows the setting you have not been shown". The capability is real, so it
   is a switch rather than a deletion, and it lives beside the global controls
   it overrides. */
(function () {
  const box = document.getElementById('an-rowlens');
  if (!box) return;
  let on = false;
  try { on = localStorage.getItem('vibeRowLens') === 'on'; } catch (_) { /* private mode */ }
  const apply = () => {
    box.checked = on;
    document.body.classList.toggle('rowlens-on', on);
  };
  apply();
  box.addEventListener('change', () => {
    on = box.checked;
    try { localStorage.setItem('vibeRowLens', on ? 'on' : 'off'); } catch (_) { /* private */ }
    apply();
  });
})();

const gId = document.getElementById('g-identity');
const gSeg = document.getElementById('g-seg');
gId.value = GLOBAL.identity; gSeg.value = GLOBAL.seg;
gId.addEventListener('change', () => {
  GLOBAL.identity = gId.value; setPref('analyzerIdentity', gId.value);
  for (const r of results){ if (r.ok && r.row && r.row._applyModes && !r.row._idOverride) r.row._applyModes(); }
});
gSeg.addEventListener('change', () => {
  GLOBAL.seg = gSeg.value; setPref('analyzerSeg', gSeg.value);
  for (const r of results){ if (r.ok && r.row && r.row._applyModes && !r.row._segOverride) r.row._applyModes(); }
});
// The same two lenses set from the Options tab: the selects are the source of
// truth for the rows, so route the change through them.
PREF_LISTENERS.push((k, v) => {
  if (k === 'analyzerIdentity' && gId.value !== v){ gId.value = v; gId.dispatchEvent(new Event('change')); }
  if (k === 'analyzerSeg' && gSeg.value !== v){ gSeg.value = v; gSeg.dispatchEvent(new Event('change')); }
});


/* render one engine's ranked genre list for the compare panel */
function cmpList(arr){
  if (!arr || !arr.length) return '<span class="cmp-none">—</span>';
  return arr.slice(0, 5).map(s => {
    const col = colorFor(s.style);
    return `<span class="cmp-item"><span class="sw ${styleInfo(s.style).shape}" style="background:${col}"></span>` +
      `<b>${escapeHtml(s.style)}</b> ${(s.score*100).toFixed(0)}%</span>`;
  }).join('');
}
/* top-5 [{style,score}] from the pairs list, scored by fn(pair) */
function topScored(pairs, fn, k){
  return pairs.map(p => ({style:p.style, score:fn(p)}))
              .sort((a,b) => b.score - a.score).slice(0, k || 5);
}
/* build the compare panel into `box`, with a live EffNet↔MAEST weight slider.
   Re-mixing the merge is instant client-side math — MAEST does NOT re-run. */
function renderCompareInto(box, j){
  if (!j.maest_available){
    box.innerHTML = `<div class="cmp-note">MAEST model not installed — showing EffNet only.</div>` +
      `<div class="cmp-col"><div class="cmp-h">EffNet</div>${cmpList(j.effnet)}</div>`;
    return;
  }
  const pairs = j.pairs || [];
  let w = j.weight ?? 0.5;                                    // EffNet share (0..1)
  box.innerHTML =
    `<div class="cmp-grid">` +
      `<div class="cmp-col"><div class="cmp-h">EffNet <span>CNN</span></div>${cmpList(topScored(pairs, p=>p.eff))}</div>` +
      `<div class="cmp-col"><div class="cmp-h">MAEST <span>transformer</span></div>${cmpList(topScored(pairs, p=>p.mae))}</div>` +
      `<div class="cmp-col merged"><div class="cmp-h">Merged <span class="cmp-w"></span></div><div class="cmp-mergedlist"></div></div>` +
    `</div>` +
    `<div class="cmp-slider"><span>EffNet</span>` +
      `<input type="range" class="cmp-range" min="0" max="100" step="5">` +
      `<span>MAEST</span></div>` +
    `<div class="cmp-note"></div>`;
  const range = box.querySelector('.cmp-range');
  const wLab  = box.querySelector('.cmp-w');
  const mList = box.querySelector('.cmp-mergedlist');
  const note  = box.querySelector('.cmp-note');
  const effTop = topScored(pairs, p=>p.eff, 1)[0];
  const maeTop = topScored(pairs, p=>p.mae, 1)[0];
  const agree = effTop && maeTop && effTop.style === maeTop.style;
  function paint(){
    mList.innerHTML = cmpList(topScored(pairs, p => w*p.eff + (1-w)*p.mae, 6));
    wLab.textContent = `${Math.round(w*100)}/${Math.round((1-w)*100)}`;
    note.textContent = agree
      ? `✓ both engines agree on the top genre (${effTop.style})`
      : `⚠ engines disagree — EffNet: ${effTop.style} · MAEST: ${maeTop.style}. The slider blends them.`;
  }
  range.value = Math.round(w*100);
  range.addEventListener('input', () => { w = range.value/100; paint(); });
  paint();
}

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}


/* ---- review reads: audit the library for likely-misread genres ---- */
(() => {
  const btn = document.getElementById('flag-btn');
  const panel = document.getElementById('flag-panel');
  const body = document.getElementById('flag-body');
  const closeB = document.getElementById('flag-close');
  if (!btn || !panel) return;
  closeB && closeB.addEventListener('click', () => panel.classList.remove('open'));

  btn.addEventListener('click', async () => {
    panel.classList.add('open');
    body.innerHTML = `<div class="flag-note">scanning your library…</div>`;
    let list;
    try{ list = await fetch('/audit').then(r => r.json()); }
    catch(_){ body.innerHTML = `<div class="flag-note">audit failed</div>`; return; }
    if (!list.length){ body.innerHTML = `<div class="flag-note">✓ no likely misreads found.</div>`; return; }
    body.innerHTML =
      `<div class="flag-note">${list.length} low-confidence reads whose closest sonic neighbours
        point elsewhere. These are only hints — review and omit the wrong ones.</div>` +
      list.map(f => `
        <div class="flag-row" data-h="${escapeHtml(f.hash)}">
          <div class="flag-main">
            <div class="flag-title">${escapeHtml(f.title)}</div>
            <div class="flag-sub">reads as <b>${escapeHtml(f.style||'?')}</b> ${(f.confidence*100).toFixed(0)}%
              · sounds like <b class="flag-suggest">${escapeHtml(f.suggested_style)}</b>
              (${(f.agreement*100).toFixed(0)}% agree)</div>
          </div>
          <div class="flag-acts">
            <button class="flag-go" title="show on the map">map</button>
            <button class="flag-omit" title="delete this track's analysis">omit</button>
          </div>
        </div>`).join('');
    body.querySelectorAll('.flag-row').forEach(row => {
      const h = row.getAttribute('data-h');
      row.querySelector('.flag-go').onclick = () => {
        panel.classList.remove('open');
        if (window.vibeMapGoto) window.vibeMapGoto(h);
      };
      row.querySelector('.flag-omit').onclick = async () => {
        try{ await fetch(`/forget/${h}`, {method:'POST'}); }catch(_){}
        row.remove();
      };
    });
  });

  if (location.hash === '#review') btn.click();   // deep link: open the audit
})();


/* ===================================================================
   Guide tab: fetch docs/USAGE.md (via /guide) and render it in-app with a
   small dependency-free Markdown converter (headings, lists w/ nesting,
   code, blockquotes, hr, bold, inline code, links).
   =================================================================== */
(() => {
  const body = document.getElementById('guide-body');
  if (!body) return;
  let loaded = false;

  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, (m,c)=>`<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m,t,u)=>{
      const ext = /^https?:/.test(u);
      return `<a href="${esc(u)}"${ext?' target="_blank" rel="noopener"':''}>${t}</a>`;
    });
  const slug = s => s.toLowerCase().replace(/[^\w\s-]/g,'').trim().replace(/\s+/g,'-');

  function mdToHtml(md){
    const lines = md.replace(/\r/g,'').split('\n');
    const out = [];
    const stack = [];                 // open lists: {type, indent}
    let inCode = false, code = [], quote = [];
    const closeLists = (toIndent) => {
      while (stack.length && stack[stack.length-1].indent >= toIndent)
        out.push(stack.pop().type === 'ol' ? '</ol>' : '</ul>');
    };
    const closeAll = () => closeLists(-1);
    const flushQuote = () => { if (quote.length){ out.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`); quote=[]; } };
    for (const raw of lines){
      if (/^\s*```/.test(raw)){
        if (inCode){ out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`); code=[]; inCode=false; }
        else { flushQuote(); closeAll(); inCode=true; }
        continue;
      }
      if (inCode){ code.push(raw); continue; }
      const line = raw.replace(/\s+$/,'');
      let m;
      if ((m = /^>\s?(.*)$/.exec(line))){ closeAll(); quote.push(m[1]); continue; }
      flushQuote();
      if (!line.trim()) continue;                                   // blank
      if ((m = /^(#{1,4})\s+(.*)$/.exec(line))){ closeAll(); const n=m[1].length; out.push(`<h${n} id="${slug(m[2])}">${inline(m[2])}</h${n}>`); continue; }
      if (/^-{3,}$/.test(line.trim())){ closeAll(); out.push('<hr>'); continue; }
      const li = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
      if (li){
        const indent = li[1].length, type = /\d/.test(li[2]) ? 'ol' : 'ul';
        closeLists(indent + 1);
        const top = stack[stack.length-1];
        if (!top || top.indent < indent){ out.push(type==='ol'?'<ol>':'<ul>'); stack.push({type, indent}); }
        out.push(`<li>${inline(li[3])}</li>`);
        continue;
      }
      closeAll(); out.push(`<p>${inline(line.trim())}</p>`);
    }
    flushQuote(); closeAll();
    if (inCode) out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
    return out.join('\n');
  }

  window.vibeLoadGuide = async () => {
    if (loaded) return;
    loaded = true;
    try{
      const md = await fetch('/guide').then(r => r.text());
      body.innerHTML = mdToHtml(md);
    }catch(_){
      body.innerHTML = '<p>Could not load the guide.</p>';
      loaded = false;
    }
  };

  // deep link (#guide) switches the view before this module defines the loader,
  // so kick off the load here too.
  if (location.hash === '#guide') window.vibeLoadGuide();
})();

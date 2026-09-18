/* Genre Map — the 3-D constellation view (scene, camera controls, tree
   view, popups, search, tab switching). Self-contained IIFE.

   LOAD ORDER: load AFTER app.js — uses shared helpers from app.js
   (escapeHtml, colorFor, styleInfo, familyOf, fmtTime) and calls
   window.vibeLoadGuide (defined in app.js). Exposes window.vibeMapGoto,
   which app.js's review panel calls. See index.html. */

/* ===================================================================
   Genre Map -- 3D constellation of the whole scanned library.
   Tracks float in a rotating 3D point-cloud on black; depth drives
   size + brightness. Three layouts (regions / universe / solar). Selecting a point
   opens its popup and pulls up a random one of its closest matches.
   Canvas 2D with a hand-rolled perspective projection (no libraries).
   =================================================================== */
(() => {
  const stage    = document.getElementById('map-stage');
  const canvas   = document.getElementById('map-canvas');
  const legendEl = document.getElementById('map-legend');
  const popEl    = document.getElementById('map-pop');
  const searchEl = document.getElementById('map-search');
  const suggestEl= document.getElementById('map-suggest');
  const countMap = document.getElementById('map-count');
  const resetB   = document.getElementById('map-reset');
  const modeEl   = document.getElementById('map-mode');
  const tabsEl   = document.getElementById('tabs');
  if (!tabsEl || !canvas) return;
  const ctx = canvas.getContext('2d');

  let NODES = [], EDGES = [], FAMS = [], COUNTS = {}, CENTROIDS = {}, STYLE_CENTROIDS = {};
  const byHash = new Map();
  let mapMode = 'regions';                 // 'regions' | 'universe' | 'tree' | 'solar'
  let TREE = null;                         // {nodes, links, rows} for tree mode
  let treeHits = [], hoverGenre = null;    // tree node hit-boxes + hovered node
  let famLabelHits = [];                   // family-label hit-boxes -> click to fly
  let styleLabelHits = [];                 // subgenre-label hit-boxes -> click to fly
  let MAXR = 1;                            // cloud bounding radius (for auto-fit)
  let selHash = null;
  let simCache = [];                       // last popup's /similar result

  let W = 0, H = 0, DPR = 1;
  const rot = { x: -0.15, y: 0.5 };        // orbit angles
  const view = { zoom: 1, panx: 0, pany: 0 };
  const pivot = { x:0, y:0, z:0 };     // orbit centre (eased): see the frame loop
  /* The cloud's centre of mass -- where the tracks actually are, as opposed to
     where the coordinate system happens to start. This is the RESTING pivot:
     with nothing selected the camera looks at it and orbits it. Rebuilt by
     layout(), because it is a property of the arrangement. See gravity(). */
  const BARY = { x:0, y:0, z:0 };
  /* Where YOU have flown the camera, as an offset from that resting pivot, in
     world units. Panning used to be a screen-space slide (view.panx/pany): the
     picture moved but the orbit centre did not, so the next drag swung the view
     straight back around the thing you had just pushed aside -- in Solar, the
     sun. Panning now moves the pivot itself (see panBy), so the camera stays
     where you park it and rotates about that point. Cleared by the framing
     gestures -- fitView, focusFamily/focusStyle, selectNode -- which all mean
     "take me there". */
  const panOff = { x:0, y:0, z:0 };
  let famPivot = null;                 // a clicked genre's centroid to orbit around
  let focusedFam = null;               // a clicked genre -> force ITS subgenre labels on
  let spinSpeed = 0.0006, running = false, rafId = null, filterFam = null;   // 10% of the 0.006 max
  let edgesOn = true, harmonic = false, flaggedOnly = false;

  /* ---------------------------------------------------------------------------
     Facet filters. Genre and "flagged only" used to be two ad-hoc checks inline
     in the draw loop; every new facet would have added another. One object plus
     one predicate keeps them in a single place, so the map, the counter and the
     twinkle highlight all agree on what "showing" means.

     A range facet is [min, max] with null meaning "no bound". The sliders write
     null when parked at their ends, so a track whose BPM was misread as 738
     still appears until you actually narrow the range -- an outlier shouldn't be
     silently hidden by a control you never touched.
  --------------------------------------------------------------------------- */
  // `hidden` is the set of genre names taken off the map by the genre list. A
  // set of exclusions rather than a list of inclusions, so a genre that appears
  // in the library later is visible by default rather than silently absent.
  const FILT_EMPTY = { artist:'', key:'', style:'', tags:[], playlist:null,
                       playable:false, hidden:[], bpm:[null,null], len:[null,null] };
  let FILT = JSON.parse(JSON.stringify(FILT_EMPTY));
  let playlistHashes = null;        // Set of hashes for the chosen playlist, or null
  // Hovered chip -> its tracks twinkle as a preview of what clicking would show.
  // {kind, value} rather than a bare tag: genre and artist chips preview the same
  // way, and they are the ones you can actually see on a library with no tags.
  let HL = null;

  /* The artists credited on a track. The server splits the credit string (see
     vibenative/artists.py); this is the accessor everything else goes through
     so a node from an older payload without the split still behaves. */
  function artistsOf(n){
    if (n.artists && n.artists.length) return n.artists;
    return n.artist ? [n.artist] : [];
  }

  /* The same credits lower-cased, once: the artist filter and the chip hover
     both test every node every frame, and lower-casing three credits per node
     per frame was most of what those frames did. */
  function artistsLower(n){
    return n._al || (n._al = artistsOf(n).map(a => a.toLowerCase()));
  }

  // The one place that answers "does this track match that chip". Both the hover
  // preview and the filter go through it, so the twinkle can never promise a
  // different set than the click delivers -- which was the whole point of having
  // a preview.
  function nodeHas(n, kind, value){
    if (!value) return false;
    if (kind === 'tag')    return (n.tags || []).includes(value);
    // Substring over the SPLIT credits, matching how FILT.artist is applied, so
    // hovering an artist chip previews exactly the tracks clicking it filters to.
    if (kind === 'artist'){
      const v = String(value).toLowerCase();
      return artistsLower(n).some(a => a.includes(v));
    }
    if (kind === 'style')  return n.style === value || (n.styles || []).includes(value);
    return false;
  }
  // Set by the filter panel so anything that changes FILT can refresh the
  // controls and the counter. A no-op until the panel has been wired.
  let syncFilterUI = () => {};

  const filtActive = () =>
    !!(FILT.artist || FILT.key || FILT.style || FILT.tags.length || FILT.playlist
       || FILT.playable || FILT.hidden.length
       || FILT.bpm[0] != null || FILT.bpm[1] != null
       || FILT.len[0] != null || FILT.len[1] != null);

  function inRange(v, [lo, hi]){
    if (v == null) return lo == null && hi == null;   // unknown passes only an unset facet
    if (lo != null && v < lo) return false;
    if (hi != null && v > hi) return false;
    return true;
  }

  // Does this node survive every active filter? The single source of truth.
  function passes(n){
    // Solar shows ONE playlist and nothing else -- a system with strangers
    // drifting through it is not a system. Checked first so it cannot be
    // widened by any other facet.
    if (mapMode === 'solar' && (!SOLAR_SET || !SOLAR_SET.has(n.hash))) return false;
    if (filterFam && n.grp !== filterFam) return false;
    if (flaggedOnly && !n.flag) return false;
    // Match against the SPLIT credits, so filtering to "Chris Lorenzo" finds
    // "AC Slater/Chris Lorenzo/Fly With Us" as well as his solo tracks. Falls
    // back to the raw credit for any node the server did not split.
    if (FILT.artist && !artistsLower(n).some(a => a.includes(FILT.artist))) return false;
    if (FILT.key && n.camelot !== FILT.key) return false;
    // A track counts as its genre even when that genre is only a runner-up read,
    // so filtering to House finds the tracks that are partly House too.
    if (FILT.style && !nodeHas(n, 'style', FILT.style)) return false;
    // tags are AND: picking two means "has both", which is how you narrow down
    if (FILT.tags.length && !FILT.tags.every(t => (n.tags || []).includes(t))) return false;
    if (playlistHashes && !playlistHashes.has(n.hash)) return false;
    // `n.a` is "the server can find this track's audio". A track analysed from a
    // drag-and-drop was never linked to a folder, so it can't be previewed or
    // exported -- a star you can look at but not use. Note this filter, like
    // every other one here, is applied when DRAWING: layout() has already placed
    // every node from the whole library, so hiding these does not move the
    // survivors or change whose neighbours are whose. What you see is the same
    // map with fewer dots on it, not a different map.
    if (FILT.playable && !n.a) return false;
    // Unticked in the genre list. Matched against the keystones, which is the
    // level the list is written at -- so hiding "Dubstep" hides Brostep with it
    // rather than leaving its subgenres behind, and hides the Drumstep that is
    // half Dubstep too.
    if (FILT.hidden.length && genreKeysOf(n).some(g => FILT.hidden.includes(g))) return false;
    if (!inRange(n.bpm, FILT.bpm)) return false;
    if (!inRange(n.duration, FILT.len)) return false;
    return true;
  }
  const tipEl = document.getElementById('map-tip');
  let anim = null;                         // camera tween
  const proj = new Map();                  // hash -> {sx,sy,z,r} for this frame
  /* How far the camera stands off what it is looking at, in world units.

     This was a constant, 2.7, which quietly assumed every layout fits inside a
     ball of that radius. Perspective is CAM/(CAM - z), so a point at z = 2.7 is
     AT the lens: it divides by zero, and everything approaching it swings across
     the screen and then vanishes at the near-plane cull. The old Universe
     already poked past it (its cloud reached about 3.4), and sizing galaxies by
     mass pushed the sky out to about 10 -- so most of it was at or through the
     camera, and orbiting warped it wildly.

     So the camera backs off with the scene instead. At 1.7x the cloud radius the
     near edge magnifies about 2.4x and the far edge about 0.63x -- a fixed 3.9:1
     ratio, so a map looks the same whatever it is measuring, and no layout can
     put itself inside the lens again. The 2.7 floor keeps small scenes on the
     framing they have always had. */
  /* How far in "picking a track" takes you.

     This was the flat number 1.9, which is a zoom level, not a distance -- so it
     only meant "close" for a cloud of the size the map happened to have when it
     was written. On a sky sized by mass, fitting the whole library is around
     0.10, and slamming to 1.9 is twenty times further in than the view you
     started from: you arrive somewhere with nothing around you.

     Six times the fit zoom is about one galaxy filling the frame, which is what
     "look at this track" should mean at any scale -- and on the old cloud it
     lands within a hair of the 1.9 it replaces. */
  const closeZoom = () => clamp(0.95 / (FITR || 1) * 6, 0.3, 6);

  const CAM_STANDOFF = 1.7;
  let CAM = 2.7;                           // camera distance (world units)
  /* Two radii, because they answer different questions.

     MAXR is the real one: the furthest star there is. The camera has to clear
     THAT or the straggler it missed ends up inside the lens.

     FITR is what the view frames, and it deliberately ignores the last few
     percent. A handful of one-track genres sitting out on the rim would
     otherwise set the zoom for the whole library, and the answer to "show me my
     music" would be a small knot in the middle of an empty frame with four dots
     around the edge. Framing the bulk puts the library on screen and lets the
     stragglers fall outside it, which is what they are. */
  let FITR = 1;
  function setSceneRadius(all){
    if (!all.length){ MAXR = FITR = 1; CAM = 2.7; return; }
    all.sort((a, b) => a - b);
    MAXR = Math.max(0.5, all[all.length - 1]);
    // The 90th percentile, not the 97th. Framing at 97 put the edge of the
    // frame where almost nothing is: the outer tenth of a library is a thin
    // scatter, so it set the zoom while the part you can actually see sat in a
    // knot in the middle. At 90 the frame lands on the body of the map and the
    // scatter falls outside it, which is what "fit" should mean.
    FITR = Math.max(0.5, all[Math.floor(all.length * 0.90)] || MAXR);
    CAM = Math.max(2.7, MAXR * CAM_STANDOFF);
  }

  /* -- deterministic RNG so a track's spot is stable across reloads -- */
  function rng(seed){
    let h = 1779033703 ^ seed.length;
    for (let i=0;i<seed.length;i++){
      h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = (h<<13)|(h>>>19);
    }
    let a = h >>> 0;
    return () => {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a>>>15), 1 | a);
      t = (t + Math.imul(t ^ (t>>>7), 61 | t)) ^ t;
      return ((t ^ (t>>>14)) >>> 0) / 4294967296;
    };
  }
  const hueOf = nameHue;               // app.js: shared with the Vibes tab's swatches
  // user-customisable per-family base hue (persisted); falls back to the hash hue
  let FAM_HUE = {};
  try { FAM_HUE = JSON.parse(localStorage.getItem('vibeFamHue') || '{}') || {}; } catch(_){ FAM_HUE = {}; }
  /* Both on-canvas overlays start closed. They are the first thing the map shows
     you, and what you came to the map for is behind them -- a legend and a list
     of key bindings are reference material, useful when you go looking for them
     and in the way when you don't. An explicit "on" is remembered, so opening
     one keeps it open; never having touched it means closed. */
  let legendCollapsed = true;
  try { legendCollapsed = localStorage.getItem('vibeLegend') !== 'on'; } catch(_){ /* private mode */ }

  /* Stars you have looked at, newest first. Kept per browser rather than in the
     library: which tracks you happened to open is a trail through this session's
     thinking, not a fact about the music. Titles are stored alongside the hash so
     the list can name what it is offering before the map has finished loading. */
  const RECENT_MAX = 24;
  let RECENT = [];
  try { RECENT = JSON.parse(localStorage.getItem('vibeRecentStars') || '[]') || []; } catch(_){ RECENT = []; }
  if (!Array.isArray(RECENT)) RECENT = [];
  const saveRecent = () => {
    try { localStorage.setItem('vibeRecentStars', JSON.stringify(RECENT)); } catch(_){ /* private mode */ }
  };
  function pushRecent(n){
    if (!n || !n.hash) return;
    // Re-opening a track moves it to the front rather than adding it twice: the
    // list answers "where have I been", and the same star five times over is a
    // worse answer than the five different ones it pushed out.
    RECENT = [{ hash: n.hash, title: n.title || '', artist: n.artist || '', at: Date.now() },
              ...RECENT.filter(r => r && r.hash !== n.hash)].slice(0, RECENT_MAX);
    saveRecent();
    if (renderRecent) renderRecent();
  }
  let renderRecent = null;          // set when the panel is wired
  const famHue = fam => (FAM_HUE[fam] == null ? hueOf(fam) : FAM_HUE[fam]);
  const famCss = fam => `hsl(${famHue(fam)} 62% 62%)`;

  /* -- user label preferences (persisted). Read live inside frame() so every
     change takes effect on the next rendered frame -- no relayout needed. --
       showFam    show the overarching (family) genre labels
       showSub    show the subgenre labels
       subAlways  show subgenres regardless of zoom/focus (skip the LOD gate)
       onlyFam    '' = every genre; else isolate ONE family (its label + subs)
       colorFam   colour family labels with the genre's own hue vs. plain white
       counts     append the track count to each label
       opacity    0..1 overall label transparency multiplier
       dist       0.5..2.5 family-label distance from the cloud centre
       size       0.6..1.6 label size multiplier
       maxFam     0 = all, else cap the number of genre labels (biggest kept)
       maxSub     0 = all, else cap the number of subgenre labels             */
  const LBL_DEFAULTS = { showFam:true, showSub:true, subAlways:false, onlyFam:'',
    colorFam:false, counts:false, opacity:1, dist:1, size:1, maxFam:0, maxSub:0,
    // hideText   kill every label the canvas draws, in one switch. Distinct
    //            from unticking genre+subgenre: it also drops the leader lines
    //            and the solar ring labels, so the view is purely the stars.
    // twinkle    'off' | 'subtle' | 'flicker'. Subtle is the original gentle
    //            breathing; flicker is a real scintillation, closer to how a
    //            star actually behaves through atmosphere.
    // leaders    draw the line tying a moved label back to its cluster
    // labelStyle 'halo' (stroked outline) or 'pill' (solid rounded plate)
    // shine      how much corona each star gets, 0 = none: the corona is the
    //            part that reads as light being emitted. 0 is exactly the
    //            plain-disc field the map drew before it existed.
    // sizeByRating / useArtistRating / unratedScale -- see ratingBoost()
    hideText:false, twinkle:'subtle', leaders:false, labelStyle:'halo',
    shine:1.4, sizeByRating:false, useArtistRating:true, unratedScale:0.8,
    linkWidth:1 };
  let LBL = Object.assign({}, LBL_DEFAULTS);
  try { LBL = Object.assign(LBL, JSON.parse(localStorage.getItem('vibeMapLabels') || '{}') || {}); } catch(_){}
  const saveLbl = () => { try{ localStorage.setItem('vibeMapLabels', JSON.stringify(LBL)); }catch(_){ /* private */ } };
  // user-customisable per-SUBGENRE base hue (persisted), keyed "fam||style".
  // Overrides the family-derived shade so a single subgenre can be any colour.
  let SUB_HUE = {};
  try { SUB_HUE = JSON.parse(localStorage.getItem('vibeSubHue') || '{}') || {}; } catch(_){ SUB_HUE = {}; }
  function hexToHue(hex){
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return null;
    const r = parseInt(m[1],16)/255, g = parseInt(m[2],16)/255, b = parseInt(m[3],16)/255;
    const mx = Math.max(r,g,b), mn = Math.min(r,g,b), d = mx-mn;
    if (d === 0) return 0;
    let h; if (mx===r) h = ((g-b)/d) % 6; else if (mx===g) h = (b-r)/d + 2; else h = (r-g)/d + 4;
    return ((h*60) % 360 + 360) % 360;
  }
  function hslHex(h, s, l){                          // for seeding the colour picker
    s/=100; l/=100;
    const k = n => (n + h/30) % 12, a = s*Math.min(l, 1-l);
    const f = n => l - a*Math.max(-1, Math.min(k(n)-3, Math.min(9-k(n), 1)));
    const to = x => Math.round(x*255).toString(16).padStart(2,'0');
    return `#${to(f(0))}${to(f(8))}${to(f(4))}`;
  }
  // deterministic 0..1 hash of a string
  function hash01(s){ let h = 0; for (let i=0;i<s.length;i++) h = (h*31 + s.charCodeAt(i)) | 0;
    return (((h % 4096) + 4096) % 4096) / 4096; }
  function hexHsl(hex){
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!m) return null;
    const r = parseInt(m[1],16)/255, g = parseInt(m[2],16)/255, b = parseInt(m[3],16)/255;
    const mx = Math.max(r,g,b), mn = Math.min(r,g,b), d = mx-mn, l = (mx+mn)/2;
    let h = 0;
    if (d !== 0){
      if (mx===r) h = ((g-b)/d) % 6; else if (mx===g) h = (b-r)/d + 2; else h = (r-g)/d + 4;
      h = ((h*60) % 360 + 360) % 360;
    }
    const sat = d === 0 ? 0 : d / (1 - Math.abs(2*l - 1));
    return { h, s: sat*100, l: l*100 };
  }

  // Keystone colour by style name, harvested from the server's own paint. The
  // server owns the palette -- the solved default, the chosen preset, and any
  // colour set per genre all resolve there -- so the map reads its colours out
  // rather than deriving a second, disagreeing set from a static family table.
  let KCOL = {};

  // A subgenre's colour = its keystone's hue nudged a little (so it still reads
  // as the same genre) plus a small saturation/lightness wobble -- subgenres come
  // out distinct but kin, so a cluster shows its internal groupings even from
  // afar. Returns {h, s, dl} (hue, saturation, lightness delta from the base 58).
  function styleShade(fam, style){
    const ov = style ? SUB_HUE[`${fam}||${style}`] : null;   // per-subgenre override
    const paint = style ? hexHsl(KCOL[style]) : null;
    const base = paint ? paint.h : famHue(fam);
    if (!style || style === fam)
      return { h: (ov == null ? base : ov), s: paint ? paint.s : 64, dl: paint ? paint.l - 58 : 0 };
    const r = hash01(style + '|' + fam);
    // A narrower nudge when the hue came from the palette: +/-36 was safe around
    // a family hue with nothing next to it, but the palette packs keystones close
    // enough that that much wander would push a subgenre into its neighbour's
    // colour -- the one thing the palette is solved to prevent.
    const spread = paint ? 12 : 36;
    return {
      h: ov != null ? ov : ((base + (r*2 - 1)*spread) % 360 + 360) % 360,
      // Wobble *around* the palette's saturation rather than across a fixed
      // range, or Pastel and Neon would come out the same on the map.
      s: paint ? Math.max(0, Math.min(100, paint.s + (hash01('s' + style)*2 - 1) * 12))
               : 48 + Math.floor(hash01('s' + style) * 38),
      dl: (paint ? paint.l - 58 : 0) + (hash01('l' + style)*2 - 1) * (paint ? 7 : 15),
    };
  }
  // blend shade b into a by t (0..1); hue interpolated along the short arc so a
  // mixed track lands *between* its two genres' colours ("colour matching").
  function mixShade(a, b, t){
    const d = ((b.h - a.h) % 360 + 540) % 360 - 180;
    return { h: ((a.h + d*t) % 360 + 360) % 360, s: a.s + (b.s-a.s)*t, dl: a.dl + (b.dl-a.dl)*t };
  }
  const durfmt = s => { if (s==null) return '--'; s=Math.round(s);
    return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); };
  // Written in whichever notation the app is set to read in; app.js owns that
  // preference so the map, the rows and the exported list can never disagree.
  const keyfmt = n => keyText(n) || '--';

  /* ---- harmonic mixing (Camelot wheel + BPM tolerance) ------------- */
  const camelot = c => { const m = /^(\d{1,2})([AB])$/.exec((c||'').trim().toUpperCase());
    return m ? { n:+m[1], l:m[2] } : null; };
  function keyCompatible(a, b){
    const A = camelot(a), B = camelot(b);
    if (!A || !B) return false;
    if (A.n === B.n) return true;                       // same, or relative maj/min
    const d = Math.abs(A.n - B.n);
    return A.l === B.l && (d === 1 || d === 11);        // ±1 around the 12-hour wheel
  }
  function bpmCompatible(a, b){
    if (a == null || b == null) return true;            // unknown -> don't exclude
    const r = Math.max(a,b) / Math.min(a,b);
    const near = x => Math.abs(x - 1) <= 0.06;          // ±6%
    return near(r) || near(r/2) || near(r*2);           // same, or half / double-time
  }
  const clamp = (v,a,b) => Math.max(a, Math.min(b, v));
  const pctl = (arr,p) => { if(!arr.length) return 1;
    const s=arr.slice().sort((x,y)=>x-y);
    return s[Math.min(s.length-1, Math.floor(p*(s.length-1)))] || 1; };

  /* ---- ratings: how big a star gets -------------------------------
     Track ratings and artist ratings are fetched once per map load (see
     loadOverlays) and answer different questions -- "is this record good" vs
     "is this producer worth my time" -- so a track can be sized by either. */
  let TRACK_RATINGS = {};              // hash -> {stars, grade, note}
  let ARTIST_RATINGS = {};             // normalised artist key -> {stars, ...}
  /* Bumped whenever either table changes. starsFor() runs for every node every
     frame; the lookups behind it -- a regex split per credit -- are resolved
     once per node per revision and remembered on the node. */
  let RATINGS_REV = 0;
  const ratingsChanged = () => { RATINGS_REV++; };

  /* Must match ratings.artist_key() on the server: casefolded, whitespace
     collapsed. If these two ever disagree the map silently sizes every star as
     unrated, which looks like the feature is off rather than broken. */
  const artistKey = name => String(name || '').split(/\s+/).filter(Boolean).join(' ').toLowerCase();

  function starsFor(n){
    if (n._starsRev !== RATINGS_REV){
      n._starsT = (TRACK_RATINGS[n.hash] || {}).stars || 0;
      // The popup rates the split artists (artistsOf), never the raw credit, so
      // a co-credited track has to look each of them up: rating "Chris Lorenzo"
      // 5* must grow every "AC Slater/Chris Lorenzo" star too. The raw credit
      // is still tried for ratings made before credits were split.
      let a = (ARTIST_RATINGS[artistKey(n.artist)] || {}).stars || 0;
      for (const name of artistsOf(n)){
        a = Math.max(a, (ARTIST_RATINGS[artistKey(name)] || {}).stars || 0);
      }
      n._starsA = a;
      n._starsRev = RATINGS_REV;
    }
    if (!LBL.useArtistRating) return n._starsT;
    // The better of the two, not the average: a 5-star track by an unrated
    // artist is still a 5-star track, and averaging would bury it.
    return Math.max(n._starsT, n._starsA);
  }

  /* Radius multiplier from the rating. Unrated stays visible rather than
     vanishing -- an unrated track is unjudged, not bad, and a map that hides
     everything you haven't got to yet is useless for finding what to play. */
  function ratingBoost(n){
    if (!LBL.sizeByRating) return 1;
    const st = starsFor(n);
    if (!st) return LBL.unratedScale;
    return 0.78 + st * 0.20;                       // 1★ ≈ 0.98 … 5★ ≈ 1.78
  }

  /* ---- star sprites -----------------------------------------------
     A lit sphere is a radial gradient: white-hot core, the genre's colour
     through the body, corona falling to nothing. Building one per node per
     frame would mean thousands of createRadialGradient calls at 60fps, so
     sprites are rendered once into offscreen canvases and blitted.

     The cache key quantises the colour (hue to 6°, saturation and lightness to
     coarse steps) which caps it at a few hundred sprites for any library while
     staying visually indistinguishable from exact colours. */
  /* Colour components, coerced to something CSS will always accept.

     A NaN hue or lightness renders as the string "hsla(NaN 90% NaN% / 1)", and
     addColorStop does not ignore that -- it throws. Thrown inside the rAF
     callback it takes the whole render loop down and leaves nothing but the
     black background fill, which is indistinguishable from "the map is empty".
     No single track's shade is worth that, so every component is clamped to a
     usable number on the way in. */
  const numOr = (v, fallback) => (Number.isFinite(v) ? v : fallback);
  const hueOk = v => ((numOr(v, 0) % 360) + 360) % 360;
  const pctOk = (v, fallback) => clamp(numOr(v, fallback), 0, 100);

  let _shadeWarned = false;
  function warnShade(where, n){
    if (_shadeWarned) return;                 // once per session, not per frame
    _shadeWarned = true;
    console.warn('map: non-finite colour for a track, using a fallback shade', {
      where, hash: n && n.hash, title: n && n.title, fam: n && n.fam,
      style: n && n.style, hue: n && n.hue, sat: n && n.sat, dl: n && n.dl,
    });
  }

  const STAR_SPRITES = new Map();
  // 64, not 32: the context is scaled by devicePixelRatio, so a sprite drawn at
  // its nominal size is already magnified 2x on a HiDPI display before zoom is
  // considered. The colour key is quantised coarsely enough that the cache
  // stays in the low hundreds of entries even at 128x128 each.
  const SPRITE_R = 64;                              // sprite half-size in px
  const GLOW_SCALE = 2.6;                           // corona reach vs. core radius

  /* Where the light comes from, as a fraction of the body's radius.
     A sphere only reads as a sphere when it is lit from somewhere: a gradient
     centred on the middle is a fuzzy dot no matter how much resolution it has.
     Offsetting the highlight up and to the left gives the shading a direction,
     and keeping that direction the same for every star makes the field look
     like one scene rather than a thousand unrelated blobs. */
  const LIGHT_X = -0.38, LIGHT_Y = -0.38;
  // How much of the corona is added per star. Deliberately small: the corona is
  // drawn with 'lighter', which ACCUMULATES, and a dense cluster stacks hundreds
  // of them on the same pixels. At full strength that saturates to a solid white
  // blob and the cluster stops showing any structure at all -- which is exactly
  // what a first pass at this did.
  const GLOW_ALPHA = 0.16;

  /* The corona: the part that reads as light being EMITTED rather than a dot
     printed on black. Additive at low alpha (see GLOW_ALPHA), and skipped on
     the smallest, faintest stars: there it is under a pixel of visible
     contribution but still a full blit, and on a 3000-track map that is
     thousands of wasted draws every frame.

     Assumes the caller has already put the context into additive mode. It used
     to set 'lighter' and put it back on every single call, and that is what
     made the glow expensive rather than the light itself: changing the
     composite operation ends the current batch, so a 3,000-star frame paid
     6,000 forced flushes on top of its 6,000 blits. The blits are the work; the
     flushes were pure tax. The alpha each star needs still differs (depth,
     twinkle, harmonic dimming), so it is passed in rather than read back off
     the context; the corona is a fraction OF it, so a dim star glows dimly. */
  function drawCorona(p, n, strength, alpha){
    if (!(strength > 0) || p.r <= 1.8 || alpha <= 0.12) return;
    const gr = p.r * GLOW_SCALE;
    ctx.globalAlpha = alpha * GLOW_ALPHA * strength;
    ctx.drawImage(glowSprite(n), p.sx - gr, p.sy - gr, gr * 2, gr * 2);
  }

  /* Colour stops for a lit sphere -- the Solar view's sun -- from the
     highlight out to the dark limb.

     The silhouette stop is FULLY OPAQUE. That is the whole difference between
     an orb and a blur: the previous body faded from alpha 0.95 to 0 across the
     outer 38% of its radius, so its edge was soft by construction and no amount
     of sprite resolution could sharpen it. Here the edge is defined by the arc
     path instead, which the canvas antialiases at exactly the drawn size --
     crisp at 2px and at 200. */
  function sphereStops(grd, h, sa, li){
    grd.addColorStop(0.00, `hsla(${h} ${Math.max(0, sa - 30)}% ${clamp(li + 46, 62, 99)}% / 1)`);
    grd.addColorStop(0.14, `hsla(${h} ${Math.min(100, sa + 6)}% ${clamp(li + 28, 46, 92)}% / 1)`);
    grd.addColorStop(0.42, `hsla(${h} ${Math.min(100, sa + 14)}% ${clamp(li + 6, 26, 78)}% / 1)`);
    grd.addColorStop(0.74, `hsla(${h} ${sa}% ${clamp(li - 10, 12, 64)}% / 1)`);
    // A touch of light back on the dark limb -- bounce light. Without it the
    // terminator runs to black and the ball reads as a crescent.
    grd.addColorStop(0.93, `hsla(${h} ${sa}% ${clamp(li - 20, 7, 52)}% / 1)`);
    grd.addColorStop(1.00, `hsla(${h} ${Math.min(100, sa + 8)}% ${clamp(li - 8, 10, 60)}% / 1)`);
  }

  /* One lit sphere, drawn at its exact on-screen size. */
  function drawSphere(cx, cy, r, h, sa, li){
    const g = ctx.createRadialGradient(
      cx + r * LIGHT_X, cy + r * LIGHT_Y, r * 0.03,   // highlight
      cx, cy, r);                                      // body
    sphereStops(g, h, sa, li);
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, 6.2832);
    ctx.fillStyle = g;
    ctx.fill();
  }

  // Canonical body lightness a sprite is baked at. Per-star brightness is
  // applied as alpha at draw time, so this is only the midpoint it varies around.
  const SPRITE_LIGHT = 56;

  /* The corona sprite a star draws with, resolved once and kept on the node.

     starSprite() is cheap but not free: it rounds three numbers, builds a key
     string and hits a Map. Calling it per star per frame on a 3,000-track
     library is 3,000 key strings every frame for no gain, since n.hue / n.sat
     / n.dl do not change between layouts. Invalidated by setShade(), the one
     place those three are assigned. */
  function glowSprite(n){
    return n._spGlow || (n._spGlow = starSprite(n.hue, n.sat || 64, n.dl));
  }

  /* Nebula gas: one very soft, very faint blob per system.

     Stars alone draw a galaxy as a swarm of points with nothing between them,
     and the thing every real photograph of one has that ours did not is the
     stuff in between -- lit gas, dim and enormous and the same colour as what
     lit it. It is drawn additively and kept deliberately weak, because it is
     accumulating: a galaxy is dozens of these overlapping, and anything you can
     see clearly on its own blows out to a white cloud when they stack.

     Softer than the star corona, and with no core: gas has no surface. */
  const NEBULA_R = 96;
  const NEBULA_SPRITES = new Map();
  function nebulaSprite(hue, sat){
    const h = Math.round(hueOk(hue) / 10) * 10;
    const sa = Math.round(pctOk(sat, 64) / 12) * 12;
    const key = h + '|' + sa;
    let cv = NEBULA_SPRITES.get(key);
    if (cv) return cv;
    if (NEBULA_SPRITES.size > 200) NEBULA_SPRITES.clear();
    cv = document.createElement('canvas');
    cv.width = cv.height = NEBULA_R * 2;
    const g = cv.getContext('2d');
    const grd = g.createRadialGradient(NEBULA_R, NEBULA_R, 0, NEBULA_R, NEBULA_R, NEBULA_R);
    grd.addColorStop(0.00, `hsla(${h} ${sa}% 66% / 0.62)`);
    grd.addColorStop(0.18, `hsla(${h} ${sa}% 58% / 0.34)`);
    grd.addColorStop(0.48, `hsla(${h} ${sa}% 50% / 0.13)`);
    grd.addColorStop(0.78, `hsla(${h} ${sa}% 44% / 0.03)`);
    grd.addColorStop(1.00, `hsla(${h} ${sa}% 40% / 0)`);
    g.fillStyle = grd;
    g.fillRect(0, 0, NEBULA_R * 2, NEBULA_R * 2);
    NEBULA_SPRITES.set(key, cv);
    return cv;
  }

  /* The halo, drawn additively at low alpha so that a handful of nearby stars
     genuinely brighten each other -- the part that reads as light being
     emitted -- without a crowd blowing out to white. */
  function starSprite(hue, sat, dl){
    const h = Math.round(hueOk(hue) / 6) * 6;
    const sa = Math.round(pctOk(sat, 64) / 8) * 8;
    // dl is the subgenre's lightness offset -- stable for the whole layout, so
    // it is safe in the key. Depth and twinkle deliberately are NOT.
    const li = Math.round(clamp(SPRITE_LIGHT + (Number.isFinite(dl) ? dl : 0), 20, 84) / 6) * 6;
    const key = h + '|' + sa + '|' + li;
    let cv = STAR_SPRITES.get(key);
    if (cv) return cv;
    // Backstop. The key is bounded by the palette and the subgenre list, so this
    // should never fire -- but an unbounded canvas cache is how the renderer
    // froze once already, and a cleared cache costs a few milliseconds to refill.
    if (STAR_SPRITES.size > 400) STAR_SPRITES.clear();
    cv = document.createElement('canvas');
    cv.width = cv.height = SPRITE_R * 2;
    const g = cv.getContext('2d');
    const grd = g.createRadialGradient(SPRITE_R, SPRITE_R, 0, SPRITE_R, SPRITE_R, SPRITE_R);
    grd.addColorStop(0.00, `hsla(${h} ${Math.min(100, sa + 14)}% ${clamp(li + 20, 34, 90)}% / 0.85)`);
    grd.addColorStop(0.35, `hsla(${h} ${sa}% ${li}% / 0.34)`);
    grd.addColorStop(1.00, `hsla(${h} ${sa}% ${li}% / 0)`);
    g.fillStyle = grd;
    g.fillRect(0, 0, SPRITE_R * 2, SPRITE_R * 2);
    STAR_SPRITES.set(key, cv);
    return cv;
  }

  /* ---- Solar view: one playlist as a system ------------------------
     The sun is the playlist; every track is a body orbiting it, and the ring a
     track lands in is what SOLAR.by decides. Inner orbits run faster than
     outer ones, which is both true of real systems and useful here: it keeps
     the dense inner rings legible instead of rotating as a solid disc. */
  let SOLAR = { playlist: '', by: 'similarity' };
  try { SOLAR = Object.assign(SOLAR, JSON.parse(localStorage.getItem('vibeSolar') || '{}') || {}); } catch(_){}
  const saveSolar = () => { try{ localStorage.setItem('vibeSolar', JSON.stringify(SOLAR)); }catch(_){} };
  let SOLAR_SET = null;                 // Set of hashes in the chosen playlist
  let SOLAR_RINGS = [];                 // [{label, r, n}] for the ring legend
  let SOLAR_NAME = '';                  // the sun's name

  function solarLayout(){
    // Cleared FIRST, not last: both early returns below (no playlist chosen, no
    // ring survived) used to bail before the reset at the end, leaving the
    // PREVIOUS mode's centroids in place -- vibe-keyed centroids under
    // genre-keyed FAMS, or a full regions label set over an empty system.
    CENTROIDS = {}; STYLE_CENTROIDS = {};
    SOLAR_RINGS = [];
    const members = SOLAR_SET ? NODES.filter(n => SOLAR_SET.has(n.hash)) : [];
    if (!members.length) return;

    // --- decide each member's ring ---------------------------------------
    let bands = [];                     // [{label, members:[]}] innermost first
    if (SOLAR.by === 'bpm'){
      // Quantiles, not fixed BPM windows: a playlist that lives between 122 and
      // 128 should still spread across its rings rather than collapse into one.
      const vals = members.map(n => n.bpm || 0).filter(v => v > 0).sort((a,b)=>a-b);
      const cuts = [0.2,0.4,0.6,0.8].map(q => vals.length ? vals[Math.floor(q*(vals.length-1))] : 0);
      const labels = ['slowest','slower','middle','faster','fastest'];
      bands = labels.map(l => ({ label:l, members:[] }));
      for (const n of members){
        const v = n.bpm || 0;
        let i = 0; while (i < cuts.length && v > cuts[i]) i++;
        bands[i].members.push(n);
      }
      bands.forEach((b,i) => {
        const bs = b.members.map(n=>n.bpm||0).filter(Boolean);
        if (bs.length) b.label = `${Math.round(Math.min(...bs))}–${Math.round(Math.max(...bs))} bpm`;
        else b.label = labels[i];
      });
    } else if (SOLAR.by === 'genre'){
      const by = {};
      for (const n of members){ const k = n.style || n.fam || 'Other'; (by[k] ||= []).push(n); }
      bands = Object.keys(by).sort((a,b)=>by[b].length-by[a].length)
                    .map(k => ({ label:k, members:by[k] }));
    } else {
      // similarity: distance from the playlist's own centre of mass. The tracks
      // that ARE this playlist hug the sun; the ones that only just belong orbit
      // far out -- which makes "what doesn't fit here" visible at a glance.
      const dim = (members.find(n=>n.e)||{}).e?.length || 0;
      const cen = new Array(dim).fill(0);
      let cn = 0;
      for (const n of members) if (n.e){ for (let j=0;j<dim;j++) cen[j] += n.e[j]; cn++; }
      if (cn) for (let j=0;j<dim;j++) cen[j] /= cn;
      const cmag = Math.hypot(...cen) || 1;
      const scored = members.map(n => {
        if (!n.e) return { n, sim: 0 };
        let dot = 0; for (let j=0;j<dim;j++) dot += n.e[j]*cen[j];
        return { n, sim: dot / ((Math.hypot(...n.e) || 1) * cmag) };
      }).sort((a,b) => b.sim - a.sim);
      const labels = ['the core','close fit','fits','loose fit','outliers'];
      bands = labels.map(l => ({ label:l, members:[] }));
      scored.forEach((sc,i) => {
        bands[Math.min(4, Math.floor(i / (scored.length / 5)))].members.push(sc.n);
      });
    }
    bands = bands.filter(b => b.members.length);
    if (!bands.length) return;

    // --- place each body on its ring --------------------------------------
    // "AU" here is just an even step outward; using the real inverse-square
    // spacing would bunch every outer ring against the frame edge.
    const AU = 1.0 / Math.max(1, bands.length);
    bands.forEach((b, bi) => {
      const r = 0.42 + (bi + 1) * AU * 1.55;
      SOLAR_RINGS.push({ label: b.label, r, n: b.members.length });
      b.members.forEach((n, i) => {
        const rr = rng(n.hash);
        // Evenly spaced by index so a crowded ring reads as a belt rather than
        // a random clump, with a small deterministic jitter so it is not a
        // perfect string of beads.
        const a0 = (i / b.members.length) * 6.2832 + (rr() - 0.5) * 0.35;
        n.orb = {
          r: r + (rr() - 0.5) * 0.055,
          a0,
          // Slight inclination per body so the system has depth instead of
          // being a flat disc seen edge-on when you orbit the camera.
          incl: (rr() - 0.5) * 0.30,
          // Inner orbits sweep faster (Keplerian in spirit, not to scale).
          speed: 0.30 / Math.pow(r, 1.5),
        };
        solarPlace(n, 0);
      });
    });
    // The sun is at the origin and every body orbits it, so the centre of mass
    // is the origin by construction -- there is nothing to search for here.
    BARY.x = BARY.y = BARY.z = 0;
    setSceneRadius(members.map(n => Math.hypot(n.x3, n.y3, n.z3)));
  }

  /* One body's position at time t. Split out because frame() re-runs it every
     tick to animate the orbit, while solarLayout() calls it once to seed. */
  function solarPlace(n, t){
    const o = n.orb; if (!o) return;
    const a = o.a0 + t * o.speed;
    n.x3 = Math.cos(a) * o.r;
    n.z3 = Math.sin(a) * o.r;
    n.y3 = Math.sin(a) * o.r * o.incl;
    n.ph = o.a0;
  }

  /* ---- Universe view: what counts as a galaxy ----------------------
     UNI.by is 'vibe' or 'arch'. Vibe membership is fetched once per map load
     (see loadOverlays) because it lives in the database, not on the node. */
  const UNI_FIELD = '\u2014 not in a vibe \u2014';        // where unassigned tracks drift
  /* `by`   what a galaxy is: 'arch' (keystone genre), 'fam' (family), 'vibe'.
     `sep`  how big the sky is -- see the relaxation, where it sets the balance.
     `grav` how hard related galaxies pull on each other; 0 is a plain even shell.
     `v`    which meaning those numbers have.

     `sep` used to scale the starting positions and nothing else, so a stored 1
     from that version does not mean what a 1 means now. Rather than silently
     reinterpreting it, a settings blob from before the change is replaced with
     the current defaults -- the alternative is a saved preference that quietly
     becomes a different preference under the user. */
  const UNI_V = 2;
  let UNI = { by: 'arch', sep: 1.6, grav: 1, v: UNI_V };
  try {
    const saved = JSON.parse(localStorage.getItem('vibeUniverse') || '{}') || {};
    if (saved.v === UNI_V) UNI = Object.assign(UNI, saved);
    else if (saved.by) UNI.by = saved.by;      // that one still means what it did
  } catch(_){}
  const saveUni = () => {
    UNI.v = UNI_V;
    try{ localStorage.setItem('vibeUniverse', JSON.stringify(UNI)); }catch(_){}
  };
  // The settled galaxies of the current Universe layout, by name. Kept so the
  // label layer and the click-to-fly targets can use where gravity actually put
  // them rather than recomputing the relaxation.
  let GALAXIES = {};
  let lastGt = 0;                     // the orbit clock, as of the last tick
  let PLAYLISTS = [];                 // [{id, name}] saved playlists, for Solar
  let VIBES = [];                     // [{id, name, hashes}] from /vibes/membership
  let VIBE_OF = new Map();            // hash -> vibe name (first vibe wins)
  /* What kind of thing n.grp names: 'fam' (a genre family), 'genre' (a
     keystone), or 'vibe'. Set beside n.grp in layout(), so the legend, the
     count line and the subgenre layer read one value instead of each
     re-deriving it from the mode and the Universe's clustering. */
  let GROUP_KIND = 'fam';
  const groupNoun = () => (GROUP_KIND === 'vibe' ? 'vibe' : 'genre');

  /* The genres a track is filed under for the genre list: its keystones, which
     is the tier that answers "what kind of track is this" without splitting
     House into nine entries you would have to untick one at a time.

     The keystones themselves, not `kkey`: a fusion's key is the joined
     "Drum n Bass + Dubstep", which would give the list a row of its own for
     every blend and leave the track on the map after you unticked Dubstep. A
     fusion is filed under both of its parents instead, and hidden with either.
     Always present: the server files a track the taxonomy cannot place under
     its own style, so there is nothing to fall back to here. */
  function genreKeysOf(n){ return n.keystones; }

  /* One tier below whatever a galaxy is.

     A galaxy is a genre, but a genre is not a smooth thing: House is Progressive
     House and Bassline and Electro House and Tech House, and those are real
     divisions with their own sound. Drawing them as one even disc says they are
     interchangeable, which is the opposite of what the rest of the app spends
     its time telling you. So each one gets its own system inside the galaxy --
     a cluster of its own, in its own orbit around the middle.

     Always the next tier down, so the nesting holds whichever way you slice the
     sky: family galaxies are made of genres, genre galaxies are made of
     subgenres. */
  function systemKeyOf(n){
    if (UNI.by === 'fam' || UNI.by === 'vibe') return n.kkey;
    return n.style || n.kkey;          // a track with no read at all sits with its keystone
  }

  /* Which galaxy a track belongs to.

     A track can sit in several vibes at once, but it can only be in one place
     on screen, so the FIRST vibe by name owns it. Deterministic, and stated
     rather than silently picking whichever the query returned first. */
  function uniGroupOf(n){
    if (UNI.by === 'vibe') return VIBE_OF.get(n.hash) || UNI_FIELD;
    // 'genre' is the default: one galaxy per keystone, which is the level at
    // which "Dubstep" and "Drum n Bass" are different places. Grouping by family
    // put both inside one Bass galaxy -- which is why that galaxy was a single
    // dense blob with the interesting structure buried inside it.
    if (UNI.by === 'fam') return n.fam;
    return n.kkey;
  }

  /* ---- galaxies -----------------------------------------------------

     Every galaxy used to be the same size, in the same orientation, pinned to a
     point on one sphere. So the biggest genre in the library and a genre with
     four tracks in it drew the same object, and the sky was a ring of equal
     blobs -- which is why the dense ones read as fog and the whole thing looked
     like a diagram rather than a sky.

     A galaxy now has three things the old anchor did not:

       MASS. Its radius grows as the square root of its track count, because a
       galaxy is a disc: doubling the area doubles the room, and sqrt is what
       keeps a 1,400-track genre from swallowing the sky while a 5-track one
       stays a legible speck rather than a single point.

       ORIENTATION. A random-but-stable 3-D rotation, seeded from the name. Real
       galaxies are not co-planar, and a sky of discs all facing the camera is
       the single strongest tell that a thing was drawn rather than observed.

       GRAVITY. Where it sits is settled by a relaxation, not assigned. Galaxies
       repel by mass, so the big ones claim room, and attract along the
       similarity edges the library already carries -- so genres whose tracks are
       actually each other's nearest neighbours drift together. That is where
       the swirl comes from: Drumstep's tracks neighbour both Dubstep and Drum n
       Bass, so its galaxy is pulled between the two and all three end up in one
       another's tide. Nothing about that is hardcoded -- take the bridge tracks
       out of the library and the pull goes with them. */

  // Affinity between galaxies: how many similarity edges cross between them,
  // normalised by size so a big genre is not simply attractive to everything.
  function galaxyBonds(groupOf){
    const bonds = new Map();               // "a\u0000b" -> edge count
    for (const ed of EDGES){
      const a = byHash.get(ed.a), b = byHash.get(ed.b);
      if (!a || !b) continue;
      const ga = groupOf(a), gb = groupOf(b);
      if (ga === gb) continue;
      const k = ga < gb ? ga + '\u0000' + gb : gb + '\u0000' + ga;
      bonds.set(k, (bonds.get(k) || 0) + (ed.sim || 0.75));
    }
    return bonds;
  }

  // A stable rotation matrix for a galaxy, from its name. Same name, same tilt,
  // every session -- a sky that re-shuffles itself on reload is not a place.
  function galaxyBasis(name){
    const r = rng('gx|' + name);
    // Two random orthonormal axes in the disc plane, plus their normal.
    const a = r() * 6.2832, b = Math.acos(2 * r() - 1), c = r() * 6.2832;
    const ca = Math.cos(a), sa = Math.sin(a);
    const cb = Math.cos(b), sb = Math.sin(b);
    const cc = Math.cos(c), sc = Math.sin(c);
    // Z-Y-Z Euler rotation, written out: three cheap trig calls beat a matrix
    // library for the twenty or so galaxies this ever runs on.
    return {
      u: [ca*cb*cc - sa*sc,  sa*cb*cc + ca*sc,  -sb*cc],
      v: [-ca*cb*sc - sa*cc, -sa*cb*sc + ca*cc,  sb*sc],
      w: [ca*sb,             sa*sb,              cb],
    };
  }

  /* Settle the galaxies by force. Repulsion by mass keeps them out of each
     other; the bonds pull related ones together; a weak pull to the origin stops
     the whole sky drifting apart. Runs once per layout on a handful of bodies,
     so it is a few thousand operations -- nothing that touches a frame. */
  function uniAnchors(){
    const count = {};
    for (const n of NODES){ const g = uniGroupOf(n); count[g] = (count[g]||0)+1; }
    const names = Object.keys(count).sort((a,b)=>count[b]-count[a]);
    if (!names.length) return {};

    const total = NODES.length || 1;
    const G = {};
    names.forEach((g, i) => {
      const r = rng('pos|' + g);
      // Seeded on a Fibonacci sphere -- an even, deterministic starting point,
      // so the relaxation converges to the same sky every time rather than
      // wherever this run's random numbers happened to drop it.
      const k = i + 0.5;
      const phi = Math.acos(1 - 2 * k / names.length);
      const th = Math.PI * (1 + Math.sqrt(5)) * k;
      const seed = 1.6 + 1.4 * UNI.sep;
      G[g] = {
        name: g, n: count[g],
        // sqrt of the share of the library, floored so a tiny genre is still an
        // object with an inside rather than a dot. Deliberately NOT scaled by
        // the separation control: that sets how much space is BETWEEN galaxies,
        // and scaling the galaxies with it would just be zoom.
        radius: clamp(1.5 * Math.sqrt(count[g] / total), 0.10, 0.95),
        mass: Math.sqrt(count[g]),
        x: seed * Math.cos(th) * Math.sin(phi) + (r() - 0.5) * 0.2,
        y: seed * Math.sin(th) * Math.sin(phi) + (r() - 0.5) * 0.2,
        z: seed * Math.cos(phi) + (r() - 0.5) * 0.2,
        basis: galaxyBasis(g),
        // Its own rate and direction, stable from the name. A sky where every
        // galaxy turns the same way at the same speed reads as one mechanism
        // with things glued to it.
        spin: (r() < 0.5 ? -1 : 1) * (0.055 + r() * 0.075),
      };
    });

    const bonds = galaxyBonds(uniGroupOf);
    // Normalise so the strongest pair in the library pulls at 1. An absolute
    // edge count would mean a big library collapses and a small one never moves.
    let maxBond = 0;
    for (const v of bonds.values()) if (v > maxBond) maxBond = v;
    const pull = [];
    for (const [k, v] of bonds){
      const [a, b] = k.split('\u0000');
      if (G[a] && G[b]) pull.push([G[a], G[b], v / (maxBond || 1)]);
    }

    const STEPS = 260;
    const grav = clamp(UNI.grav, 0, 2);
    /* What holds the sky together, and therefore how big it is.

       Repulsion pushes outward and this pulls back; the sky settles where they
       balance, at a radius that goes as the square root of their ratio. So the
       separation control has to land HERE. Scaling the seed positions and the
       galaxy radii by it (which is all it used to do) changed where the
       relaxation started and how big each galaxy was, but not where it finished
       -- the sky came out the same size at every setting, which is why turning
       it up did nothing you could see. */
    /* How much clear space galaxies insist on, as a multiple of them touching.

       This is where the separation control lands, and it is the only place it
       can honestly land: the sky settles where the galaxies stop overlapping, so
       the only way to make it emptier is to widen what counts as overlapping.
       At 1 they sit two radii apart -- a sky of touching discs; by 3 there is
       more space than galaxy, which is what a universe actually looks like. */
    const GAP = 1.15 + 0.85 * UNI.sep;
    // Weak: it only has to stop the pack drifting apart, and anything stronger
    // fights the spacing above and pulls the sky back into a lump.
    const hold = 0.004;
    for (let step = 0; step < STEPS; step++){
      const cool = 1 - step / STEPS;              // anneal: big moves first
      for (const g of names) { G[g].fx = 0; G[g].fy = 0; G[g].fz = 0; }
      /* Repulsion, every pair. Seventy galaxies is ~2,400 pairs.

         This was an inverse-square force divided by each body's own mass -- that
         is, a real gravitational acceleration -- and on a library with a long
         tail of tiny genres it produced exactly what physics says it should: the
         heavy galaxies barely moved, and every one-track genre was flung to the
         edge of the sky. Those specks then set the frame, so the fit view was
         mostly empty rim with the entire library crushed into the middle fifth.

         What the sky actually needs is packing, not orbital mechanics. So the
         repulsion is now short-range: galaxies push only while they overlap, in
         proportion to how far in they are, and both move -- split by mass, so a
         big one yields less than a speck but is not immovable. Past contact they
         ignore each other entirely and the bonds and the centring do the rest.
         The result fills the volume instead of shelling it. */
      for (let i = 0; i < names.length; i++){
        for (let j = i + 1; j < names.length; j++){
          const A = G[names[i]], B = G[names[j]];
          let dx = A.x - B.x, dy = A.y - B.y, dz = A.z - B.z;
          let d2 = dx*dx + dy*dy + dz*dz;
          if (d2 < 1e-6){ dx = 1e-3; dy = dz = 0; d2 = 1e-6; }
          const d = Math.sqrt(d2);
          const want = (A.radius + B.radius) * GAP;
          if (d >= want) continue;                  // not touching: nothing to resolve
          const push = (want - d) * 0.45;
          // Share the correction by mass: the lighter body gives way.
          const total = A.mass + B.mass;
          const ux = dx/d, uy = dy/d, uz = dz/d;
          const ka = B.mass / total, kb = A.mass / total;
          A.fx += ux*push*ka; A.fy += uy*push*ka; A.fz += uz*push*ka;
          B.fx -= ux*push*kb; B.fy -= uy*push*kb; B.fz -= uz*push*kb;
        }
      }
      // Attraction along the bonds -- the part that makes neighbours neighbours.
      for (const [A, B, w] of pull){
        const dx = B.x - A.x, dy = B.y - A.y, dz = B.z - A.z;
        const d = Math.hypot(dx, dy, dz) || 1e-3;
        const rest = (A.radius + B.radius) * 1.5;
        const f = grav * w * (d - rest) * 0.10;
        const ux = dx/d, uy = dy/d, uz = dz/d;
        A.fx += ux*f; A.fy += uy*f; A.fz += uz*f;
        B.fx -= ux*f; B.fy -= uy*f; B.fz -= uz*f;
      }
      for (const g of names){
        const A = G[g];
        A.fx -= A.x * hold; A.fy -= A.y * hold; A.fz -= A.z * hold;  // hold the sky together
        const stepMax = 0.25 * cool;
        const m = Math.hypot(A.fx, A.fy, A.fz);
        const k = m > stepMax ? stepMax / m : 1;
        A.x += A.fx * k; A.y += A.fy * k; A.z += A.fz * k;
      }
    }

    // Who is pulling on whom, once it has all settled: the direction and
    // strength of a galaxy's strongest neighbour, which is what its arms lean
    // toward. A galaxy with no strong neighbour keeps its own shape.
    for (const g of names){ G[g].tide = null; }
    for (const [A, B, w] of pull){
      const dx = B.x - A.x, dy = B.y - A.y, dz = B.z - A.z;
      const d = Math.hypot(dx, dy, dz) || 1e-3;
      // Tidal strength: how hard, relative to how far. Near neighbours deform
      // each other; a strong bond across the sky barely registers, which is how
      // tides actually work.
      const t = w / (d * d + 0.05);
      for (const [X, sx, sy, sz] of [[A, dx, dy, dz], [B, -dx, -dy, -dz]]){
        if (!X.tide || t > X.tide.t) X.tide = { t, x: sx/d, y: sy/d, z: sz/d };
      }
    }
    // Where the biggest galaxy landed becomes the origin, so the view still
    // opens on the busiest music rather than on wherever the relaxation drifted.
    const c = G[names[0]];
    for (const g of names){ G[g].x -= c.x; G[g].y -= c.y; G[g].z -= c.z; }
    return G;
  }

  /* Divide each galaxy into its systems and place them.

     A system sits where its members' sound puts it -- the mean of their
     embedding coordinates -- so two subgenres that actually sound alike are
     neighbours inside the galaxy, exactly as two tracks are. Its size follows
     its share of the galaxy, the same square root the galaxies themselves use.

     Then they are pushed apart until they stop overlapping, because two systems
     occupying the same space is two systems you cannot see. A handful per galaxy
     makes this a few hundred operations. */
  function buildSystems(G, members){
    for (const gname in G){
      const g = G[gname];
      const mem = members[gname] || [];
      const acc = {};
      for (const m of mem){
        const k = systemKeyOf(m.n);
        const a = acc[k] || (acc[k] = { k, n: 0, x: 0, y: 0, z: 0 });
        a.n++; a.x += m.e[0]; a.y += m.e[1]; a.z += m.e[2];
      }
      const list = Object.values(acc);
      for (const a of list){ a.x /= a.n; a.y /= a.n; a.z /= a.n; }
      const total = mem.length || 1;
      for (const a of list){
        // In galaxy-radius units throughout; the galaxy's own radius is applied
        // once, at draw time.
        a.sr = clamp(0.62 * Math.sqrt(a.n / total), 0.05, 0.52);
      }
      // Separate them. Position only in the disc plane -- a system is a place in
      // the galaxy, and letting them slide in depth as well would just hide the
      // overlap rather than resolve it.
      for (let pass = 0; pass < 90; pass++){
        let moved = false;
        for (let i = 0; i < list.length; i++){
          for (let j = i + 1; j < list.length; j++){
            const A = list[i], B = list[j];
            let dx = A.x - B.x, dy = A.y - B.y;
            let d = Math.hypot(dx, dy);
            if (d < 1e-6){ dx = (i % 2 ? 1 : -1) * 1e-3; dy = 1e-3; d = 1.4e-3; }
            const want = (A.sr + B.sr) * 1.12;
            if (d >= want) continue;
            const push = (want - d) / 2;
            const ux = dx / d, uy = dy / d;
            A.x += ux * push; A.y += uy * push;
            B.x -= ux * push; B.y -= uy * push;
            moved = true;
          }
        }
        // Keep them inside the galaxy they belong to.
        for (const a of list){
          const d = Math.hypot(a.x, a.y), lim = Math.max(0.05, 1.3 - a.sr);
          if (d > lim){ a.x *= lim / d; a.y *= lim / d; }
        }
        if (!moved) break;
      }
      /* Spread them out to fill the galaxy.

         A system sits at the MEAN of its members' coordinates, and a set of
         means is always tighter than the points it came from -- so left alone
         the systems huddle near the middle and the galaxy is mostly empty rim.
         Scaling them out to touch the edge keeps their relative arrangement,
         which is the part that carries meaning, and uses the room. */
      let far = 0;
      for (const a of list) far = Math.max(far, Math.hypot(a.x, a.y) + a.sr);
      if (far > 0.01 && list.length > 1){
        const k = 1.18 / far;
        for (const a of list){ a.x *= k; a.y *= k; }
      }
      g.systems = {};
      for (const a of list){
        let rad = Math.hypot(a.x, a.y);
        const ang0 = Math.atan2(a.y, a.x);
        // Concentrate toward the core, and lag the outer systems so the galaxy
        // is wound into arms made of clusters rather than of single stars.
        rad = Math.pow(clamp(rad / 1.3, 0, 1), 1.35) * 1.3;
        // Every member of a system shares its subgenre, so they share a shade;
        // one of them is as good as an average and costs nothing.
        const first = (members[gname] || []).find(m => systemKeyOf(m.n) === a.k);
        g.systems[a.k] = {
          rad, sr: a.sr, ang: ang0 + 1.6 * rad, z: a.z * 0.34,
          mx: a.x, my: a.y, mz: a.z, n: a.n,
          hue: first ? first.n.hue : 210, sat: first ? first.n.sat : 60,
          // Mostly rigid with the galaxy, a little quicker toward the middle --
          // the systems march around together and the arms survive.
          spin: g.spin * (1 + 0.22 / (rad + 0.35)),
        };
      }
    }
  }

  /* Place one track inside its galaxy.

     The disc is built from the track's own embedding, as before -- two PCA axes
     give the position in the plane and the third gives the thickness, so tracks
     that sound alike still sit together. What is new is what happens to that
     position afterwards:

       It is spun into the galaxy's own orientation, so the disc lies in that
       galaxy's plane rather than the world's.

       It is sheared with radius -- the outside lags the inside, which is what
       makes a rotating disc into a spiral rather than a smear. Differential
       rotation is the whole reason real galaxies have arms.

       If a neighbour is close and strongly bound, the outer stars are dragged
       toward it. That is the swirl: two galaxies that share a lot of tracks
       reach for each other, and the reach is strongest exactly where a real
       tidal arm would be -- at the rim, on the near side.

     Stored as an orbit rather than a point, because the stars turn: uniPlaceAt()
     re-places them every frame. Same split as Solar, and for the same reason --
     a galaxy that does not move is a spray of dots that happens to be
     galaxy-shaped, and rotation is most of what makes a disc read as an object.

     Two orbits, not one. The system carries the track around the galaxy; the
     track turns inside the system, faster, the way a moon goes round faster than
     its planet goes round the sun. Both are worked out once here. */
  function uniOrbit(n, g, e, jitter){
    const rr = jitter;
    const sys = (g.systems && g.systems[systemKeyOf(n)]) || null;
    // Offset from the system's own centre: where this track sits among its
    // subgenre, still from its own embedding, so the finest grouping the map can
    // make is still the one the model heard.
    const ox = sys ? e[0] - sys.mx : e[0];
    const oy = sys ? e[1] - sys.my : e[1];
    const oz = sys ? e[2] - sys.mz : e[2];
    let rad = Math.hypot(ox, oy) || 1e-4;
    const ang0 = Math.atan2(oy, ox);
    /* Concentrate toward the middle. Spread evenly, a cluster draws as a smudge
       of constant brightness; the fade from a bright centre outward is a large
       part of what makes one read as an object. Only moves stars inward --
       nothing is invented. */
    rad = Math.pow(clamp(rad / 1.3, 0, 1), 1.55);
    // Scaled into the system it belongs to, so a subgenre of sixty tracks is a
    // small dense knot and one of six hundred is a broad one.
    const scale = sys ? sys.sr : 1.3;
    n.gorb = {
      g, sys,
      rad: rad * scale,
      ang: ang0,
      z: oz * 0.34 * scale,
      // A little fixed scatter, so a system is made of stars rather than drawn
      // as a ring.
      jx: (rr() - 0.5) * 0.05 * scale,
      jy: (rr() - 0.5) * 0.05 * scale,
      jz: (rr() - 0.5) * 0.05 * scale,
      // Quicker than the system's own march around the galaxy, and in its own
      // direction, so each cluster reads as a thing turning rather than a patch
      // being carried.
      spin: g.spin * (rr() < 0.5 ? -1 : 1) * (2.0 + rr() * 1.6),
    };
    uniPlaceAt(n, 0);
  }

  /* A system's own centre, in world coordinates. uniPlaceAt() works this out for
     every track; the gas needs it once per system. */
  function systemWorld(g, sys, t, out){
    const R = g.radius, b = g.basis;
    const sa = sys.ang + t * sys.spin;
    const px = Math.cos(sa) * sys.rad * R, py = Math.sin(sa) * sys.rad * R, pz = sys.z * R;
    let x = b.u[0]*px + b.v[0]*py + b.w[0]*pz;
    let y = b.u[1]*px + b.v[1]*py + b.w[1]*pz;
    let z = b.u[2]*px + b.v[2]*py + b.w[2]*pz;
    if (g.tide){
      const reach = clamp(g.tide.t * 0.30, 0, 0.55) * (sys.rad / 1.3);
      x += g.tide.x * reach * R; y += g.tide.y * reach * R; z += g.tide.z * reach * R;
    }
    out.x = g.x + x; out.y = g.y + y; out.z = g.z + z;
    return out;
  }

  function uniPlaceAt(n, t){
    const o = n.gorb; if (!o) return;
    const g = o.g, R = g.radius, sys = o.sys;
    // Where the system is, this instant, around the galaxy's middle.
    let cx = 0, cy = 0, cz = 0;
    if (sys){
      const sa = sys.ang + t * sys.spin;
      cx = Math.cos(sa) * sys.rad; cy = Math.sin(sa) * sys.rad; cz = sys.z;
    }
    // ...and where the track is, this instant, around the system's middle.
    const a = o.ang + t * o.spin;
    let px = (cx + Math.cos(a) * o.rad + o.jx) * R;
    let py = (cy + Math.sin(a) * o.rad + o.jy) * R;
    let pz = (cz + o.z + o.jz) * R;
    // Into the galaxy's orientation.
    const b = g.basis;
    let x = b.u[0]*px + b.v[0]*py + b.w[0]*pz;
    let y = b.u[1]*px + b.v[1]*py + b.w[1]*pz;
    let z = b.u[2]*px + b.v[2]*py + b.w[2]*pz;
    // The tide, if this galaxy has a strong close neighbour. Proportional to how
    // far out the star is, so the core stays put and the rim streams away --
    // which is what a tidal arm looks like.
    if (g.tide){
      const reach = clamp(g.tide.t * 0.30, 0, 0.55)
                  * (((sys ? sys.rad : 0) + o.rad) / 1.3);
      x += g.tide.x * reach * R;
      y += g.tide.y * reach * R;
      z += g.tide.z * reach * R;
    }
    n.x3 = g.x + x; n.y3 = g.y + y; n.z3 = g.z + z;
  }

  /* ---- build 3-D positions for the current mode -------------------- */
  /* Where the map's mass is: the densest point of the star cloud.

     The plain centre of mass is the wrong answer. It is the mean position, so a
     handful of far-flung outliers drag it as hard as a thousand tracks in a
     cluster, and between two clusters it lands in the empty space BETWEEN them
     -- pointing the camera at nothing, which is exactly what we are fixing.

     So: mean-shift. Start at the centre of mass, then repeatedly re-centre on
     the Gaussian-weighted mean of whatever is nearby. Each step walks the point
     uphill in density, and shrinking the bandwidth as it goes tightens it onto
     the peak. That converges on the busiest REGION rather than the average
     position -- gravity, not arithmetic.

     Sampled on a stride so the cost is bounded by the sample, not the library:
     the mode of a few thousand tracks is the mode of thirty thousand. */
  function gravity(nodes){
    if (!nodes.length){ BARY.x = BARY.y = BARY.z = 0; return; }
    const stride = Math.max(1, Math.floor(nodes.length / 4000));
    const pts = [];
    for (let i = 0; i < nodes.length; i += stride){
      const n = nodes[i];
      if (Number.isFinite(n.x3) && Number.isFinite(n.y3) && Number.isFinite(n.z3)) pts.push(n);
    }
    if (!pts.length){ BARY.x = BARY.y = BARY.z = 0; return; }
    let cx = 0, cy = 0, cz = 0;
    for (const n of pts){ cx += n.x3; cy += n.y3; cz += n.z3; }
    cx /= pts.length; cy /= pts.length; cz /= pts.length;
    // Bandwidth starts at the cloud's RMS spread: wide enough that the first
    // step sees the whole field and cannot get stuck in a local knot.
    let v = 0;
    for (const n of pts){
      const dx = n.x3-cx, dy = n.y3-cy, dz = n.z3-cz;
      v += dx*dx + dy*dy + dz*dz;
    }
    let h = Math.sqrt(v / pts.length) * 0.6;
    if (!(h > 1e-6)){ BARY.x = cx; BARY.y = cy; BARY.z = cz; return; }   // one point, or all coincident
    for (let it = 0; it < 12; it++){
      const inv = 1 / (2*h*h);
      let sx = 0, sy = 0, sz = 0, sw = 0;
      for (const n of pts){
        const dx = n.x3-cx, dy = n.y3-cy, dz = n.z3-cz;
        const w = Math.exp(-(dx*dx + dy*dy + dz*dz) * inv);
        sx += n.x3*w; sy += n.y3*w; sz += n.z3*w; sw += w;
      }
      if (!(sw > 0)) break;              // bandwidth collapsed past every point
      cx = sx/sw; cy = sy/sw; cz = sz/sw;
      h *= 0.88;
    }
    BARY.x = cx; BARY.y = cy; BARY.z = cz;
  }

  /* Give a node its colour. The three things derived from it -- the sprites,
     the flat disc's CSS colour string, the sub-cluster key the labels and the
     legend group by -- are remembered on the node and re-resolved here, in
     the one place the colour can change, rather than rebuilt per frame. */
  function setShade(n, sh){
    n.hue = sh.h; n.sat = sh.s; n.dl = sh.dl;
    n._spGlow = null;               // colour changed -> re-resolve its sprite
    n._css = null;
    n.sk = `${n.fam}||${n.style || n.fam}`;
  }
  // The flat disc's fill: static per node, and a CSS colour parse per assignment.
  const discCss = n => n._css || (n._css =
    `hsl(${hueOk(n.hue)} ${pctOk(n.sat, 64)}% ${clamp(SPRITE_LIGHT + (n.dl || 0), 20, 84)}%)`);

  function layout(){
    byHash.clear();
    // Harvest the server's paint first: every shade below depends on it, so it
    // has to be complete before the first lookup rather than filled in as we go.
    KCOL = {};
    for (const n of NODES){
      if (n.style && n.kcolor) KCOL[n.style] = n.kcolor;
      for (const r of n.rings || []) if (r.keystone && r.color) KCOL[r.keystone] = r.color;
    }
    for (const n of NODES){
      n.fam = familyOf(n.style || n.styles[0] || 'Other') || 'Other';
      let sh = styleShade(n.fam, n.style || n.styles[0]);   // per-subgenre shade of the family
      if (n.mix && n.mix[1] > 0.02){                        // lean toward the 2nd genre by its %
        const f2 = familyOf(n.mix[0]) || n.fam;
        sh = mixShade(sh, styleShade(f2, n.mix[0]), Math.min(0.5, n.mix[1]));
      }
      setShade(n, sh);
      byHash.set(n.hash, n);
    }
    /* n.grp is what the BIG labels name, which is not always the genre.

       In the Universe clustered by vibe, a galaxy IS a vibe -- so labelling
       those galaxies "HOUSE" and "TECHNO" describes the wrong thing entirely.
       The stars keep their genre colours (that is still what they are), but the
       label layer, the legend counts and the click-to-fly targets all follow the
       group the layout actually used. */
    // In the Universe that is always the galaxy the star was placed in -- by
    // vibe, by family or by genre. Naming those galaxies after their families
    // while gravity had sorted them by genre described the wrong grouping.
    for (const n of NODES) n.grp = (mapMode === 'universe') ? uniGroupOf(n) : n.fam;
    GROUP_KIND = (mapMode === 'universe') ? UNI.by : 'fam';
    COUNTS = {};
    for (const n of NODES) COUNTS[n.grp] = (COUNTS[n.grp]||0)+1;
    FAMS = Object.keys(COUNTS).sort((a,b)=>COUNTS[b]-COUNTS[a]);
    const NC = (NODES.find(n=>n.e)||{}).e?.length || 0;

    if (mapMode === 'tree'){
      buildTree();
      buildLegend();
      countMap.textContent = mapCountText();
      return;
    }

    if (mapMode === 'universe'){
      /* The Universe: the library as a sky of galaxies.

         Two ways to decide what a galaxy IS, and they answer different
         questions. Clustering by ARCHGENRE asks "where does the music sit in
         the taxonomy"; clustering by VIBE asks "where does it sit in MY head".
         Neither is derivable from the other, so both are offered rather than
         one being picked for you.

         Within a galaxy, position still comes from the first three PCA axes of
         the track's own embedding -- so a galaxy is not a blob, it has real
         internal structure, and two tracks that sound alike sit together inside
         it exactly as they did before. */
      const p = [0,1,2].map(j => pctl(NODES.map(n=>Math.abs(n.e?n.e[j]:0)),0.96)||1);
      GALAXIES = uniAnchors();
      const stray = { name:UNI_FIELD, x:0, y:0, z:0, radius:0.5, tide:null,
                      basis:galaxyBasis(UNI_FIELD), spin:0.07, systems:{} };
      // One pass to work out each track's place in the embedding, so the systems
      // can be built from their members before any track is placed inside one.
      const members = {};
      const seat = [];
      for (const n of NODES){
        const g = GALAXIES[uniGroupOf(n)] || stray;
        const e = [
          clamp((n.e?n.e[0]:0)/p[0], -1.3, 1.3),
          clamp((n.e?n.e[1]:0)/p[1], -1.3, 1.3),
          clamp((n.e?n.e[2]:0)/p[2], -1.3, 1.3),
        ];
        (members[g.name] || (members[g.name] = [])).push({ n, e });
        seat.push({ n, g, e });
      }
      buildSystems(GALAXIES, members);
      buildSystems({ [stray.name]: stray }, members);
      for (const st of seat){
        const r = rng(st.n.hash);
        uniOrbit(st.n, st.g, st.e, r);
        st.n.ph = r()*6.28;
      }
    } else if (mapMode === 'solar'){
      /* Solar returns here rather than falling through, the way tree does.

         Falling through meant the code below rebuilt CENTROIDS and
         STYLE_CENTROIDS from EVERY node -- including the 3000-odd tracks not in
         the playlist, still carrying stale positions from the previous layout.
         The result was the whole regions-mode label set (BASS MUSIC, TRANCE,
         TECHNO...) painted on top of a system that only contains 140 tracks. */
      solarLayout();
      buildLegend();
      countMap.textContent = mapCountText();
      return;
    } else {
      // regions: biggest family at the core, the rest on a Fibonacci sphere;
      // members offset in 3-D by their 3 highest within-family-variance axes.
      const anchors = {};
      const big = FAMS[0];
      anchors[big] = { x:0, y:0, z:0 };
      const rest = FAMS.slice(1);
      rest.forEach((f,i) => {
        const k = i + 0.5;
        const phi = Math.acos(1 - 2*k/rest.length);
        const th  = Math.PI * (1 + Math.sqrt(5)) * k;
        anchors[f] = { x:1.7*Math.cos(th)*Math.sin(phi),
                       y:1.7*Math.sin(th)*Math.sin(phi),
                       z:1.7*Math.cos(phi) };
      });
      // sub-clusters: within each family, group tracks by dominant style
      // (subgenre) and give each style its own sub-anchor on a small sphere
      // around the family anchor -- so Dubstep and Drum n Bass separate visibly
      // inside Bass Music instead of blending together.
      const styleAnchors = {}, styleCount = {};
      for (const f of FAMS){
        const cnt = {};
        for (const n of NODES) if (n.fam===f){ const s=n.style||f; cnt[s]=(cnt[s]||0)+1; }
        const styles = Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a]);
        const famSpread = 0.06 + Math.sqrt(COUNTS[f]) * 0.013;
        const subR = famSpread * (styles.length>1 ? 1.0 : 0);   // more room for subgenres
        styles.forEach((s,i) => {
          styleCount[`${f}||${s}`] = cnt[s];
          const a = anchors[f];
          if (styles.length===1){ styleAnchors[`${f}||${s}`] = {x:a.x,y:a.y,z:a.z}; return; }
          const k = i + 0.5;
          const phi = Math.acos(1 - 2*k/styles.length);
          const th  = Math.PI * (1 + Math.sqrt(5)) * k;
          styleAnchors[`${f}||${s}`] = {
            x: a.x + subR*Math.cos(th)*Math.sin(phi),
            y: a.y + subR*Math.sin(th)*Math.sin(phi),
            z: a.z + subR*Math.cos(phi),
          };
        });
      }
      // per-family: pick 3 highest-variance components + their p90 spreads
      const fa = {};
      for (const f of FAMS){
        const mem = NODES.filter(n=>n.fam===f && n.e);
        const mean = new Array(NC).fill(0), varc = new Array(NC).fill(0);
        for (const n of mem) for (let j=0;j<NC;j++) mean[j]+=n.e[j];
        for (let j=0;j<NC;j++) mean[j]/=(mem.length||1);
        for (const n of mem) for (let j=0;j<NC;j++) varc[j]+=(n.e[j]-mean[j])**2;
        const ord = varc.map((v,j)=>[v,j]).sort((a,b)=>b[0]-a[0]);
        const ax = ord.map(o=>o[1]).slice(0,3);
        while (ax.length<3) ax.push(ax[0]||0);
        const pc = ax.map(j => pctl(mem.map(n=>Math.abs(n.e[j]-mean[j])),0.90));
        fa[f] = { ax, mean, pc };
      }
      for (const n of NODES){
        const s = n.style || n.fam;
        const a = styleAnchors[`${n.fam}||${s}`] || anchors[n.fam];
        const f = fa[n.fam];
        const famSpread = 0.06 + Math.sqrt(COUNTS[n.fam]) * 0.013;
        // tight sub-cluster so subgenres stay distinct
        const spread = Math.min(famSpread*0.42, 0.03 + Math.sqrt(styleCount[`${n.fam}||${s}`]||1)*0.011);
        const r = rng(n.hash);
        const loc = j => n.e && f ? clamp((n.e[f.ax[j]]-f.mean[f.ax[j]])/f.pc[j], -1.15, 1.15)
                                  : (r()-0.5);
        n.x3 = a.x + loc(0)*spread + (r()-0.5)*0.012;
        n.y3 = a.y + loc(1)*spread + (r()-0.5)*0.012;
        n.z3 = a.z + loc(2)*spread + (r()-0.5)*0.012;
        n.ph = r()*6.28;
      }
    }
    // family label anchors = member centroid (3-D)
    CENTROIDS = {};
    const acc = {}; for (const f of FAMS) acc[f] = {x:0,y:0,z:0,c:0};
    for (const n of NODES){ const a=acc[n.grp]; if (!a) continue;
      a.x+=n.x3; a.y+=n.y3; a.z+=n.z3; a.c++; }
    for (const f of FAMS){ const a=acc[f];
      CENTROIDS[f] = { x:a.x/a.c, y:a.y/a.c, z:a.z/a.c, n:COUNTS[f] }; }
    gravity(NODES);
    // Measured from BARY, not the origin: the projection subtracts the pivot, so
    // the radius that has to fit on screen is the distance from what the camera
    // is looking AT. Origin-relative, a cloud whose mass sits off to one side
    // would fit its far edge and push the near one out of frame.
    setSceneRadius(NODES.map(n =>
      Math.hypot(n.x3-BARY.x, n.y3-BARY.y, n.z3-BARY.z)));

    // subgenre label anchors: centroid of each style sub-cluster with >=labelMin
    // members. In regions they fade in as you zoom into a cluster (semantic zoom /
    // LOD). Galaxy has no genre hierarchy, so there's no zoom-fade -- but we still
    // compute the anchors so "Always show subgenres" and clicking a genre can
    // reveal them there too.
    STYLE_CENTROIDS = {};
    {
      // label threshold scales with library size: a subgenre earns a label once
      // it has ~1/90th of the library (min 2, max 12) -- so a small library
      // surfaces subgenres eagerly, a large one stays uncluttered.
      const labelMin = Math.max(2, Math.min(12, Math.round(NODES.length / 90)));
      const sacc = {};
      // Clustered by vibe, the sub-clusters inside a galaxy are not subgenres of
      // it -- a vibe has no subgenres -- and the shade lookup below keys on the
      // genre family, which the group no longer is. Skip the layer entirely
      // rather than draw mislabelled, miscoloured text.
      if (GROUP_KIND === 'vibe'){
        STYLE_CENTROIDS = {};
        buildLegend();
        countMap.textContent = mapCountText();
        return;
      }
      for (const n of NODES){
        const key = n.sk;
        if (!sacc[key]) sacc[key] = { x:0, y:0, z:0, c:0, style:n.style || n.fam };
        const a = sacc[key]; a.x+=n.x3; a.y+=n.y3; a.z+=n.z3; a.c++;
      }
      for (const key in sacc){ const a = sacc[key];
        if (a.c >= labelMin) STYLE_CENTROIDS[key] = { x:a.x/a.c, y:a.y/a.c, z:a.z/a.c, n:a.c, style:a.style }; }
    }

    buildLegend();
    countMap.textContent = mapCountText();
  }

  /* The status line at the right of the toolbar.

     Single definition because there are four call sites -- layout(), each mode
     branch, and the filter sync -- and when they each spelled it out
     independently they disagreed: the Universe clustered by vibe would render
     "2 vibes" from layout() and then be overwritten with "2 genres" by the
     filter sync a moment later. */
  function mapCountText(){
    const n = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
    if (mapMode === 'solar'){
      if (!SOLAR_SET) return 'pick a saved playlist to see it as a solar system';
      const tracks = SOLAR_RINGS.reduce((a, r) => a + r.n, 0);
      return `${n(tracks, 'track')} · ${n(SOLAR_RINGS.length, 'orbit')} · `
        + `${SOLAR_NAME || 'solar'}`;
    }
    return `${n(NODES.length, 'track')} · ${n(FAMS.length, groupNoun())} · ${mapMode}`;
  }

  function buildLegend(){
    // Subgenre breakdown per group. n.grp is the genre family in every mode
    // except the Universe clustered by vibe, where it is the vibe -- and there
    // the legend must list the same things the map labels, or clicking a legend
    // row would filter on a name nothing on screen carries.
    //
    // Each subgenre row also remembers the PulseRoots family (n.fam) its tracks
    // carry, because that -- not the group -- is what focusStyle() filters on
    // and what the subgenre shade (styleShade / SUB_HUE) is keyed by. In the
    // Universe the group is a keystone or a vibe, and passing that as the
    // family made every subgenre row a silent no-op and its recolour a key
    // nothing read. n.fam is a function of the style (familyOf), so one style
    // has one family and the first seen is the only one.
    const subs = {};
    for (const n of NODES){ const st = n.style || n.fam;
      const g = (subs[n.grp] = subs[n.grp] || {});
      const e = (g[st] = g[st] || { c:0, fam:n.fam });
      e.c++; }
    const groups = FAMS.map(f => {
      const active = filterFam === f ? ' active' : '';
      const head = `<span class="leg leg-fam${active}" data-fam="${escapeHtml(f)}">`
        + `<span class="dot" title="click to recolour this genre" style="background:${famCss(f)}"></span>`
        + `<b>${escapeHtml(f)}</b>&nbsp;${COUNTS[f]}</span>`;
      // a lone subgenre identical to the family isn't really a "sub" -> skip it
      const list = Object.entries(subs[f] || {}).filter(([st]) => st !== f).sort((a,b) => b[1].c-a[1].c);
      if (!list.length) return `<div class="leg-group">${head}</div>`;
      const shown = list.slice(0, 10), more = list.length - shown.length;
      const subHtml = shown.map(([st, e]) => {
        const c = e.c, fam = e.fam;
        const sh = styleShade(fam, st);
        const col = `hsl(${sh.h} ${clamp(sh.s, 40, 88)}% ${clamp(58 + sh.dl, 44, 70)}%)`;
        return `<span class="leg-sub" data-fam="${escapeHtml(fam)}" data-style="${escapeHtml(st)}"`
          + ` title="zoom to ${escapeHtml(st)}"><span class="sdot" title="click to recolour this subgenre"`
          + ` style="background:${col}"></span>${escapeHtml(st)} ${c}</span>`;
      }).join('') + (more > 0 ? `<span class="leg-more">+${more} more</span>` : '');
      return `<div class="leg-group">${head}<div class="leg-subs">${subHtml}</div></div>`;
    }).join('');
    legendEl.innerHTML =
      `<button class="leg-toggle" type="button" title="show / hide the legend">&#9698; `
      + `${groupNoun()}s</button>`
      + `<div class="leg-body">${groups}</div>`;
    legendEl.classList.toggle('collapsed', legendCollapsed);
    legendEl.querySelector('.leg-toggle').onclick = () => {
      legendCollapsed = !legendCollapsed;
      legendEl.classList.toggle('collapsed', legendCollapsed);
      try{ localStorage.setItem('vibeLegend', legendCollapsed ? 'off' : 'on'); }catch(_){ /* private */ }
    };
    // click a family header -> zoom to that genre; its dot -> recolour it;
    // click a subgenre -> zoom to that sub-cluster
    legendEl.querySelectorAll('.leg-fam').forEach(el => {
      const f = el.getAttribute('data-fam');
      el.querySelector('.dot').onclick = ev => { ev.stopPropagation(); pickFamColor(f, ev.currentTarget); };
      el.onclick = () => focusFamily(f);
    });
    legendEl.querySelectorAll('.leg-sub').forEach(el => {
      const f = el.getAttribute('data-fam'), st = el.getAttribute('data-style');
      const sd = el.querySelector('.sdot');
      if (sd) sd.onclick = ev => { ev.stopPropagation(); pickSubColor(f, st, ev.currentTarget); };
      el.onclick = () => focusStyle(f, st);
    });
    // (re)populate the filter dropdown, preserving the current choice
    const fe = document.getElementById('map-filter');
    if (fe){
      const cur = fe.value;
      fe.innerHTML = `<option value="">all genres</option>`
        + `<option value="__flagged__">⚠ likely misreads</option>`
        + FAMS.map(f => `<option value="${escapeHtml(f)}">${escapeHtml(f)} · ${COUNTS[f]}</option>`).join('');
      const keep = (cur === '__flagged__' || FAMS.includes(cur));
      fe.value = keep ? cur : '';
      // Reset the STATE too, not just the control. passes() tests filterFam
      // against n.grp, so a stale genre name left over from a different
      // grouping matches nothing and blanks the map with no visible cause.
      if (!keep && filterFam) filterFam = null;
    }
    // the label-panel "isolate genre" dropdown draws from the same family list
    const oe = document.getElementById('lbl-only');
    if (oe){
      oe.innerHTML = `<option value="">show all</option>`
        + FAMS.map(f => `<option value="${escapeHtml(f)}">${escapeHtml(f)} · ${COUNTS[f]}</option>`).join('');
      oe.value = FAMS.includes(LBL.onlyFam) ? LBL.onlyFam : (LBL.onlyFam = '');
    }
  }

  // a shared hidden native colour input; each caller wires its own onHue.
  let _picker = null;
  function openColorPicker(seedHex, anchor, onHue){
    if (!_picker){
      _picker = document.createElement('input');
      _picker.type = 'color';
      _picker.style.cssText = 'position:fixed;width:0;height:0;opacity:0;border:0;padding:0;pointer-events:none';
      document.body.appendChild(_picker);
    }
    _picker.value = seedHex;
    _picker.oninput = () => { const hue = hexToHue(_picker.value); if (hue != null) onHue(Math.round(hue)); };
    const r = anchor.getBoundingClientRect();
    _picker.style.left = r.left + 'px'; _picker.style.top = r.bottom + 'px';
    _picker.click();
  }
  // recolour a whole genre family (and its subgenre shades); persists + re-applies.
  function pickFamColor(fam, anchor){
    openColorPicker(hslHex(famHue(fam), 62, 62), anchor, hue => {
      FAM_HUE[fam] = hue;
      try{ localStorage.setItem('vibeFamHue', JSON.stringify(FAM_HUE)); }catch(_){ /* private */ }
      if (NODES.length) layout();                     // recompute node shades + legend
    });
  }
  // recolour ONE subgenre to an exact hue (overrides its family-derived shade).
  function pickSubColor(fam, style, anchor){
    const sh = styleShade(fam, style);
    openColorPicker(hslHex(sh.h, clamp(sh.s,40,88), clamp(58+sh.dl,44,70)), anchor, hue => {
      SUB_HUE[`${fam}||${style}`] = hue;
      try{ localStorage.setItem('vibeSubHue', JSON.stringify(SUB_HUE)); }catch(_){ /* private */ }
      if (NODES.length) layout();
    });
  }

  /* ---- organic left-to-right genre tree (root -> families -> subgenres) ---
     A taxonomy of the library (à la pulse.roots / ishkur). Branch LENGTH grows
     with track count -> big branches reach farther before fanning out, so the
     ends aren't a straight column. */
  function buildTree(){
    /* Deciding each style's ONE parent is the whole job here.

       A style can read under more than one family across a library -- about 20
       of 91 do -- because `family` follows the keystone classification while
       `style` follows the dominant-style read, and a handful of tracks
       disagree. Grouped naively that draws Dubstep as a child of Bass (486
       tracks) AND as stray one-track dots under Dance, Chill and Experimental:
       the same genre three or four times over, most of them too small to label.
       That is the "dots, then duplicated again" the tree was showing.

       So resolve it once, up front: a style belongs to the family it appears
       under most often, and every one of its tracks hangs there. Ties break
       toward the bigger family, which keeps the result stable between loads. */
    const styleFam = {};
    for (const n of NODES){
      const s = n.style || n.fam;
      (styleFam[s] ||= {});
      styleFam[s][n.fam] = (styleFam[s][n.fam] || 0) + 1;
    }
    const famSize = {};
    for (const n of NODES) famSize[n.fam] = (famSize[n.fam] || 0) + 1;
    const parentOf = {};
    for (const s in styleFam){
      let best = null, bestN = -1;
      for (const f in styleFam[s]){
        const c = styleFam[s][f];
        if (c > bestN || (c === bestN && (famSize[f]||0) > (famSize[best]||0))){ bestN = c; best = f; }
      }
      parentOf[s] = best;
    }

    const groups = {};
    for (const n of NODES){
      const sub = n.style || n.fam;
      const fam = parentOf[sub] || n.fam;
      // Stash the resolved parent on the node: the tree card looks branches up
      // by it, and recomputing the resolution there could disagree with what
      // was actually drawn.
      n.treeFam = fam;
      (groups[fam] ||= { subs:{}, count:0, self:0 });
      groups[fam].count++;
      // A style named after its own family IS that family, not a child of it.
      // "Experimental > Experimental" is a rendering artefact of the data
      // shape, not something in the taxonomy -- count it on the parent and
      // give it no leaf.
      if (sub === fam) groups[fam].self++;
      else groups[fam].subs[sub] = (groups[fam].subs[sub]||0) + 1;
    }
    const famNames = Object.keys(groups).sort((a,b)=>groups[b].count-groups[a].count);
    const maxFam = Math.max(1, ...famNames.map(f=>groups[f].count));
    let maxSub = 1;
    for (const f of famNames) for (const s in groups[f].subs) maxSub = Math.max(maxSub, groups[f].subs[s]);
    const famLen = c => 0.7 + 1.9 * Math.sqrt(c / maxFam);   // root -> family reach
    const subLen = c => 0.5 + 1.8 * Math.sqrt(c / maxSub);   // family -> subgenre reach

    const nodes = [], links = [];
    let row = 0, maxX = 0;
    for (const fam of famNames){
      const g = groups[fam];
      const subNames = Object.keys(g.subs).sort((a,b)=>g.subs[b]-g.subs[a]);
      const famX = famLen(g.count);
      const subInfo = [];
      for (const sub of subNames){
        const y = row++, sx = famX + subLen(g.subs[sub]);
        maxX = Math.max(maxX, sx);
        subInfo.push({ sub, y, sx, count:g.subs[sub] });
      }
      // A family whose tracks are ALL self-named has no children, so there is
      // no child mean to centre it on -- take a row of its own instead of
      // dividing by zero and placing the node at NaN (which silently drops it).
      const fy = subInfo.length
        ? subInfo.reduce((a,b)=>a+b.y,0) / subInfo.length
        : row++;
      maxX = Math.max(maxX, famX);
      nodes.push({ kind:'fam', label:fam, fam, x:famX, y:fy, count:g.count });
      links.push([0, 0, famX, fy, fam]);                 // root -> family (root y = centre)
      for (const si of subInfo){
        nodes.push({ kind:'sub', label:si.sub, fam, x:si.sx, y:si.y, count:si.count });
        links.push([famX, fy, si.sx, si.y, fam]);        // family -> subgenre
      }
      row += 0.9;                                        // gap between families
    }
    const off = row / 2;                                 // centre vertically
    for (const nd of nodes) nd.y -= off;
    for (const l of links){ l[1] -= (l[0]===0 ? 0 : off); l[3] -= off; }
    nodes.push({ kind:'root', fam:null, x:0, y:0, count:NODES.length });
    TREE = { nodes, links, rows: row, maxX, rowPx: 0 };
  }
  function fitTree(){
    if (!TREE) return;
    const rows = TREE.rows;
    TREE.rowPx = Math.max(15, (H - 130) / Math.max(1, rows));   // readable row height
    view.zoom = 1; view.panx = 0;
    view.pany = 96 - H/2 + (rows/2) * TREE.rowPx;               // start at the top
  }
  function renderTree(){
    ctx.clearRect(0,0,W,H); ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H);
    if (!TREE) return;
    if (!TREE.rowPx) fitTree();
    const cx = W/2 + view.panx, cy = H/2 + view.pany;
    const spanX = TREE.maxX || 1;
    const SPX = (W * 0.66) / spanX * view.zoom;
    const SX = wx => cx + (wx - spanX/2) * SPX;
    const SY = wy => cy + wy * TREE.rowPx * view.zoom;
    const show = fam => (!filterFam || !fam || fam === filterFam);
    // links (curved, coloured by family)
    ctx.lineWidth = 1.3;
    for (const l of TREE.links){
      if (!show(l[4])) continue;
      const x1=SX(l[0]), y1=SY(l[1]), x2=SX(l[2]), y2=SY(l[3]), mx=(x1+x2)/2;
      ctx.strokeStyle = `hsla(${hueOf(l[4])} 48% 55% / 0.4)`;
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.bezierCurveTo(mx,y1,mx,y2,x2,y2); ctx.stroke();
    }
    // nodes + labels
    proj.clear(); treeHits = []; famLabelHits = []; styleLabelHits = [];
    ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
    for (const nd of TREE.nodes){
      if (!show(nd.fam)) continue;
      const sx = SX(nd.x), sy = SY(nd.y);
      if (nd.kind === 'root'){
        ctx.beginPath(); ctx.arc(sx, sy, 5, 0, 6.2832);
        ctx.fillStyle = 'rgba(200,210,225,0.85)'; ctx.fill();
        continue;
      }
      const isFam = nd.kind === 'fam';
      const r = isFam ? 6 + Math.min(12, Math.sqrt(nd.count)) : 3.5 + Math.min(8, Math.sqrt(nd.count)*0.9);
      treeHits.push({ node: nd, sx, sy, r });
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, 6.2832);
      if (isFam){ ctx.fillStyle = famCss(nd.fam); }
      else { const sh = styleShade(nd.fam, nd.label);   // subgenre = shade of family
        ctx.fillStyle = `hsl(${sh.h} ${clamp(sh.s-4,42,80)}% ${clamp(56+sh.dl,44,66)}%)`; }
      ctx.fill();
      // labels honour the label-options panel (hide / isolate / colour / counts / size / opacity)
      const showLabel = (isFam ? LBL.showFam : LBL.showSub)
        && !(LBL.onlyFam && nd.fam !== LBL.onlyFam);
      if (showLabel){
        ctx.textAlign = isFam ? 'right' : 'left';   // fam labels left, sub labels right
        const lx = isFam ? sx - r - 6 : sx + r + 6;
        const hot = nd === hoverGenre;
        const label = (hot || LBL.counts) ? `${nd.label} ${nd.count}` : nd.label;   // count on hover, or always if set
        const fsz = Math.round((isFam ? 15 : 11) * LBL.size);
        ctx.font = isFam ? `800 ${fsz}px Syne, sans-serif` : `500 ${fsz}px 'JetBrains Mono', monospace`;
        ctx.globalAlpha = LBL.opacity;
        ctx.lineWidth = 3.5;
        ctx.strokeStyle = LBL.colorFam ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.92)';
        ctx.strokeText(label, lx, sy);
        if (hot) ctx.fillStyle = '#ffffff';
        else if (isFam) ctx.fillStyle = LBL.colorFam ? famCss(nd.fam) : '#e9eef7';
        else { const sh = styleShade(nd.fam, nd.label);
          ctx.fillStyle = LBL.colorFam ? `hsl(${sh.h} ${clamp(sh.s,45,85)}% 72%)` : '#aeb8ca'; }
        ctx.fillText(label, lx, sy);
        ctx.globalAlpha = 1;
      }
    }
  }

  /* ---- tree: sample a track from a branch --------------------------- */
  const treeCardEl = document.getElementById('tree-card');
  let treeCardNode = null;                 // the branch the card is showing

  function closeTreeCard(){
    if (treeCardEl) treeCardEl.hidden = true;
    treeCardNode = null;
    treeCardTrack = null;
    clearPreview();
  }

  /* Tracks under a tree node: everything in the family for a family node, or
     just that subgenre for a leaf. Uses the same parent resolution buildTree()
     applied, so the card can never show a track the branch does not contain. */
  function treeMembers(nd){
    if (!nd) return [];
    if (nd.kind === 'fam') return NODES.filter(n => (n.treeFam || n.fam) === nd.fam);
    return NODES.filter(n =>
      (n.treeFam || n.fam) === nd.fam && (n.style || n.fam) === nd.label);
  }

  let treeCardTrack = null;                // the track the card is showing

  function rerollTreeCard(){
    if (!treeCardNode) return;
    const members = treeMembers(treeCardNode);
    if (!members.length) return;
    const others = (members.length > 1 && treeCardTrack)
      ? members.filter(m => m.hash !== treeCardTrack.hash) : members;
    renderTreeCard(treeCardNode, others[Math.floor(Math.random() * others.length)]);
  }

  function renderTreeCard(nd, pick){
    if (!treeCardEl) return;
    const members = treeMembers(nd);
    if (!members.length){ closeTreeCard(); return; }
    const n = pick || members[Math.floor(Math.random() * members.length)];
    treeCardNode = nd;
    treeCardTrack = n;
    const sh = nd.kind === 'fam' ? null : styleShade(nd.fam, nd.label);
    const col = nd.kind === 'fam' ? famCss(nd.fam)
      : `hsl(${sh.h} ${clamp(sh.s, 45, 85)}% 62%)`;
    const bits = [];
    if (n.bpm) bits.push(Math.round(n.bpm) + ' bpm');
    if (keyText(n)) bits.push(escapeHtml(keyText(n)));
    if (n.duration) bits.push(fmtTime(n.duration));
    treeCardEl.innerHTML =
      `<div class="tc-head" style="border-color:${col}">
         <span class="tc-branch" style="color:${col}">${escapeHtml(nd.label)}</span>
         <span class="tc-n">${members.length} track${members.length === 1 ? '' : 's'}</span>
         <button class="tc-x" title="close">&#10005;</button>
       </div>
       <div class="tc-body">
         <div class="tc-title">${escapeHtml(n.artist ? stripArtist(n.title, n.artist) : n.title)}</div>
         ${artistsOf(n).length ? `<div class="tc-artist">${escapeHtml(artistsOf(n).join(' · '))}</div>` : ''}
         <div class="tc-meta">${bits.join(' · ')}</div>
       </div>
       <div class="tc-acts">
         ${n.a ? `<button class="tc-play" title="hear a few seconds">&#9654; sample</button>` : ''}
         <button class="tc-more" title="another track from this branch">&#8635; another</button>
         <button class="tc-open" title="find this track on the map">&#10038; show on map</button>
       </div>`;
    treeCardEl.hidden = false;

    treeCardEl.querySelector('.tc-x').onclick = closeTreeCard;
    // Never hands back the track already showing -- "another" that returns the
    // same one reads as a broken button.
    treeCardEl.querySelector('.tc-more').onclick = rerollTreeCard;
    treeCardEl.querySelector('.tc-open').onclick = () => {
      closeTreeCard();
      mapMode = 'regions';
      modeEl && modeEl.querySelectorAll('.mm')
        .forEach(m => m.classList.toggle('active', m.dataset.mode === 'regions'));
      syncModeControls();
      layout(); fitView();
      selectNode(n.hash);
    };
    const play = treeCardEl.querySelector('.tc-play');
    if (play) play.onclick = () => previewTrack(n);
  }

  /* ---- canvas sizing ----------------------------------------------- */
  function resize(){
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = stage.clientWidth; H = stage.clientHeight;
    canvas.width = Math.round(W*DPR); canvas.height = Math.round(H*DPR);
    canvas.style.width = W+'px'; canvas.style.height = H+'px';
    ctx.setTransform(DPR,0,0,DPR,0,0);
  }

  /* ---- render one frame -------------------------------------------- */
  function frame(now){
    if (!running) return;
    const t = now/1000;
    if (anim){
      const p = Math.min(1,(now-anim.t0)/anim.dur), e = p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2;
      rot.x = anim.f.rx + (anim.t.rx-anim.f.rx)*e;
      rot.y = anim.f.ry + (anim.t.ry-anim.f.ry)*e;
      view.zoom = anim.f.z + (anim.t.z-anim.f.z)*e;
      view.panx = anim.f.px + (anim.t.px-anim.f.px)*e;
      view.pany = anim.f.py + (anim.t.py-anim.f.py)*e;
      if (p>=1) anim = null;
    }
    if (mapMode === 'tree'){ renderTree(); rafId = requestAnimationFrame(frame); return; }
    // Solar bodies actually move: re-place every orbit before projecting. Tied
    // to the orbit-speed slider so "pause" stops the system, not just the camera.
    /* The galaxies turn. Tied to the same orbit-speed slider and pause button as
       Solar's bodies, so one control stops all the motion on the map. Skipped
       while dragging, or the sky would slide out from under the cursor. */
    if (mapMode === 'universe' && spinSpeed > 0 && !dragging){
      // Scaled by the slider the same way Solar scales its orbits, so the
      // control sets the rate rather than just switching the motion on.
      const gt = t * (spinSpeed / 0.0006);
      // Remembered, so that pausing leaves the gas exactly where the stars
      // stopped rather than snapping it back to where they started.
      lastGt = gt;
      for (const n of NODES) uniPlaceAt(n, gt);
    }
    if (mapMode === 'solar' && spinSpeed > 0 && !dragging){
      const st = t * (spinSpeed / 0.0006) * 0.06;
      for (const n of NODES) if (n.orb) solarPlace(n, st);
    }
    /* The camera drifts -- except where the scene moves on its own. In Solar the
       bodies orbit and in the Universe the galaxies turn, and spinning the
       camera as well gives two unrelated motions at once: you cannot tell what
       is the sky moving and what is you moving, which is worse than either. */
    if (spinSpeed > 0 && !anim && !dragging
        && mapMode !== 'solar' && mapMode !== 'universe') rot.y += spinSpeed;
    // Orbit centre (eased): a clicked genre's centroid, else the selected track,
    // else the cloud's centre of mass -- plus wherever you have panned from
    // there. So clicking a genre orbits AROUND that cluster, letting go of
    // everything falls back to orbiting the busiest part of the map rather than
    // an arbitrary origin that may hold nothing, and a pan re-aims the camera
    // instead of just sliding the picture.
    const sel = selHash ? byHash.get(selHash) : null;
    const tx = (famPivot ? famPivot.x : (sel ? sel.x3 : BARY.x)) + panOff.x;
    const ty = (famPivot ? famPivot.y : (sel ? sel.y3 : BARY.y)) + panOff.y;
    const tz = (famPivot ? famPivot.z : (sel ? sel.z3 : BARY.z)) + panOff.z;
    // Eased, so a new selection glides -- but 1:1 while a drag is in progress:
    // panning moves this target, and easing a pan makes the map rubber-band
    // behind the cursor instead of sticking to it.
    const ease = dragging ? 1 : 0.12;
    pivot.x += (tx - pivot.x) * ease;
    pivot.y += (ty - pivot.y) * ease;
    pivot.z += (tz - pivot.z) * ease;
    const cy=Math.cos(rot.y), sy=Math.sin(rot.y), cx=Math.cos(rot.x), sx=Math.sin(rot.x);
    const DISP = Math.min(W,H)*0.40*view.zoom;
    const cxp = W/2 + view.panx, cyp = H/2 + view.pany;

    // project every node
    proj.clear();
    // Reset the label hit-boxes too. renderTree() cleared these but frame() did
    // not, so in the 3-D modes they accumulated one entry per label PER FRAME --
    // an unbounded array at 60fps, and every click tested against thousands of
    // stale boxes from earlier camera positions.
    famLabelHits = []; styleLabelHits = [];
    // How many nodes each group / subgenre actually has ON SCREEN this frame.
    // Labels are gated on these so a filter that hides a genre hides its label
    // too, instead of leaving a name floating over nothing.
    const visFam = {}, visSub = {};
    const order = [];
    for (const n of NODES){
      if (!passes(n)) continue;                         // genre / flag / facet filters
      const ax = n.x3-pivot.x, ay = n.y3-pivot.y, az = n.z3-pivot.z;
      const x =  ax*cy + az*sy;
      const z = -ax*sy + az*cy;
      const y2 = ay*cx - z*sx;
      const z2 = ay*sx + z*cx;              // depth: bigger = nearer
      const dist = CAM - z2;
      if (dist < 0.15) continue;            // clipped behind the camera
      const persp = CAM / dist;
      const sxp = cxp + x*persp*DISP;
      const syp = cyp + y2*persp*DISP;
      // Every dot the same size and the same brightness at every depth: the
      // layout comes from the 3-D positions (that is what the clustering
      // means), but the depth *cues* were dropped with the sphere renderer --
      // a flat map is the one that is readable for picking. `depth` is still
      // carried on the projection because the rings and labels fade by it.
      const depth = 1;
      const r = clamp(4.2*Math.sqrt(view.zoom)*ratingBoost(n), 1.2, 46);
      // Cull anything whose glow cannot reach the viewport. At high zoom most
      // of the library sits off-screen, and blitting it was pure waste.
      const reach = r * GLOW_SCALE + 2;
      if (sxp < -reach || sxp > W + reach || syp < -reach || syp > H + reach) continue;
      visFam[n.grp] = (visFam[n.grp] || 0) + 1;
      visSub[n.sk] = (visSub[n.sk] || 0) + 1;
      proj.set(n.hash, { sx:sxp, sy:syp, z:z2, r, depth, node:n });
      order.push(n.hash);
    }
    order.sort((a,b)=> proj.get(a).z - proj.get(b).z);   // far -> near

    ctx.clearRect(0,0,W,H);
    ctx.fillStyle = '#000'; ctx.fillRect(0,0,W,H);

    // edges (unless hidden; selection's own web always shows)
    //
    // Never in solar: there the layout is orbital, so a similarity line between
    // two tracks cuts straight across the rings and carries no meaning in that
    // geometry -- it just reads as a scratch on the lens. The selection's own
    // web is still worth seeing, so that stays.
    if ((edgesOn && mapMode !== 'solar') || selHash){
      for (const ed of EDGES){
        const a = proj.get(ed.a), b = proj.get(ed.b);
        if (!a || !b) continue;
        const hot = selHash && (ed.a===selHash||ed.b===selHash);
        // hidden (or solar): only the selection's own web
        if ((!edgesOn || mapMode === 'solar') && !hot) continue;
        /* In the Universe, only links INSIDE a galaxy.
           A similarity line between two galaxies is true, but drawn across the
           gap between them it is also the single thing stopping the sky reading
           as a sky: a few thousand pale threads over the empty space that is
           supposed to separate one island from the next. Inside a galaxy the
           same lines do the opposite -- they trace its structure and hold it
           together as one object. The selection's own web still crosses freely,
           because "what else sounds like this" is exactly a question about
           somewhere else. */
        if (mapMode === 'universe' && !hot && a.node.grp !== b.node.grp) continue;
        // brightness + thickness scale with how closely the two tracks match
        const s = clamp(((ed.sim ?? 0.75) - 0.6) / 0.4, 0, 1);
        let op, lw;
        if (selHash){ op = hot ? 0.9 : 0.05; lw = hot ? 1.8 : 1; }
        else {
          // Fade the web out as you zoom in. The links describe STRUCTURE --
          // which is what you want when the whole library is in frame -- but
          // once you are down among individual tracks they are just thousands
          // of bright lines drawn over the thing you zoomed in to look at.
          // Full strength at the fit zoom, gone by ~3x in -- past that the
          // selection's own web (which always draws) is the useful one.
          const zfade = clamp(1.3 - view.zoom * 0.42, 0, 1);
          op = (0.14 + 0.34*s) * (0.55 + 0.45*Math.min(a.depth,b.depth)) * zfade;
          lw = 0.8 + 1.4*s;
        }
        if (op < 0.02) continue;
        ctx.lineWidth = lw * LBL.linkWidth;
        ctx.strokeStyle = hot ? `rgba(86,180,233,${op})` : `rgba(150,172,208,${op})`;
        ctx.beginPath(); ctx.moveTo(a.sx,a.sy); ctx.lineTo(b.sx,b.sy); ctx.stroke();
      }
    }

    // nodes far -> near (drawn BEFORE labels so the text stays on top / legible)
    const selNode = selHash ? byHash.get(selHash) : null;
    const harmonicOn = harmonic && selNode;

    /* The gas, first of all, under every star and every line.

       One blob per system, at the system's own size, in the system's own colour.
       Skipped when the glow is off -- that switch means "no light bleeding into
       the black", and gas is nothing but light bleeding into the black. */
    if (mapMode === 'universe' && LBL.shine > 0 && GALAXIES){
      const wp = { x:0, y:0, z:0 };
      ctx.globalCompositeOperation = 'lighter';
      const gt = spinSpeed > 0 && !dragging ? t * (spinSpeed / 0.0006) : (lastGt || 0);
      for (const gname in GALAXIES){
        const g = GALAXIES[gname];
        if (!g.systems) continue;
        for (const k in g.systems){
          const sys = g.systems[k];
          systemWorld(g, sys, gt, wp);
          const ax = wp.x-pivot.x, ay = wp.y-pivot.y, az = wp.z-pivot.z;
          const xx = ax*cy + az*sy, zz = -ax*sy + az*cy;
          const y2 = ay*cx - zz*sx, z2 = ay*sx + zz*cx;
          const dist = CAM - z2;
          if (dist < 0.15) continue;
          const persp = CAM / dist;
          const sxp = cxp + xx*persp*DISP, syp = cyp + y2*persp*DISP;
          // Generous: gas reaches well past the stars it surrounds.
          const gr = sys.sr * g.radius * persp * DISP * 2.6 + 14;
          if (sxp < -gr || sxp > W + gr || syp < -gr || syp > H + gr) continue;
          // Bigger systems hold more of it, and depth fades it like everything
          // else. Capped low: dozens of these overlap inside one galaxy.
          const depth = clamp((z2+1.15)/2.3, 0, 1);
          ctx.globalAlpha = clamp(0.14 + 0.34 * Math.sqrt(sys.n / 260), 0.10, 0.62)
                          * (0.45 + 0.55*depth) * LBL.opacity;
          ctx.drawImage(nebulaSprite(sys.hue, sys.sat), sxp-gr, syp-gr, gr*2, gr*2);
        }
      }
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
    }

    /* How bright one star is this frame, and whether it is a harmonic match.

       Baseline shimmer, plus a much stronger pulse for tracks matching the chip
       currently under the cursor -- the "what would this filter show me"
       preview. Phase-offset per node so they sparkle rather than strobe in
       unison, which reads as a glitch instead of a highlight. Three twinkle
       modes; 'flicker' beats two detuned sines together so the field
       scintillates irregularly instead of every star breathing on one cycle.

       Both passes call this. It used to be inline in the star loop, which meant
       the corona pass carried a second copy that had to be kept in step. */
    const starLight = (p, n) => {
      const lit = HL && nodeHas(n, HL.kind, HL.value);
      /* The hover preview -- "which tracks would this chip show me" -- is a
         0..1 pulse rather than a brightness multiplier, because it drives three
         things at once: the star flashes white at the peak, and fades toward
         transparent at the trough. Colour alone was not enough to find a
         scattered handful of matches in three thousand stars; something that
         goes white and then nearly vanishes is visible from across the map even
         where the matches are a single dot in a crowded cluster. */
      const flash = lit ? 0.5 + 0.5*Math.sin(t*7 + n.ph*3) : 0;
      const tw = lit
        ? 0.55 + 1.45*flash
        : LBL.twinkle === 'off' ? 1
        : LBL.twinkle === 'flicker'
          ? 0.70 + 0.30*Math.sin(t*6.1 + n.ph*5.3) + 0.16*Math.sin(t*2.3 + n.ph*11.7)
          : 0.9 + 0.1*Math.sin(t*1.6 + n.ph);
      // A lit star is allowed to go properly see-through at the bottom of its
      // pulse; everything else keeps the old floor so the field never gutters.
      const bright = clamp(((26 + 44*p.depth) * tw) / 70, lit ? 0.06 : 0.16, 1);
      let compatible = false, dim = 1;
      if (harmonicOn && n.hash !== selHash){    // harmonic mixing: mute non-matches
        compatible = keyCompatible(selNode.camelot, n.camelot) && bpmCompatible(selNode.bpm, n.bpm);
        dim = compatible ? 1 : 0.1;
      }
      return { alpha: bright * dim, compatible, lit, flash };
    };
    /* Every corona first, in one additive pass.
       Each star used to flip the composite operation to 'lighter' for its own
       halo and back again for its body -- two context-state changes per star,
       so a 3,000-star frame ended the draw batch 6,000 times. Hoisting the mode
       out of the loop leaves the same blits and the same alphas with two state
       changes for the whole frame.
       It also fixes a layering accident: a near star's halo used to be painted
       over a far star's body. Halos belong under bodies, which is what the
       original comment said it wanted. */
    if (LBL.shine > 0){
      ctx.globalCompositeOperation = 'lighter';
      for (const h of order){
        const p = proj.get(h);
        // Kept on the projection entry: the star loop below needs the same two
        // numbers, and deriving them twice a frame for every star is the kind of
        // small waste this pass exists to remove.
        p.lit = starLight(p, p.node);
        // A previewed star's halo swells with the same pulse, so the flash
        // carries further than the dot itself in a crowded cluster.
        drawCorona(p, p.node, LBL.shine * (1 + 2.2 * p.lit.flash), p.lit.alpha);
      }
      ctx.globalCompositeOperation = 'source-over';
    }

    for (const h of order){
      const p = proj.get(h), n = p.node;
      // Brightness, as alpha. This used to be baked into the sprite's lightness,
      // which is what made the cache key churn every frame.
      const { alpha, compatible, lit, flash } = p.lit || starLight(p, n);
      ctx.globalAlpha = alpha;
      if (!Number.isFinite(n.hue)) warnShade('node', n);
      // A plain disc over the corona already laid down above. The disc is what
      // keeps a dense cluster legible -- it is opaque, so neighbours occlude
      // instead of summing -- and the halo under it is what makes the field
      // read as a sky rather than dots printed on black. Twinkle is already in
      // globalAlpha.
      ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r, 0, 6.2832);
      ctx.fillStyle = discCss(n);
      ctx.fill();
      if (lit && flash > 0.02){
        /* White over the body, additively, so the star washes out to white at
           the top of the pulse instead of merely getting brighter in its own
           colour -- which on a map where colour IS the genre reads as "slightly
           more House", not as "this one". Drawn at the body's size so it is the
           star that flashes and not a blob around it. */
        ctx.globalCompositeOperation = 'lighter';
        ctx.globalAlpha = flash * 0.85;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r, 0, 6.2832);
        ctx.fillStyle = '#ffffff'; ctx.fill();
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = alpha;
      }
      if (compatible){                          // key + BPM compatible -> teal ring
        ctx.globalAlpha = 0.5 + 0.5*p.depth;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r+2.5, 0, 6.2832);
        ctx.lineWidth = 1.6; ctx.strokeStyle = 'rgba(80,224,180,0.95)'; ctx.stroke();
      }
      if (n.flag){                              // likely misread -> amber ring
        ctx.globalAlpha = 0.5 + 0.5*p.depth;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r+2.5, 0, 6.2832);
        ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(255,176,59,0.95)'; ctx.stroke();
      }
      if (h === selHash){
        ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r+3.5, 0, 6.2832);
        ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;

    // Labels with semantic zoom (LOD): family names when zoomed out, subgenre
    // names fading in as you zoom in -- in BOTH regions and galaxy now.
    // This frame's camera, as a function: used by every label and by Solar's
    // chrome below.
    const projPt = projPtFactory(cy,sy,cx,sx,cxp,cyp,DISP);
    if (mapMode === 'solar'){
      // Solar draws its own sun, orbits and ring labels, and then stops. The
      // genre-label section below is not merely redundant here -- it iterates
      // FAMS against CENTROIDS, which solarLayout() empties, so entering it
      // threw on undefined and took the whole render loop down with it.
      drawSolarChrome(t, projPt);
      rafId = requestAnimationFrame(frame);
      return;
    }
    // One switch for every label the canvas draws. Distinct from unticking
    // genre and subgenre separately: this also drops leader lines and solar
    // ring labels, leaving nothing but the stars.
    if (LBL.hideText){ rafId = requestAnimationFrame(frame); return; }
    ctx.textAlign='center'; ctx.textBaseline='middle';
    // subgenre detail ramps in with zoom (sooner than before), then is gated
    // per-family by how centred/near that cluster is -- see famFocus below. The
    // proximity gate keeps galaxy's tight ball from lighting up every subgenre at
    // once: only the clusters you've zoomed toward reveal their subgenre names.
    const zoomLod = clamp((view.zoom - 0.8) / (1.7 - 0.8), 0, 1);
    // labels get a halo (stroke) so they stay legible over dense clusters. With
    // colour-matching on, the halo flips to white so the coloured text pops.
    ctx.lineJoin = 'round';
    const halo = LBL.colorFam ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.9)';
    // Depth cues on text, so distant labels recede the way distant objects do.
    // Both are floored: a far label gets faint and small, never invisible and
    // never unreadable -- you still need to know what's back there.
    const DEPTH_MIN_ALPHA = 0.34;
    const DEPTH_MIN_SCALE = 0.62;
    const depthAlpha = d => DEPTH_MIN_ALPHA + (1 - DEPTH_MIN_ALPHA) * clamp(d, 0, 1);
    const depthScale = d => DEPTH_MIN_SCALE + (1 - DEPTH_MIN_SCALE) * clamp(d, 0, 1);
    const drawLabel = (text, p, fs, fill, depth = 1) => {
      // globalAlpha multiplies whatever alpha the fill already carries, so the
      // existing focus/LOD fades keep working and this composes on top.
      const prev = ctx.globalAlpha;
      ctx.globalAlpha = prev * depthAlpha(depth);
      ctx.font = fs;
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = halo;
      ctx.strokeText(text, p.sx, p.sy);
      ctx.fillStyle = fill;
      ctx.fillText(text, p.sx, p.sy);
      ctx.globalAlpha = prev;
    };
    // Per-family "focus": high when that cluster is near the screen centre AND
    // you're zoomed in on it. A focused family fades its own big label and shows
    // its subgenre labels; families off to the side stay coarse (family label
    // only). So being deep in one cluster reveals ITS subgenres without lighting
    // up subgenres across the whole map -- and other clusters stay identifiable.
    const focusR = 0.40 * Math.min(W, H);
    const famFocus = {};
    for (const f of FAMS){
      // A group with no centroid is not drawable. FAMS and CENTROIDS are built
      // in separate steps and a mode that clears one but not the other used to
      // throw here -- and a throw inside requestAnimationFrame is fatal, since
      // nothing re-arms the callback.
      if (!CENTROIDS[f]) continue;
      const cp = projPt(CENTROIDS[f]);
      const prox = cp.persp > 0
        ? clamp(1 - Math.hypot(cp.sx - cxp, cp.sy - cyp) / focusR, 0, 1) : 0;
      famFocus[f] = zoomLod * prox;
    }

    // family labels: measure, then relax apart in 2D (box separation) so they
    // fan out around the cluster -- even a tight galaxy ball -- each tied back
    // to its true centroid by a colour-coded leader line.
    const fl = [];
    // The biggest galaxy on the map, which every label is sized against.
    let famMax = 1;
    for (const f of FAMS) famMax = Math.max(famMax, (CENTROIDS[f] && CENTROIDS[f].n) || 0);
    /* Declutter: keep only the N biggest genre labels.

       "All" was a sane default at five families and is not at seventy -- naming
       every galaxy at once means naming none of them, because no single one can
       be read. So the Universe caps itself unless you have said otherwise; the
       rest of the names are still one hover or one zoom away.

       Decided up front, on the candidates, so the font is set and the text
       measured only for the labels that will be drawn -- at seventy galaxies
       that was four measureText calls per frame for every one kept. */
    const famCap = LBL.maxFam > 0 ? LBL.maxFam
                 : (mapMode === 'universe' ? 16 : 0);
    let cands = [];
    for (const f of FAMS){
      if (!LBL.showFam) break;                          // family labels hidden
      if (LBL.onlyFam && f !== LBL.onlyFam) continue;   // isolate one genre's label
      if (filterFam && f !== filterFam) continue;
      // No stars from this genre on screen -> no label. Chips, facet filters
      // and culling all feed this, so the labels always describe what is
      // actually drawn.
      if (!visFam[f]) continue;
      cands.push(f);
    }
    if (famCap > 0 && cands.length > famCap){
      cands.sort((a,b) => (CENTROIDS[b].n||0) - (CENTROIDS[a].n||0));
      cands.length = famCap;
    }
    for (const f of cands){
      const p = projPt(CENTROIDS[f]);
      if (p.persp <= 0) continue;
      const depth = clamp((p.z2+1.15)/2.3, 0, 1);
      const alpha = (0.52 + 0.32*depth) * (1 - 0.9*(famFocus[f]||0)) * LBL.opacity;   // fade when focused
      if (alpha < 0.04) continue;
      /* Label size follows the galaxy's mass, the same way the galaxy's own
         radius does.

         This used to be `min(21, 13 + n*0.3)`, which was written when the map
         had five families in it and every one of them was big: at five tracks
         that is 14.5px and at fifteen hundred it is 21px, so everything came out
         essentially the same size. With a galaxy per genre there are seventy of
         them, most tiny, and the sky turned into a wall of same-sized words with
         the stars somewhere behind it.

         Against the biggest galaxy's count, so it is a hierarchy of what is
         actually there rather than an absolute scale that stops meaning anything
         on a bigger library. sqrt for the same reason the galaxies use it: a
         genre with a hundred times the tracks is ten times the object, not a
         hundred. */
      const share = Math.sqrt((CENTROIDS[f].n || 1) / famMax);
      const fs = (9 + 12 * share) * clamp(p.persp, 0.9, 1.25) * LBL.size;
      const text = (LBL.counts ? `${f} ${CENTROIDS[f].n}` : f).toUpperCase();
      ctx.font = `800 ${fs}px Syne, sans-serif`;
      fl.push({ f, text, ax:p.sx, ay:p.sy, lx:p.sx, ly:p.sy,
                hw:ctx.measureText(text).width/2 + 5, hh:fs*0.62, fs, alpha, depth });
    }
    let cx0 = 0, cy0 = 0;
    for (const l of fl){ cx0 += l.ax; cy0 += l.ay; }
    if (fl.length){
      cx0 /= fl.length; cy0 /= fl.length;
      let spread = 0;                                   // how clustered are the anchors?
      for (const l of fl) spread += Math.hypot(l.lx-cx0, l.ly-cy0);
      spread /= fl.length;
      /* Ring the labels only when their anchors are genuinely on top of one
         another. The threshold was 90px, from when the Universe put every
         galaxy in one ball and a group centroid really did carry no direction.
         Now the galaxies are separated in space, so their anchors point at
         something -- and at 90 this still fired, flinging every name out to the
         rim where it named nothing in particular. Below about half a label's
         width the anchors are useless and the ring is the honest answer; above
         it, the overlap relaxation below keeps labels on their galaxies. */
      if (spread < 45){
        // tight ball (galaxy): centroid *direction* is basically noise, so ring
        // the labels evenly by angle around the cluster, each tied back by a
        // leader line. Centre the ring on the ACTUAL node cloud (its visual mass)
        // -- not the family-centroid mean, which the dense clusters skew off to
        // one side -- and size the radius to the ball's on-screen extent (+ a
        // generous margin) so the labels clear the cloud all round, not just on
        // one side, and sit well clear when zoomed out.
        let bx=0, by=0, bn=0;
        for (const [, pp] of proj){ bx+=pp.sx; by+=pp.sy; bn++; }
        if (bn){ cx0 = bx/bn; cy0 = by/bn; }
        let ballR = 0;
        { const ds = []; for (const [, pp] of proj) ds.push(Math.hypot(pp.sx-cx0, pp.sy-cy0));
          ballR = pctl(ds, 0.92); }
        const arr = fl.slice().sort((a,b) =>
          Math.atan2(a.ay-cy0, a.ax-cx0) - Math.atan2(b.ay-cy0, b.ax-cx0));
        const N = arr.length;
        // push the ring out toward the viewport edges -- there's usually far more
        // empty space out there than the ball needs -- but never less than a clean
        // clearance of the ball. Labels are clamped on-screen after relaxation.
        const availX = Math.min(cx0, W - cx0), availY = Math.min(cy0, H - cy0);
        const Rx = Math.max(210, ballR*1.32 + 90, N*8, availX * 0.82);
        const Ry = Math.max(180, ballR*1.22 + 78, availY * 0.82);
        for (let i=0; i<N; i++){
          const ang = (i/N)*6.2832 - 1.5708;            // start at top, go clockwise
          arr[i].lx = cx0 + Math.cos(ang)*Rx;
          arr[i].ly = cy0 + Math.sin(ang)*Ry;
        }
      } else {
        // spread map (regions): nudge a hair so labels stay on their centroids.
        for (const l of fl){
          let dx = l.lx-cx0, dy = l.ly-cy0, d = Math.hypot(dx, dy);
          if (d < 1){ const a = (hueOf(l.f) % 360) * Math.PI/180; dx = Math.cos(a); dy = Math.sin(a); d = 1; }
          l.lx += dx/d * 3; l.ly += dy/d * 3;
        }
      }
      // user "distance from the middle": scale every label's offset from the
      // cloud centre. >1 pushes labels out toward the edges, <1 pulls them in.
      if (LBL.dist !== 1){
        for (const l of fl){
          l.lx = cx0 + (l.lx - cx0) * LBL.dist;
          l.ly = cy0 + (l.ly - cy0) * LBL.dist;
        }
      }
    }
    /* 2-D AABB min-penetration relax, with the viewport bounds solved as part
       of the SAME loop rather than clamped once at the end.

       Clamping afterwards was the bug behind labels like "INDUSTRIALEAKBEAT":
       separation would push two labels below the bottom edge, the final clamp
       pinned both to the same y, and nothing ran again to pull them apart. Now
       a label driven out of bounds is snapped back and then re-separated on the
       next pass, so the two constraints converge together. */
    for (let pass=0; pass<90; pass++){
      let moved = false;
      for (let i=0; i<fl.length; i++) for (let j=i+1; j<fl.length; j++){
        const a=fl[i], b=fl[j];
        const dx=b.lx-a.lx, dy=b.ly-a.ly;
        const ox=(a.hw+b.hw)-Math.abs(dx), oy=(a.hh+b.hh+2)-Math.abs(dy);
        if (ox>0 && oy>0){                              // boxes overlap -> push on shallow axis
          if (ox < oy){ const p=(ox/2)*(dx>=0?1:-1); a.lx-=p; b.lx+=p; }
          else        { const p=(oy/2)*(dy>=0?1:-1); a.ly-=p; b.ly+=p; }
          moved = true;
        }
      }
      for (const l of fl){                              // keep every label on-screen
        const nx = clamp(l.lx, l.hw + 6, W - l.hw - 6);
        const ny = clamp(l.ly, l.hh + 6, H - l.hh - 6);
        if (nx !== l.lx || ny !== l.ly){ l.lx = nx; l.ly = ny; moved = true; }
      }
      if (!moved) break;
    }
    ctx.textAlign = 'center';
    // Boxes already occupied on screen. Subgenre labels test against this so
    // they never land on top of a genre label -- which is how "Metal" and
    // "Alternative Rock" rendered as "MEALTERNATIVE ROCK".
    const placed = [];
    for (const l of fl){
      // Leader lines are off by default now. With a dozen genres they form a
      // starburst across the middle of the map that competes with the data --
      // the thing this view exists to show.
      if (LBL.leaders && Math.hypot(l.lx-l.ax, l.ly-l.ay) > 4){
        ctx.save();
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 4]);                       // dashed reads as an
        ctx.strokeStyle = `hsla(${famHue(l.f)} 62% 62% / ${clamp(0.42*l.alpha+0.1, 0, 0.5)})`;
        ctx.beginPath(); ctx.moveTo(l.ax, l.ay); ctx.lineTo(l.lx, l.ly); ctx.stroke();
        ctx.restore();
      }
      if (LBL.labelStyle === 'pill') drawPill(l.lx, l.ly, l.hw, l.hh, l.alpha);
      const fill = LBL.colorFam                         // colour-match the genre?
        ? `hsla(${famHue(l.f)} 72% 70% / ${l.alpha})`
        : `rgba(233,238,247,${l.alpha})`;
      const lfs = l.fs * depthScale(l.depth);
      drawLabel(l.text, {sx:l.lx, sy:l.ly}, `800 ${lfs}px Syne, sans-serif`, fill, l.depth);
      famLabelHits.push({ f:l.f, cx:l.lx, cy:l.ly, hw:l.hw, hh:l.hh });   // click -> fly here
      placed.push({ cx:l.lx, cy:l.ly, hw:l.hw, hh:l.hh });
    }
    // subgenre labels -- shown only inside the focused cluster(s), coloured as a
    // shade of the family so they read as "part of" it. Drawn far -> near.
    if (LBL.showSub) {
      const subs = [];
      for (const key in STYLE_CENTROIDS){
        if (filterFam && !key.startsWith(filterFam + '||')) continue;
        if (LBL.onlyFam && !key.startsWith(LBL.onlyFam + '||')) continue;   // isolate one genre
        if (!visSub[key]) continue;                      // nothing of it on screen
        const fam = key.slice(0, key.indexOf('||'));
        // "always show subgenres" (or an isolated genre) bypasses the zoom/focus
        // gate so they stay readable without having to zoom into the cluster.
        const forced = LBL.subAlways || (LBL.onlyFam && fam === LBL.onlyFam)
                       || fam === focusedFam;   // clicked genre -> reveal its subgenres
        let focus = famFocus[fam] || 0;
        if (forced) focus = Math.max(focus, 1);
        if (focus < 0.02) continue;
        const c = STYLE_CENTROIDS[key], p = projPt(c);
        if (p.persp <= 0) continue;
        const depth = clamp((p.z2+1.15)/2.3, 0, 1);
        const a = (0.62 + 0.38*depth) * clamp(focus*1.5, 0, 1) * LBL.opacity;
        if (a < 0.03) continue;
        const sh = styleShade(fam, c.style);
        const fs = Math.min(22, 11 + c.n*0.4) * clamp(p.persp, 0.85, 1.3) * LBL.size;
        const text = (LBL.counts ? `${c.style} ${c.n}` : c.style).toUpperCase();
        ctx.font = `700 ${fs}px 'JetBrains Mono', monospace`;
        subs.push({ p, depth, fam, style: c.style, text, fs, n: c.n,
          hw: ctx.measureText(text).width/2 + 4, hh: fs*0.6,
          // bright, high-lightness tint of the family hue so it reads over the
          // similarly-hued nodes (the dark halo in drawLabel does the rest).
          col: `hsla(${sh.h} ${clamp(sh.s+20, 55, 96)}% ${clamp(82 + sh.dl*0.5, 74, 90)}% / ${a})` });
      }
      // declutter: keep only the N biggest subgenre labels (by track count)
      if (LBL.maxSub > 0 && subs.length > LBL.maxSub){
        subs.sort((x,y) => y.n - x.n); subs.length = LBL.maxSub;
      }
      /* Overlap was the single worst thing about this view: subgenre labels
         were drawn straight at their centroid with no declutter at all, so on a
         dense map they printed through each other and through the genre labels
         -- "Metal" over "Alternative Rock" reading as MEALTERNATIVE ROCK.

         Family labels solve this by relaxing apart, but that is wrong here: a
         subgenre label pushed away from its cluster is pointing at the wrong
         tracks, and there is no leader line tying it back. So instead: take
         them biggest-first and DROP any that would collide with something
         already on screen. Every label that survives is exactly where it
         belongs, and the ones you lose are the smallest -- which are the ones
         you'd have zoomed in to read anyway. */
      subs.sort((x,y) => y.n - x.n);
      const keep = [];
      for (const s of subs){
        const hit = placed.some(q =>
          Math.abs(q.cx - s.p.sx) < (q.hw + s.hw + 2) &&
          Math.abs(q.cy - s.p.sy) < (q.hh + s.hh + 2));
        if (hit) continue;
        placed.push({ cx:s.p.sx, cy:s.p.sy, hw:s.hw, hh:s.hh });
        keep.push(s);
      }
      keep.sort((x,y) => x.depth - y.depth);
      for (const s of keep){
        const sfs = s.fs * depthScale(s.depth);
        if (LBL.labelStyle === 'pill') drawPill(s.p.sx, s.p.sy, s.hw, s.hh, LBL.opacity*0.9);
        drawLabel(s.text, s.p, `700 ${sfs}px 'JetBrains Mono', monospace`, s.col, s.depth);
        styleLabelHits.push({ fam:s.fam, style:s.style, cx:s.p.sx, cy:s.p.sy, hw:s.hw, hh:s.hh });
      }
    }

    rafId = requestAnimationFrame(frame);
  }
  /* A solid rounded plate behind a label. The stroked-outline style keeps text
     legible over a sparse field but turns to mush over a dense cluster, where
     the halo competes with the very stars it sits on; a plate just occludes
     them. Offered as a choice because it costs contrast with the map. */
  function drawPill(cx0, cy0, hw, hh, alpha){
    const x = cx0 - hw - 3, y = cy0 - hh - 2, w = hw*2 + 6, h = hh*2 + 4, r = Math.min(7, h/2);
    ctx.save();
    ctx.globalAlpha = clamp(alpha, 0, 1) * 0.78;
    ctx.fillStyle = 'rgba(8,10,15,0.9)';
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
    else {
      ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.quadraticCurveTo(x+w,y,x+w,y+r);
      ctx.lineTo(x+w,y+h-r); ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
      ctx.lineTo(x+r,y+h); ctx.quadraticCurveTo(x,y+h,x,y+h-r);
      ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y);
    }
    ctx.fill(); ctx.stroke();
    ctx.restore();
  }

  /* frame() builds its projection from locals; solar chrome needs the same
     transform, so hand it over rather than recomputing a second, subtly
     different one. */
  function projPtFactory(cy, sy, cx, sx, cxp, cyp, DISP){
    return c => {
      const ax = c.x-pivot.x, ay = c.y-pivot.y, az = c.z-pivot.z;
      const x = ax*cy + az*sy, z = -ax*sy + az*cy;
      const y2 = ay*cx - z*sx, z2 = ay*sx + z*cx;
      const persp = CAM/(CAM - z2);
      return { sx: cxp + x*persp*DISP, sy: cyp + y2*persp*DISP, z2, persp };
    };
  }

  /* The sun, its orbit rings, and their labels. Drawn before the genre labels
     so text lands on top of the rings, never under them. */
  function drawSolarChrome(t, project){
    if (!SOLAR_RINGS.length) return;
    const c0 = project({x:0, y:0, z:0});
    if (c0.persp > 0){
      // Orbit rings, as projected ellipses. Sampled rather than drawn with
      // ctx.ellipse because the ring is a circle in WORLD space and the camera
      // can be at any orientation -- a screen-space ellipse would only be right
      // when looking straight down the Y axis.
      ctx.save();
      ctx.lineWidth = 1;
      for (const ring of SOLAR_RINGS){
        ctx.strokeStyle = 'rgba(150,172,208,0.18)';
        ctx.beginPath();
        // `pen` tracks whether the previous sample was drawable. Without it, a
        // ring passing behind the camera had its two visible arcs joined by a
        // straight lineTo across the whole viewport.
        let pen = false;
        for (let i=0; i<=64; i++){
          const a = (i/64)*6.2832;
          const q = project({ x:Math.cos(a)*ring.r, y:0, z:Math.sin(a)*ring.r });
          if (q.persp <= 0){ pen = false; continue; }
          if (!pen){ ctx.moveTo(q.sx, q.sy); pen = true; } else ctx.lineTo(q.sx, q.sy);
        }
        ctx.stroke();
      }
      ctx.restore();

      // The sun: the playlist itself, rendered as the one body that emits
      // rather than reflects.
      const pulse = 1 + 0.05*Math.sin(t*1.4);
      const sr = clamp(26 * c0.persp * Math.sqrt(view.zoom) * pulse, 10, 130);
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = 0.55;
      ctx.drawImage(starSprite(44, 92, 8, 'corona'), c0.sx-sr*2.4, c0.sy-sr*2.4, sr*4.8, sr*4.8);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      drawSphere(c0.sx, c0.sy, sr, 46, 95, 74);
      ctx.restore();
    }
    if (LBL.hideText) return;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round'; ctx.lineWidth = 3.5;
    if (c0.persp > 0 && SOLAR_NAME){
      // Above the sun, not on it: printed at the centre it sat over both the
      // sun's own glow and the innermost ring's label.
      const sy0 = c0.sy - clamp(34 * c0.persp * Math.sqrt(view.zoom), 16, 90);
      ctx.font = `800 ${Math.round(17*LBL.size)}px Syne, sans-serif`;
      ctx.strokeStyle = 'rgba(0,0,0,0.92)';
      ctx.strokeText(SOLAR_NAME.toUpperCase(), c0.sx, sy0);
      ctx.fillStyle = '#ffe9b0';
      ctx.fillText(SOLAR_NAME.toUpperCase(), c0.sx, sy0);
    }
    // Ring labels sit at the near edge of each orbit, where there is reliably
    // empty space between one ring and the next.
    ctx.font = `600 ${Math.round(10.5*LBL.size)}px 'JetBrains Mono', monospace`;
    ctx.globalAlpha = LBL.opacity;
    // Labels ride the FRONT of each orbit (+z projects toward the viewer at the
    // default tilt), which is the one place on a ring guaranteed not to be
    // behind the sun. Alternating the vertical offset keeps two adjacent rings
    // from printing their text on the same line when the system is near
    // edge-on.
    SOLAR_RINGS.forEach((ring, i) => {
      const q = project({ x:0, y:0, z:ring.r });
      if (q.persp <= 0) return;
      const text = `${ring.label} · ${ring.n}`;
      const dy = 12 + (i % 2) * 12;
      ctx.strokeStyle = 'rgba(0,0,0,0.92)';
      ctx.strokeText(text, q.sx, q.sy + dy);
      ctx.fillStyle = 'rgba(190,203,226,0.95)';
      ctx.fillText(text, q.sx, q.sy + dy);
    });
    ctx.restore();
  }

  function startLoop(){ if(!running){ running=true; rafId=requestAnimationFrame(frame); } }
  function stopLoop(){ running=false; if(rafId) cancelAnimationFrame(rafId); rafId=null; }

  /* Move the camera sideways by (dx, dy) SCREEN pixels -- the picture follows
     the drag, exactly as a screen-space pan looked.

     In the 3-D modes this walks the orbit centre through the world instead, so
     what you fly away from stays flown away from. The two vectors are the
     projection's own basis read backwards: a world step along `right` moves a
     point right on screen, one along `down` moves it down (both fall out of the
     rot.x / rot.y rotation in frame()). Dividing by DISP converts pixels to
     world units at the pivot's depth -- exact for the plane you are orbiting,
     and off only by perspective for things nearer or further, which is the same
     approximation the old screen pan made for everything.

     Tree is 2-D and has no pivot to move, so it keeps the screen-space pan.

     `snap` moves the eased pivot by the same step, not just its target. A drag
     doesn't need it (frame() eases 1:1 while dragging), but a wheel zoom does:
     the zoom is applied instantly, so if the compensating pan only moved the
     target, the point under the cursor would jump toward the centre and slide
     back over the next twenty frames. */
  function panBy(dx, dy, snap){
    if (mapMode === 'tree'){ view.panx += dx; view.pany += dy; return; }
    const cy=Math.cos(rot.y), sy=Math.sin(rot.y), cx=Math.cos(rot.x), sx=Math.sin(rot.x);
    const s = -1 / (Math.min(W,H) * 0.40 * view.zoom);      // = -1/DISP, see frame()
    const wx = (dx*cy + dy*sy*sx) * s;                      // right=(cy,0,sy)
    const wy = (dy*cx) * s;                                 // down =(sy*sx, cx, -cy*sx)
    const wz = (dx*sy - dy*cy*sx) * s;
    panOff.x += wx; panOff.y += wy; panOff.z += wz;
    if (snap){ pivot.x += wx; pivot.y += wy; pivot.z += wz; }
  }

  /* ---- interaction: orbit / pan / zoom / click --------------------- */
  // left-drag orbits; right / middle / Shift+left-drag pans (translate); wheel
  // zooms toward the cursor. Panning lets you fly through the 3-D scene.
  let dragging=false, panning=false, moved=false, lx=0, ly=0;
  canvas.addEventListener('pointerdown', e => {
    dragging=true; moved=false; lx=e.clientX; ly=e.clientY;
    panning = (e.button===1 || e.button===2 || e.shiftKey);
    canvas.classList.add(panning ? 'panning' : 'grabbing');
    canvas.setPointerCapture(e.pointerId); anim=null;
  });
  canvas.addEventListener('contextmenu', e => e.preventDefault());   // right-drag = pan
  canvas.addEventListener('pointermove', e => {
    if (dragging){
      const dx=e.clientX-lx, dy=e.clientY-ly; lx=e.clientX; ly=e.clientY;
      if (Math.abs(dx)+Math.abs(dy) > 2) moved=true;
      if (mapMode === 'tree' || panning){ panBy(dx, dy); }
      else { rot.y += dx*0.006; rot.x = clamp(rot.x + dy*0.006, -1.3, 1.3); }
      return;
    }
    const rr = canvas.getBoundingClientRect();
    if (mapMode === 'tree'){                 // hover a genre node -> reveal its count
      const mx = e.clientX-rr.left, my = e.clientY-rr.top;
      let hit = null;
      for (const h of treeHits){ if (Math.hypot(mx-h.sx, my-h.sy) <= h.r+6){ hit = h.node; break; } }
      hoverGenre = hit;
      canvas.style.cursor = hit ? 'pointer' : '';
      if (tipEl && !tipEl.hidden) tipEl.hidden = true;
      return;
    }
    // hover: a node -> tooltip; a clickable genre/subgenre label -> pointer cursor
    if (!tipEl) return;
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX-r.left, my = e.clientY-r.top;
    const onLabel = g => Math.abs(mx-g.cx) <= g.hw && Math.abs(my-g.cy) <= g.hh+4;
    const overLabel = styleLabelHits.some(onLabel) || famLabelHits.some(onLabel);
    let best=null, bz=-Infinity;
    for (const [, p] of proj){
      if (Math.hypot(mx-p.sx, my-p.sy) <= p.r+4 && p.z>bz){ bz=p.z; best=p; }
    }
    if (best){
      const n = best.node;
      tipEl.innerHTML = `<b>${escapeHtml(n.title)}</b><span>${escapeHtml(n.style||'?')} · `
        + `${n.bpm?Math.round(n.bpm):'--'} bpm · ${escapeHtml(keyfmt(n))}</span>`;
      tipEl.style.left = Math.min(mx+14, W-220)+'px';
      tipEl.style.top  = (my+14)+'px';
      tipEl.hidden = false;
      canvas.style.cursor = 'pointer';
    } else {
      if (!tipEl.hidden) tipEl.hidden = true;
      canvas.style.cursor = overLabel ? 'pointer' : '';
    }
  });
  canvas.addEventListener('pointerleave', () => { if (tipEl) tipEl.hidden = true; hoverGenre = null; });
  const endDrag = e => { dragging=false; canvas.classList.remove('grabbing','panning');
    try{ canvas.releasePointerCapture(e.pointerId); }catch(_){} };
  canvas.addEventListener('pointerup', e => {
    const wasPanning = panning;
    endDrag(e);
    if (!moved && !wasPanning){                     // treat as click -> hit test
      const r = canvas.getBoundingClientRect();
      const mx = e.clientX-r.left, my = e.clientY-r.top;
      if (mapMode === 'tree'){
        for (const h of treeHits){
          if (Math.hypot(mx-h.sx, my-h.sy) > h.r+6) continue;
          // Clicking the branch already on screen re-rolls it. Re-rendering the
          // same track would look like the click did nothing.
          if (treeCardNode === h.node) rerollTreeCard();
          else renderTreeCard(h.node);
          return;
        }
        closeTreeCard();
        return;
      }
      // a dot under the cursor wins -> select it + open the popup (the precise
      // target; labels overlap dense clusters, so they must NOT pre-empt this).
      let best=null, bz=-Infinity;
      for (const [h,p] of proj){
        if (Math.hypot(mx-p.sx, my-p.sy) <= p.r+5 && p.z>bz){ bz=p.z; best=h; }
      }
      if (best){ selectNode(best); return; }
      // otherwise a subgenre / genre label -> fly to that cluster
      for (const g of styleLabelHits){
        if (Math.abs(mx-g.cx) <= g.hw && Math.abs(my-g.cy) <= g.hh+4){ focusStyle(g.fam, g.style); return; }
      }
      for (const g of famLabelHits){
        if (Math.abs(mx-g.cx) <= g.hw && Math.abs(my-g.cy) <= g.hh+4){ focusFamily(g.f); return; }
      }
      closePopup();
    }
  });
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('wheel', e => {
    e.preventDefault(); anim=null;
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    // The floor was 0.3, which on a sky that now sizes its galaxies by mass was
    // barely wider than the fit view -- there was no way to stand back from it.
    const nz = clamp(view.zoom * (e.deltaY<0 ? 1.14 : 1/1.14), 0.04, 60);
    const f = nz / view.zoom;                          // actual factor after clamp
    // Keep the point under the cursor fixed -> zoom into wherever you're
    // looking. Zooming about the view centre would carry that point out to
    // o*f, so the camera slides back by o*(1-f) to leave it where it was.
    // Through panBy, so the zoom re-aims the camera rather than sliding the
    // picture off its own orbit centre -- and AFTER the new zoom is in, because
    // panBy sizes a pixel by it.
    const ox = mx - (W/2 + view.panx), oy = my - (H/2 + view.pany);
    view.zoom = nz;
    panBy(ox * (1 - f), oy * (1 - f), true);
  }, { passive:false });

  /* ---- select + camera fly ----------------------------------------- */
  /* ---- select-to-preview: sample-play a selected track's "drop" ----------
     Selecting a node cues a short clip from its first big energy jump (the drop)
     — or the middle as a fallback — on a DEDICATED audio element. Whether it
     actually SOUNDS is AUDIO's call (audio.js): the clip and the bottom Now
     Playing bar are the two audio sources, and the listener picks one. So this
     code cues the clip and reports it; it never pauses the other side itself. */
  const PREVIEW_SECONDS = 22;
  const PREV = { audio: new Audio(), token: 0, stopAt: 0, url: null, start: 0, node: null };
  PREV.audio.preload = 'auto';
  PREV.audio.addEventListener('timeupdate', () => {
    if (PREV.stopAt && PREV.audio.currentTime >= PREV.stopAt) stopPreview();
  });
  function stopPreview(){
    PREV.token++;                       // invalidate any in-flight start
    PREV.stopAt = 0;
    try { PREV.audio.pause(); } catch(_){ /* not started */ }
  }
  /* Forget the cued clip entirely — the strip that controls it goes away. */
  function clearPreview(){
    stopPreview();
    PREV.node = null;
    if (typeof AUDIO !== 'undefined') AUDIO.sampleClear();
  }
  if (typeof AUDIO !== 'undefined') AUDIO.registerSample({
    audio: PREV.audio,
    restart: () => { if (PREV.node) beginSample(null); },   // ⟲ replay / after the clip ran out
  });

  // Best spot to start a preview: first sustained high-energy point (the drop),
  // else ~40% in. Uses the DAW rms envelope from /waveform.
  async function dropStart(hash, duration){
    const dur = duration || 0;
    const cap = Math.max(0, dur - PREVIEW_SECONDS);   // leave room to play the clip
    try {
      const mm = await fetch('/waveform/' + hash).then(r => r.ok ? r.json() : null);
      const rms = mm && mm.rms;
      if (rms && rms.length && dur){
        let mx = 0; for (const v of rms) if (v > mx) mx = v;
        if (mx > 0){
          const thr = 0.72 * mx;
          for (let i = Math.floor(rms.length * 0.08); i < rms.length - 3; i++){
            if (rms[i] >= thr && rms[i + 1] >= thr && rms[i + 2] >= thr){
              return Math.min(i / rms.length * dur, cap);
            }
          }
        }
      }
    } catch(_){ /* fall through to the middle */ }
    return dur ? Math.min(dur * 0.4, cap) : 0;
  }

  /* Start (or restart) the cued clip. `my` guards against a newer selection
     landing first; pass null when the user asked for this one explicitly. */
  function beginSample(my){
    const go = () => {
      if (my !== null && my !== PREV.token) return;
      try { PREV.audio.currentTime = PREV.start; } catch(_){ /* seek after load */ }
      PREV.stopAt = PREV.start + PREVIEW_SECONDS;
      if (typeof AUDIO !== 'undefined') AUDIO.claim('sample');   // pauses the track
      PREV.audio.play().catch(() => {});
    };
    if (PREV.audio.readyState >= 1) go();
    else PREV.audio.addEventListener('loadedmetadata', go, { once: true });
  }

  async function previewTrack(n, keepIfSame){
    // Coming back to the star you are already sampling -- from the strip's own
    // title -- must not restart the clip. "Take me back to this" and "play this
    // again from the top" are different requests, and the second one has its own
    // button. Checked before stopPreview(), which would make it unanswerable.
    if (keepIfSame && n && PREV.node && PREV.node.hash === n.hash
        && !PREV.audio.paused && !PREV.audio.ended) return;
    stopPreview();
    // Tree mode used to be excluded here because nothing in it was selectable.
    // The tree card's "sample" button is, so the only thing left to reject is
    // an absent track.
    if (!n){ clearPreview(); return; }
    const my = PREV.token;                          // stopPreview() just bumped it
    // resolve a source: the server copy, else a persisted dropped-file handle
    let src = null;
    if (PREV.url){ URL.revokeObjectURL(PREV.url); PREV.url = null; }
    if (n.a) src = '/audio/' + n.hash;
    else if (typeof FSH !== 'undefined' && FSH.supported){
      const f = await FSH.file(n.hash);
      if (my !== PREV.token) return;                // a newer selection won
      if (f){ src = URL.createObjectURL(f); PREV.url = src; }
    }
    if (!src){ clearPreview(); return; }            // nothing playable — no strip
    const start = await dropStart(n.hash, n.duration);
    if (my !== PREV.token) return;
    PREV.audio.src = src;
    PREV.start = start;
    PREV.node = n;
    // Cue it: the strip appears either way, so a held sample is visible and one
    // click away rather than silently skipped.
    if (typeof AUDIO !== 'undefined'){
      AUDIO.sampleLoaded({
        title: n.artist ? stripArtist(n.title, n.artist) : n.title,
        artist: n.artist || '', color: famCss(n.fam),
        // Carried so the strip's title can lead back to the star being sampled:
        // an audition you liked is worth being able to return to, and a clip
        // playing under another view is otherwise a track with no name you can
        // act on.
        hash: n.hash,
        start, seconds: PREVIEW_SECONDS,
      });
      if (!AUDIO.wants('sample')) return;           // you're listening to the track
    }
    beginSample(my);
  }

  /* `cut` arrives at the star instead of flying to it.

     Clicking a dot on a map you are already looking at should move -- the glide
     is what tells you the star you clicked is the one now in the middle. But
     arriving from somewhere else (the now-playing bar, the sample strip, a deep
     link) there is no "here" to travel from: the map was not on screen a moment
     ago, so the flight starts from the whole-library framing and reads as
     opening zoomed all the way out and then zooming in, which is a 600ms trip
     through nothing to reach the star you asked for by name. */
  function selectNode(hash, cut){
    const n = byHash.get(hash); if (!n) return;
    selHash = hash; famPivot = null; focusedFam = null;   // orbit this track, not a genre
    panOff.x = panOff.y = panOff.z = 0;   // picking a track means "centre it", not "keep my pan"
    if (mapMode !== 'tree'){
      if (cut){
        // Put the camera where the tween would have ended, and the pivot on the
        // track itself -- the frame loop eases the pivot, so leaving it at the
        // old centre would still slide the star in from off-screen.
        anim = null;
        view.panx = 0; view.pany = 0;
        view.zoom = Math.max(closeZoom(), view.zoom);
        pivot.x = n.x3; pivot.y = n.y3; pivot.z = n.z3;
      } else {
        // the pivot eases to this track (frame loop), so it becomes the orbit
        // centre. keep the rotation, just zoom in a bit and recentre the view.
        anim = { f:{rx:rot.x,ry:rot.y,z:view.zoom,px:view.panx,py:view.pany},
                 t:{rx:rot.x, ry:rot.y, z:Math.max(closeZoom(), view.zoom), px:0, py:0},
                 t0:performance.now(), dur:600 };
      }
    }
    pushRecent(n);
    openPopup(n);
    previewTrack(n, cut);            // auto-sample the drop, unless it's already playing
  }

  /* The genre chips above a track's title: subgenre, then keystone, then
     archgenre -- narrowest first, because the narrow one is the answer and the
     wider ones are the context for it.

     The card used to carry a single chip holding the widest tier, which names
     the room a track belongs in and never the record: every Tech House, Deep
     House and Bassline track on the map said "House" and stopped there.

     A tier is dropped when it repeats the one beside it, keeping the wider
     reading of the name -- House IS an archgenre, so a House track gets one chip
     and not three identical ones. Read from server-side fields because all three
     come out of the taxonomy, which the user can edit and only the server holds
     -- and always sends, filing an unplaceable track under its own style. */
  function genreTiers(n){
    const tiers = [
      { cls:'is-sub',  txt: n.ksub || '',   why:'subgenre' },
      { cls:'is-key',  txt: n.klabel,       why:'genre' },
      { cls:'is-arch', txt: n.karch,        why:'archgenre' },
    ];
    const seen = new Set(), out = [];
    for (let i = tiers.length - 1; i >= 0; i--){       // widest first, so it wins the name
      const t = tiers[i], k = t.txt.toLowerCase();
      if (!k || seen.has(k)) continue;
      seen.add(k);
      out.unshift(t);
    }
    // One tier for the whole track -- a standalone archgenre, or a style the
    // taxonomy has no keystone for at all -- is not "a subgenre of nothing". It
    // is the answer, so it is painted as one: the single solid chip this card
    // has always shown.
    if (out.length === 1) out[0].cls = 'is-arch';
    return out;
  }

  /* The three chips share the star's own hue and differ only in how solidly they
     are painted, so the row reads as one genre widening rather than three
     unrelated labels. Computed here rather than with color-mix() in the
     stylesheet: this runs inside a desktop WebView whose version is the user's,
     and a hue arithmetic that works everywhere beats a colour function that
     might not. */
  function famChipVars(n){
    const h = famHue(n.fam);
    return `--c:hsl(${h} 62% 62%);--c-tint:hsl(${h} 40% 24%);`
         + `--c-line:hsl(${h} 34% 38%);--c-text:hsl(${h} 62% 76%)`;
  }

  async function openPopup(n){
    const meta = [
      n.style ? `<span><b>${escapeHtml(n.style)}</b> ${(n.score*100).toFixed(0)}%</span>` : '',
      n.bpm!=null ? `<span><b>${Math.round(n.bpm)}</b> bpm</span>` : '',
      `<span>${escapeHtml(keyfmt(n))}</span>`,
      `<span>${durfmt(n.duration)}</span>`,
    ].join('');
    const other = (n.styles||[]).filter(s=>s && s!==n.style);
    popEl.innerHTML = `
      <button class="pop-x" title="close">close ✕</button>
      <div class="pop-fams" style="${famChipVars(n)}">${genreTiers(n).map(t =>
        `<span class="pop-fam ${t.cls}" title="${t.why}">${escapeHtml(t.txt)}</span>`).join('')}</div>
      <div class="pop-title">${escapeHtml(n.artist ? stripArtist(n.title, n.artist) : n.title)}</div>
      ${artistsOf(n).length ? `<div class="pop-artist">${artistsOf(n).map(a =>
        `<button class="pop-artchip" data-kind="artist" data-v="${escapeHtml(a)}"
          title="click to show only ${escapeHtml(a)} · hover to preview"
          >${escapeHtml(a)}</button>`).join('<span class="pop-artsep">·</span>')}</div>` : ''}
      <div class="pop-meta">${meta}</div>
      <div class="pop-actions">${n.a
        ? `<button class="pop-play">▶ play</button>`
        : `<button class="pop-play" disabled title="no file on disk — re-scan this folder (batch) to enable playback">▶ no file</button>`}
        <button class="pop-add">${(window.playlistHas && window.playlistHas(n.hash)) ? '✓ in playlist' : '＋ playlist'}</button></div>
      ${n.flag ? `<div class="pop-flag">⚠ low-confidence read — its closest neighbours sound like
        <b>${escapeHtml(n.suggest || '?')}</b></div>` : ''}
      <div id="pop-pick"><div class="pop-bar" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim)">finding a match…</div></div>
      ${other.length ? `<div class="pop-h">also reads as</div>
        <div class="pop-artists">${other.map(s=>
          `<button class="chip chip-act" data-kind="style" data-v="${escapeHtml(s)}"
            title="click to show only ${escapeHtml(s)} · hover to preview">${escapeHtml(s)}</button>`).join('')}</div>` : ''}
      ${(n.tags||[]).length ? `<div class="pop-h">tags</div>
        <div class="pop-tags">${(n.tags||[]).map(t=>
          `<button class="pop-tag${FILT.tags.includes(t)?' on':''}" data-kind="tag" data-v="${escapeHtml(t)}"
            title="click to filter the map · hover to preview">${escapeHtml(t)}</button>`).join('')}</div>` : ''}
      <div class="pop-h">similar artists</div>
      <div class="pop-artists" id="pop-artists"><span class="pop-bar">…</span></div>
      <div class="pop-h">similar tracks</div>
      <div class="pop-sim" id="pop-sim"><span class="pop-bar">…</span></div>
      <div class="pop-h">rate this track</div>
      <div class="pop-rate pop-rate-track">${rateWidgetHtml({
        what: '', grade: 'letter grade (exports into the Rekordbox comment)',
        note: 'note (exports as “A - note”)' })}</div>
      ${artistsOf(n).length ? `<div class="pop-h">rate the artist</div>
      <div class="arate-pick">${artistsOf(n).map((a, i) =>
        `<button class="arate-who${i === 0 ? ' on' : ''}" data-a="${escapeHtml(a)}"
          >${escapeHtml(a)}</button>`).join('')}</div>
      <div class="pop-rate pop-rate-artist">${rateWidgetHtml({
        what: 'artist ', grade: 'letter grade for the artist', note: 'note about this artist' })}</div>
      <div class="pop-ratehint">Rates the selected artist across your whole library, not just
        this track.${artistsOf(n).length > 1 ? ' Pick which one above.' : ''}</div>` : ''}
      <div class="pop-omit-row">
        <button class="pop-adjust" title="nudge how much of each genre this track is — keeps the rest of the read">⚖ adjust</button>
        <button class="pop-override" title="set the genre yourself (persists + saved for training)">✎ override</button>
        <button class="pop-omit" title="delete this track's analysis (audio file untouched)">✕ omit</button>
      </div>
      <div class="pop-adj" hidden>${adjustPanelHtml()}</div>
      <div class="pop-ovr" hidden>
        <div class="ovr-cands"></div>
        <div class="ovr-typed">
          <input class="pop-ovr-in" type="text" placeholder="or type a genre…" list="ovr-genre-list"
                 autocomplete="off" spellcheck="false">
          <button class="pop-ovr-save">save</button>
          <button class="pop-ovr-cancel" title="cancel">✕</button>
        </div>
        <div class="ovr-hint">Tab completes · ↓ for the full list</div>
      </div>`;
    popEl.hidden = false;
    popEl.querySelector('.pop-x').onclick = closePopup;
    const playBtn = popEl.querySelector('.pop-play');
    if (playBtn && n.a) playBtn.onclick = () => {
      // the sample stays CUED -- starting the track claims your ears (audio.js),
      // and the sample strip's switch hands them back without re-selecting.
      if (window.playHash) window.playHash(n.hash, {
        title: n.artist ? stripArtist(n.title, n.artist) : n.title,
        artist: n.artist || '', color: famCss(n.fam),
      });
    };
    const addBtn = popEl.querySelector('.pop-add');
    if (addBtn) addBtn.onclick = () => {
      if (window.playlistAdd) window.playlistAdd({
        hash: n.hash, title: n.artist ? stripArtist(n.title, n.artist) : n.title,
        artist: n.artist || '', color: famCss(n.fam), a: n.a,
      });
      addBtn.textContent = '✓ in playlist'; addBtn.classList.add('added');
    };
    wireChips(popEl);
    // Keep the map's copies current so "size stars by rating" reacts now rather
    // than at the next full map load.
    wireRating(popEl.querySelector('.pop-rate-track'), `/ratings/${n.hash}`, j => {
      TRACK_RATINGS[n.hash] = { stars: j.stars || 0, grade: j.grade || '', note: j.note || '' };
      ratingsChanged();
    });
    {
      // A collaboration has several artists and each is rated separately, so the
      // widget is bound to whichever is picked and re-bound when that changes.
      const who = [...popEl.querySelectorAll('.arate-who')];
      const bind = name => wireRating(popEl.querySelector('.pop-rate-artist'),
        `/artist-ratings/${encodeURIComponent(name)}`,
        j => { ARTIST_RATINGS[j.key || artistKey(name)] = j; ratingsChanged(); });
      if (who.length){
        bind(who[0].dataset.a);
        for (const b of who) b.onclick = () => {
          who.forEach(x => x.classList.toggle('on', x === b));
          bind(b.dataset.a);
        };
      }
    }
    wireAdjust(popEl, n);
    popEl.querySelector('.pop-omit').onclick = () => omitTrack(n);
    const ovrRow = popEl.querySelector('.pop-ovr'), omitRow = popEl.querySelector('.pop-omit-row');
    const ovrIn = popEl.querySelector('.pop-ovr-in');
    const closeOvr = () => { ovrRow.hidden = true; omitRow.hidden = false; };
    popEl.querySelector('.pop-override').onclick = () => {
      omitRow.hidden = true; ovrRow.hidden = false;
      // The track's own runner-up reads, as one-click buttons. This is the usual
      // fix -- the correct genre is normally already in the list, just not first.
      const cands = (n.cands || []).filter(c => c.style && c.style !== n.style);
      const cbox = popEl.querySelector('.ovr-cands');
      cbox.innerHTML = cands.length
        ? `<div class="ovr-h">already reads as</div>` + cands.map(c =>
            `<button class="ovr-cand" data-g="${escapeHtml(c.style)}">${escapeHtml(c.style)}`
            + `<i>${(c.score * 100).toFixed(0)}%</i></button>`).join('')
        : `<div class="ovr-h">no runner-up read</div>`;
      for (const b of cbox.querySelectorAll('.ovr-cand')) {
        b.onclick = () => overrideTrack(n, b.dataset.g);
      }
      ovrIn.value = '';                       // the buttons carry the suggestion now
      ovrIn.placeholder = n.suggest ? `or type… (neighbours say ${n.suggest})` : 'or type a genre…';
      refreshGenreList();
      ovrIn.focus();
    };
    popEl.querySelector('.pop-ovr-cancel').onclick = closeOvr;
    popEl.querySelector('.pop-ovr-save').onclick = () => overrideTrack(n, ovrIn.value);
    ovrIn.addEventListener('keydown', e => {
      if (e.key === 'Enter') { overrideTrack(n, ovrIn.value); return; }
      if (e.key === 'Escape') { closeOvr(); return; }
      if (e.key === 'Tab' && ovrIn.value.trim()) {
        // Tab completes to the first genre that starts with what's typed. Only
        // when there IS a match, so Tab still moves focus normally otherwise.
        const hit = completeGenre(ovrIn.value);
        if (hit && hit.toLowerCase() !== ovrIn.value.trim().toLowerCase()) {
          e.preventDefault();
          ovrIn.value = hit;
          ovrIn.setSelectionRange(hit.length, hit.length);
        }
      }
    });
    try{
      simCache = await fetch(`/similar/${n.hash}?k=12`).then(r=>r.ok?r.json():[]);
    }catch(_){ simCache = []; }
    renderPick();
    renderSimilar(simCache);
  }

  /* Star / grade / note widget. Ratings live only in this app's database and
     surface in Rekordbox on export -- nothing here writes to your audio files.
     Each control saves on its own so a half-filled rating is never lost, and
     sends only the field it owns, so setting stars can't wipe a note. */
  /* The rating widget: five stars, a letter grade and a note, each saved the
     moment it changes (the note on blur, so one request per edit rather than
     per keystroke). Used twice in the popup -- for the track and for the
     artist -- against different endpoints; the two ratings answer different
     questions and neither is derived from the other. */
  function rateWidgetHtml({ what, grade, note }){
    return `<div class="rate-stars" role="group" aria-label="${what}star rating">
        ${[1,2,3,4,5].map(i=>`<button class="rate-star" data-s="${i}"
          title="${i} star${i>1?'s':''}" aria-label="${i} star${i>1?'s':''}">&#9733;</button>`).join('')}
        <button class="rate-clear" data-s="0" title="clear ${what}rating">&#10005;</button>
      </div>
      <select class="rate-grade" title="${grade}">
        <option value="">grade</option>
        ${['A','B','C','D','F'].map(g=>`<option value="${g}">${g}</option>`).join('')}
      </select>
      <input class="rate-note" type="text" placeholder="${note}"
             autocomplete="off" spellcheck="false" maxlength="1000">`;
  }

  // `box` is the widget's own .pop-rate element -- scoped, because the popup
  // holds two of these and an unscoped query painted both rows from one hover.
  // `onCommit(j)` sees every answer the server gives, so the caller can keep
  // its in-memory copy current.
  function wireRating(box, url, onCommit){
    if (!box) return;
    const stars = [...box.querySelectorAll('.rate-star')];
    const grade = box.querySelector('.rate-grade');
    const note  = box.querySelector('.rate-note');
    if (!stars.length || !grade || !note) return;

    // `saved` is the value on the server; `paint` is free to show a hover
    // preview on top of it. Only the server's answer updates `saved`, so
    // leaving the widget always restores the truth rather than the last hover.
    let saved = 0;
    const paint = v => stars.forEach(b => b.classList.toggle('on', +b.dataset.s <= v));
    const commit = j => {
      saved = j.stars || 0;
      paint(saved);
      if (onCommit) onCommit(j);
    };

    const save = async body => {
      try {
        const r = await fetch(url, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        if (r.ok) commit(await r.json());
      } catch(_){ /* offline / backend down -- the UI keeps what you typed */ }
    };

    fetch(url).then(r => r.ok ? r.json() : null).then(j => {
      if (!j) return;
      commit(j); grade.value = j.grade || ''; note.value = j.note || '';
    }).catch(() => {});

    // hovering previews the value you'd set; leaving restores the saved one
    for (const b of stars){
      b.onmouseenter = () => paint(+b.dataset.s);
      b.onclick = () => save({stars: +b.dataset.s});
    }
    const clear = box.querySelector('.rate-clear');
    if (clear) clear.onclick = () => save({stars: 0});
    const strip = box.querySelector('.rate-stars');
    if (strip) strip.onmouseleave = () => paint(saved);

    grade.onchange = () => save({grade: grade.value});
    note.onblur = () => save({note: note.value});
    note.onkeydown = e => { if (e.key === 'Enter') note.blur(); };
  }

  /* Every genre the library currently knows about -- families, subgenres, and
     each track's runner-up reads. Built from the loaded nodes rather than a new
     endpoint, so it can never drift from what's actually on the map, and it
     grows the moment you override something to a name that didn't exist. */
  function knownGenres(){
    const set = new Set();
    for (const n of NODES){
      if (n.fam) set.add(n.fam);
      if (n.style) set.add(n.style);
      for (const s of (n.styles || [])) if (s) set.add(s);
      for (const c of (n.cands || [])) if (c && c.style) set.add(c.style);
    }
    return [...set].sort((a, b) => a.localeCompare(b));
  }

  // Fill the shared <datalist> behind the override input's dropdown. app.js
  // owns the list (the Analyzer rows fill it too); the map adds what is on it.
  function refreshGenreList(){ fillGenreList(knownGenres()); }

  // First known genre starting with `prefix`; prefers an exact case-insensitive
  // hit so typing a full name doesn't get "completed" into a longer one.
  function completeGenre(prefix){
    const q = (prefix || '').trim().toLowerCase();
    if (!q) return null;
    const all = knownGenres();
    return all.find(g => g.toLowerCase() === q)
        || all.find(g => g.toLowerCase().startsWith(q))
        || null;
  }

  // --- adjust: nudge the blend instead of replacing it ----------------------
  // The shared panel (wireAdjustPanel, app.js) with the popup's chrome around
  // it: the omit row gives way while it is open, and the map re-clusters once,
  // when the user is done -- doing it per-press would slide the dot away from
  // the cursor between clicks.
  function wireAdjust(popEl, n){
    const btn  = popEl.querySelector('.pop-adjust');
    const box  = popEl.querySelector('.pop-adj');
    const omitRow = popEl.querySelector('.pop-omit-row');
    if (!btn || !box) return;
    let moved = false;         // did anything actually change? -> re-cluster on close
    wireAdjustPanel(btn, box, {
      hashOf: () => n.hash,
      genres: knownGenres,
      complete: completeGenre,
      onOpen: () => { omitRow.hidden = true; },
      onSaved: state => { applyToNode(n, state.adjusted); moved = true; },
      onClose: () => {
        omitRow.hidden = false;
        if (moved){ moved = false; if (NODES.length) layout(); }
      },
    });
  }

  // Recolour one dot from an adjusted blend. Deliberately does NOT re-cluster:
  // layout() would move the dot out from under the cursor mid-adjustment, so the
  // colour follows every press and the position catches up on close.
  function applyToNode(n, adjusted){
    if (!adjusted || !adjusted.length) return;
    const top = adjusted[0], second = adjusted[1];
    n.style = top.style; n.score = top.score;
    n.fam = familyOf(top.style) || 'Other';
    n.cands = adjusted.map(e => ({ style: e.style, score: e.score }));
    n.mix = second ? [second.style, Math.min(0.5, second.score / ((top.score || 0) + second.score))] : null;
    let sh = styleShade(n.fam, top.style);
    if (n.mix && n.mix[1] > 0.02){          // same blend layout() applies
      const f2 = familyOf(n.mix[0]) || n.fam;
      sh = mixShade(sh, styleShade(f2, n.mix[0]), n.mix[1]);
    }
    setShade(n, sh);
    n.flag = false; n.suggest = null;
  }

  /* Every chip in the popup behaves the same way: hover previews which tracks
     *would* survive by making them twinkle, click commits that as a filter.
     Clicking an active one clears it, so a chip is a toggle rather than a
     one-way trip into a filtered view you then have to go find the panel to
     escape.

     Genre and artist chips were inert until now, which on a library with no tags
     meant every chip you could actually see did nothing. */
  function wireChips(root){
    for (const b of root.querySelectorAll('[data-kind][data-v]')) {
      const kind = b.dataset.kind, value = b.dataset.v;
      b.onmouseenter = () => { HL = { kind, value }; };
      b.onmouseleave = () => { HL = null; };
      b.onclick = () => {
        HL = null;
        if (kind === 'tag') {
          const i = FILT.tags.indexOf(value);
          if (i >= 0) FILT.tags.splice(i, 1); else FILT.tags.push(value);
        } else if (kind === 'artist') {
          const v = value.toLowerCase();
          FILT.artist = FILT.artist === v ? '' : v;
        } else if (kind === 'style') {
          FILT.style = FILT.style === value ? '' : value;
        }
        markChips(root);
        syncFilterUI();
      };
    }
    markChips(root);
  }

  // Which chips are currently filtering. Recomputed rather than toggled in place
  // so a chip clicked here and a filter cleared in the panel can't disagree.
  function markChips(root){
    for (const b of root.querySelectorAll('[data-kind][data-v]')) {
      const k = b.dataset.kind, v = b.dataset.v;
      const on = k === 'tag' ? FILT.tags.includes(v)
        : k === 'artist' ? FILT.artist === v.toLowerCase()
        : k === 'style' ? FILT.style === v : false;
      b.classList.toggle('on', on);
    }
  }

  // override: persist a manual genre; the track moves to its new cluster
  async function overrideTrack(n, genre){
    genre = (genre || '').trim(); if (!genre) return;
    try{
      await fetch(`/override/${n.hash}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ genre }) });
    }catch(_){ /* still relabel locally */ }
    n.style = genre;
    n.fam = familyOf(genre) || 'Other';
    n.mix = null;                          // manual override -> pure genre, no blend
    setShade(n, styleShade(n.fam, genre));
    n.flag = false; n.suggest = null;
    closePopup();
    if (NODES.length) layout();          // re-cluster with the new genre
  }

  // omit/forget: delete this track's analysis from the DB and drop it off the map
  async function omitTrack(n){
    if (!window.confirm(
      `Remove "${n.title}" from your library?\n\n` +
      `This deletes its analysis (genre, BPM, key) and takes it off the map. ` +
      `Your audio file is NOT touched — re-scanning it will analyze it fresh.`)) return;
    try{ await fetch(`/forget/${n.hash}`, {method:'POST'}); }catch(_){ /* still drop it locally */ }
    NODES = NODES.filter(x => x.hash !== n.hash);
    EDGES = EDGES.filter(e => e.a !== n.hash && e.b !== n.hash);
    closePopup();
    if (NODES.length) layout();   // recompute clusters/labels/legend without it
  }

  // "pull up a random song among the ones that match it the most"
  function renderPick(){
    const box = document.getElementById('pop-pick'); if (!box) return;
    const top = simCache.slice(0, 6);
    if (!top.length){ box.innerHTML = ''; return; }
    const pick = top[Math.floor((performance.now()*13 % 997)/997 * top.length) % top.length];
    const nm = pick.artist ? `${pick.artist} – ${stripArtist(pick.title,pick.artist)}` : pick.title;
    box.innerHTML = `
      <div class="pop-pick" title="jump to this match">
        <div class="pk-top">a match for you
          <button class="pk-roll" title="another">⟳</button></div>
        <div class="pk-name">${escapeHtml(nm)}</div>
        <div class="pk-sub"><span>${escapeHtml(pick.style||'')}</span>
          <span class="pct">${(pick.sim*100).toFixed(0)}% match</span></div>
      </div>`;
    box.querySelector('.pop-pick').onclick = ev => {
      if (ev.target.closest('.pk-roll')) return;
      if (byHash.has(pick.hash)) selectNode(pick.hash);
    };
    box.querySelector('.pk-roll').onclick = ev => { ev.stopPropagation(); renderPick(); };
  }

  /* The artists on a /similar row. That payload carries the raw credit, but the
     track itself is in the library and its node already holds the split, so
     resolve through that and fall back to the raw string for anything not
     currently loaded. */
  function creditArtists(s){
    const n = byHash.get(s.hash);
    if (n) return artistsOf(n);
    return s.artist ? [s.artist] : [];
  }

  function renderSimilar(sim){
    const simEl = document.getElementById('pop-sim');
    const artEl = document.getElementById('pop-artists');
    if (!simEl) return;
    if (!sim.length){ simEl.innerHTML='<span class="pop-bar">no other tracks yet</span>';
                      if(artEl) artEl.innerHTML='<span class="pop-bar">--</span>'; return; }
    simEl.innerHTML = sim.slice(0,8).map(s => {
      const fam = familyOf(s.style||'') || 'Other';
      const who = creditArtists(s);
      const nm = who.length
        ? `${who.join(' · ')} – ${stripArtist(s.title, s.artist || who[0])}`
        : s.title;
      return `<div class="sim-row" data-h="${s.hash}">
        <span class="dot" style="background:${famCss(fam)}"></span>
        <span class="nm" title="${escapeHtml(s.title)}">${escapeHtml(nm)}</span>
        <button class="sim-play" data-h="${s.hash}" title="play">▶</button>
        <button class="sim-add" data-h="${s.hash}" title="add to playlist">＋</button>
        <span class="pct">${(s.sim*100).toFixed(0)}%</span></div>`;
    }).join('');
    simEl.querySelectorAll('.sim-row').forEach(row =>
      row.onclick = () => { const h=row.getAttribute('data-h'); if (byHash.has(h)) selectNode(h); });
    simEl.querySelectorAll('.sim-play').forEach(btn =>
      btn.onclick = ev => {
        ev.stopPropagation();
        const h = btn.getAttribute('data-h');
        const s = sim.find(x => x.hash === h);
        if (s && window.playHash) window.playHash(h, {
          title: s.artist ? stripArtist(s.title, s.artist) : s.title,
          artist: s.artist || '', color: famCss(familyOf(s.style || '') || 'Other'),
        });
      });
    simEl.querySelectorAll('.sim-add').forEach(btn =>
      btn.onclick = ev => {
        ev.stopPropagation();
        const h = btn.getAttribute('data-h');
        const s = sim.find(x => x.hash === h);
        if (s && window.playlistAdd) {
          window.playlistAdd({
            hash: h, title: s.artist ? stripArtist(s.title, s.artist) : s.title,
            artist: s.artist || '', color: famCss(familyOf(s.style || '') || 'Other'), a: s.a,
          });
          btn.textContent = '✓';
        }
      });
    const seen=new Set(), artists=[];
    // Collect INDIVIDUAL artists, not credit strings. A collaboration used to
    // arrive here whole, so the chip filtered on the entire credit and no
    // single member of it was reachable.
    outer:
    for (const s of sim){
      for (const a of creditArtists(s)){
        const key = a.trim().toLowerCase();
        if (!key || seen.has(key)) continue;
        seen.add(key); artists.push(a.trim());
        if (artists.length >= 6) break outer;
      }
    }
    if (artEl) {
      artEl.innerHTML = artists.length
        ? artists.map(a=>`<button class="chip chip-act" data-kind="artist" data-v="${escapeHtml(a)}"
              title="click to show only ${escapeHtml(a)} · hover to preview">${escapeHtml(a)}</button>`).join('')
        : '<span class="pop-bar">--</span>';
      // These arrive after the popup is built (they need /similar), so they miss
      // the wiring pass the rest of the chips got.
      wireChips(artEl);
    }
  }
  const stripArtist = (title, artist) =>
    (artist && title.toLowerCase().startsWith(artist.toLowerCase()+' - '))
      ? title.slice(artist.length+3) : title;

  function closePopup(){
    clearPreview();
    popEl.hidden = true; selHash = null; famPivot = null; focusedFam = null;
  }

  /* ---- search ------------------------------------------------------ */
  let sugItems=[], sugIdx=-1;
  function runSearch(q){
    q = q.trim().toLowerCase();
    if (!q){ suggestEl.hidden = true; return; }
    const hits = NODES.filter(n =>
      (`${n.title} ${n.artist} ${n.fam} ${n.style||''}`).toLowerCase().includes(q)
    ).slice(0,8);
    sugItems = hits; sugIdx = -1;
    if (!hits.length){ suggestEl.innerHTML=`<div class="sug">no match</div>`; suggestEl.hidden=false; return; }
    suggestEl.innerHTML = hits.map((n,i) =>
      `<div class="sug" data-i="${i}">
         <span class="dot" style="background:${famCss(n.fam)}"></span>
         <span>${escapeHtml(n.title)}</span>
         <span class="st">${escapeHtml(n.fam)}</span></div>`).join('');
    suggestEl.hidden = false;
    suggestEl.querySelectorAll('.sug').forEach(d =>
      d.onclick = () => choose(+d.getAttribute('data-i')));
  }
  function choose(i){ const n=sugItems[i]; if(!n) return;
    suggestEl.hidden=true; searchEl.value=n.title; selectNode(n.hash); }
  searchEl && searchEl.addEventListener('input', e => runSearch(e.target.value));
  searchEl && searchEl.addEventListener('keydown', e => {
    if (suggestEl.hidden) return;
    if (e.key==='ArrowDown'||e.key==='ArrowUp'){ e.preventDefault();
      sugIdx=(sugIdx+(e.key==='ArrowDown'?1:-1)+sugItems.length)%sugItems.length;
      suggestEl.querySelectorAll('.sug').forEach((d,i)=>d.classList.toggle('active',i===sugIdx));
    } else if (e.key==='Enter'){ e.preventDefault(); choose(sugIdx>=0?sugIdx:0); }
    else if (e.key==='Escape'){ suggestEl.hidden=true; }
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('.map-search-wrap')) suggestEl.hidden = true;
  });

  function resetView(){
    closePopup();
    fitView();
  }

  /* Frame the current mode. Split out of resetView() so entering the Map tab
     gets identical framing without also closing a popup that was never open --
     tab entry used to carry its own one-line copy of this, which silently
     skipped the solar branch. */
  function fitView(){
    view.panx=0; view.pany=0; rot.x=-0.15; anim=null;
    panOff.x = panOff.y = panOff.z = 0;      // "view reset" also un-flies the camera
    if (mapMode === 'tree'){ fitTree(); return; }
    // Snap rather than ease. Framing the map is a cut, not a move: easing here
    // would open the view off-centre and slide it into place, which reads as the
    // map drifting on its own. Callers reach this with nothing selected, so the
    // resting target is BARY.
    pivot.x = BARY.x; pivot.y = BARY.y; pivot.z = BARY.z;
    if (mapMode === 'solar'){
      // Solar's bodies orbit in the XZ plane, so the default -0.15 tilt shows
      // the system almost edge-on and the rings collapse into lines. Look down
      // on it instead -- that is the view in which "which ring is this track
      // in" is actually answerable -- and fit the outermost orbit with a margin
      // for the ring labels, which sit outside it.
      rot.x = -0.62;
      view.zoom = clamp(1.15 / (FITR || 1), 0.05, 2.2);
      return;
    }
    /* Fit the cloud. The factor differs by mode because the modes differ in how
       much of their radius is deliberately empty: regions packs its families
       shoulder to shoulder, while the Universe puts real space between galaxies
       by design. Measured on a 3,300-track library, the same factor filled 90%
       of the frame in regions and 57% in the Universe -- the same "fit" leaving
       the sky sitting in a small knot with nothing around it. */
    const fitK = mapMode === 'universe' ? 1.9 : 1.25;
    view.zoom = clamp(fitK / (FITR || 1), 0.05, 1.6);
  }
  function focusFamily(fam){          // fly to a genre's centroid + orbit around it
    const c = CENTROIDS[fam]; if (!c) return;
    closePopup();                     // drop any track selection...
    famPivot = c;                     // ...then orbit around this cluster's centre
    panOff.x = panOff.y = panOff.z = 0;   // flying somewhere cancels a free-flown camera
    focusedFam = fam;                 // ...and force this genre's subgenre labels on
    const ry = Math.atan2(-c.x, c.z), rx = Math.atan2(c.y, Math.hypot(c.x, c.z));
    anim = { f:{rx:rot.x,ry:rot.y,z:view.zoom,px:view.panx,py:view.pany},
             t:{rx, ry, z:2.0, px:0, py:0}, t0:performance.now(), dur:640 };
  }
  function focusStyle(fam, style){    // fly to & orbit ONE subgenre's sub-cluster
    let x=0, y=0, z=0, c=0;           // centroid computed on demand -> works in any layout
    for (const n of NODES){
      if (n.fam === fam && (n.style || n.fam) === style){ x+=n.x3; y+=n.y3; z+=n.z3; c++; }
    }
    if (!c) return;
    const cen = { x:x/c, y:y/c, z:z/c };
    closePopup();
    famPivot = cen;                   // orbit around the subgenre sub-cluster
    panOff.x = panOff.y = panOff.z = 0;   // ...and stops looking past it
    focusedFam = fam;                 // keep the family's subgenre labels visible
    const ry = Math.atan2(-cen.x, cen.z), rx = Math.atan2(cen.y, Math.hypot(cen.x, cen.z));
    anim = { f:{rx:rot.x,ry:rot.y,z:view.zoom,px:view.panx,py:view.pany},
             t:{rx, ry, z:2.8, px:0, py:0}, t0:performance.now(), dur:640 };   // tighter zoom
  }
  function applyFilter(fam){          // null = show all genres
    flaggedOnly = false;
    filterFam = fam || null;
    const fe = document.getElementById('map-filter');
    if (fe) fe.value = filterFam || '';
    closePopup();
    if (filterFam) focusFamily(filterFam); else resetView();
  }
  resetB && resetB.addEventListener('click', () => applyFilter(null));

  const spinEl = document.getElementById('map-spin');   // orbit-speed slider
  const playBtn = document.getElementById('map-play');  // pause / play the orbit
  let lastSpin = 0.0006;
  const syncSpin = () => { if (spinEl) spinEl.value = Math.round(spinSpeed / 0.006 * 100); };
  function reflectPlay(){                                // button icon <- current state
    if (!playBtn) return;
    const on = spinSpeed > 0;
    playBtn.classList.toggle('on', on);
    playBtn.innerHTML = on ? '&#9208;' : '&#9205;';     // ⏸ pause when spinning · ▶ play when stopped
    playBtn.title = (on ? 'pause' : 'play') + ' the orbit (Space)';
  }
  const applySpin = () => { if (spinEl){ spinSpeed = (spinEl.value / 100) * 0.006; reflectPlay(); } };
  function toggleSpin(){
    if (spinSpeed > 0){ lastSpin = spinSpeed; spinSpeed = 0; } else { spinSpeed = lastSpin || 0.0006; }
    syncSpin(); reflectPlay();
  }
  spinEl && spinEl.addEventListener('input', applySpin);
  // blur after click so a following Space isn't caught by the focused button
  // (native activation) *and* the document handler -> a double-toggle no-op.
  playBtn && playBtn.addEventListener('click', () => { toggleSpin(); playBtn.blur(); });
  applySpin();

  // navigation key legend: collapsible, state remembered
  const keysEl = document.getElementById('map-keys');
  const keysHead = document.getElementById('map-keys-head');
  if (keysEl && keysHead){
    // Closed unless you have opened it before -- see the legend above.
    let navOpen = false;
    try{ navOpen = localStorage.getItem('vibeNavKeys') === 'on'; }catch(_){}
    keysEl.classList.toggle('collapsed', !navOpen);
    keysHead.addEventListener('click', () => {
      const off = keysEl.classList.toggle('collapsed');
      try{ localStorage.setItem('vibeNavKeys', off ? 'off' : 'on'); }catch(_){}
    });
  }

  const filterEl = document.getElementById('map-filter');
  filterEl && filterEl.addEventListener('change', () => {
    if (filterEl.value === '__flagged__'){ filterFam = null; flaggedOnly = true; closePopup(); resetView(); }
    else applyFilter(filterEl.value);
  });

  // toggles: connection lines + harmonic-mix highlighting
  const edgesBtn = document.getElementById('map-edges');
  edgesBtn && edgesBtn.addEventListener('click', () => {
    edgesOn = !edgesOn; edgesBtn.classList.toggle('on', edgesOn);
  });
  const harmonicBtn = document.getElementById('map-harmonic');
  harmonicBtn && harmonicBtn.addEventListener('click', () => {
    harmonic = !harmonic; harmonicBtn.classList.toggle('on', harmonic);
  });

  /* ---- facet filter popover ---------------------------------------- */
  const filtBtn   = document.getElementById('map-filt-btn');
  const filtPanel = document.getElementById('map-filt-panel');
  if (filtBtn && filtPanel){
    const $f = id => document.getElementById(id);
    // Slider positions are 0-100 percent of the library's own observed range, so
    // the control fits whatever is actually loaded instead of a hard-coded scale.
    let bpmLo = 0, bpmHi = 200, lenLo = 0, lenHi = 600;
    const pct2 = (p, lo, hi) => lo + (hi - lo) * (p / 100);
    const fmtLen = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

    // Recompute the slider domains from the loaded nodes. Uses the 1st/99th
    // percentile, not min/max: one BPM misread at 738 would otherwise squash the
    // whole useful range into a few pixels.
    function calibrate(){
      const bs = NODES.map(n => n.bpm).filter(v => v > 0).sort((a, b) => a - b);
      const ls = NODES.map(n => n.duration).filter(v => v > 0).sort((a, b) => a - b);
      const pick = (arr, q, dflt) => arr.length ? arr[Math.floor(q * (arr.length - 1))] : dflt;
      bpmLo = Math.floor(pick(bs, 0.01, 60));  bpmHi = Math.ceil(pick(bs, 0.99, 200));
      lenLo = Math.floor(pick(ls, 0.01, 0));   lenHi = Math.ceil(pick(ls, 0.99, 600));
      if (bpmHi <= bpmLo) bpmHi = bpmLo + 1;
      if (lenHi <= lenLo) lenHi = lenLo + 1;
    }

    function readRange(loId, hiId, lo, hi){
      const a = +$f(loId).value, b = +$f(hiId).value;
      // parked at an end => no bound, so outliers stay visible until you narrow
      return [a <= 0 ? null : pct2(a, lo, hi), b >= 100 ? null : pct2(b, lo, hi)];
    }

    const setTxtF = (id, v) => { const el = $f(id); if (el) el.textContent = v; };

    function syncFilt(){
      const b = FILT.bpm, l = FILT.len;
      setTxtF('flt-bpm-v', (b[0] == null && b[1] == null) ? 'any'
        : `${Math.round(b[0] ?? bpmLo)}–${Math.round(b[1] ?? bpmHi)}`);
      setTxtF('flt-len-v', (l[0] == null && l[1] == null) ? 'any'
        : `${fmtLen(l[0] ?? lenLo)}–${fmtLen(l[1] ?? lenHi)}`);
      setTxtF('flt-tags-v', FILT.tags.length ? FILT.tags.join(' + ') : 'any');
      // A chip in the popup writes straight to FILT, so the controls have to be
      // pushed back into sync or the panel would show "any" over a live filter.
      const asel = $f('flt-artist'); if (asel && asel.value.trim().toLowerCase() !== FILT.artist) asel.value = FILT.artist;
      const ssel2 = $f('flt-style'); if (ssel2 && ssel2.value !== FILT.style) ssel2.value = FILT.style;
      const pchk = $f('flt-playable'); if (pchk && pchk.checked !== !!FILT.playable) pchk.checked = !!FILT.playable;
      setTxtF('flt-gen-v', FILT.hidden.length ? `${FILT.hidden.length} hidden` : 'all');
      for (const b2 of (($f('flt-tags') || {}).querySelectorAll ? $f('flt-tags').querySelectorAll('.flt-tag') : []))
        b2.classList.toggle('on', FILT.tags.includes(b2.dataset.t));
      filtBtn.classList.toggle('on', filtActive());
      // Clearing a filter from the panel has to un-mark the chip that set it.
      if (popEl && !popEl.hidden) markChips(popEl);
      if (countMap && NODES.length){
        const shown = NODES.filter(passes).length;
        countMap.textContent = filtActive() || filterFam || flaggedOnly
          ? `${shown} of ${NODES.length} tracks · filtered`
          : mapCountText();
      }
    }

    // Populate the key + playlist + tag choosers from what's actually loaded.
    async function populate(){
      calibrate();
      const keys = [...new Set(NODES.map(n => n.camelot).filter(Boolean))]
        .sort((a, b) => (parseInt(a) - parseInt(b)) || a.localeCompare(b));
      const ksel = $f('flt-key');
      if (ksel) ksel.innerHTML = `<option value="">any key</option>`
        + keys.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join('');
      // Every genre any track reads as, not just the dominant ones -- a chip for
      // a runner-up read has to be selectable in the panel too, or clicking it
      // would set a filter the control could not show.
      const styles = [...new Set(NODES.flatMap(n => [n.style, ...(n.styles || [])]).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b));
      const ssel = $f('flt-style');
      if (ssel) ssel.innerHTML = `<option value="">any genre</option>`
        + styles.map(k => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join('');
      const tags = [...new Set(NODES.flatMap(n => n.tags || []))].sort();
      const tbox = $f('flt-tags');
      if (tbox) tbox.innerHTML = tags.length
        ? tags.map(t => `<button class="flt-tag" data-t="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join('')
        : `<span class="mp-hint">no tags yet</span>`;
      if (tbox) for (const b of tbox.querySelectorAll('.flt-tag')) {
        b.onclick = () => {
          const t = b.dataset.t, i = FILT.tags.indexOf(t);
          if (i >= 0) FILT.tags.splice(i, 1); else FILT.tags.push(t);
          b.classList.toggle('on', FILT.tags.includes(t));
          syncFilt();
        };
      }
      // The playlist facet is filled from the same list Solar's picker uses --
      // one fetch, one shape, and both stay in step when one changes.
      await refreshPlaylists();
      syncFilt();
    }
    window.mapFilterPopulate = populate;

    // let anything outside this block (the popup's tag chips) refresh the panel
    /* The genre list: one row per keystone, with its track count, all ticked
       until you untick one. Built from the loaded library rather than the
       taxonomy, so it lists the genres you actually have and cannot offer a
       filter that would hide nothing. */
    const genBox = $f('flt-genres');
    function genreRows(){
      const count = {}, famOf = {};
      for (const n of NODES) for (const g of genreKeysOf(n)){
        count[g] = (count[g] || 0) + 1;      // a fusion counts under each parent
        /* `n.family` from the server, NOT `n.fam`.
           They sound interchangeable and are not: `n.fam` is recomputed on this
           side from the PulseRoots table and comes out as one of ~54 fine
           families (Metalcore, Alternative Rock, Phonk), so it is almost never
           the string "Other" -- which is why the electronic filter used to run
           and hide nothing at all. The server's `family` is the coarse tier the
           taxonomy actually files a track under: Dance, Bass, Chill,
           Experimental, or Other for whatever it could not place. */
        famOf[g] = n.family;
      }
      return Object.keys(count).sort((a, b) => count[b] - count[a])
        .map(g => ({ name: g, n: count[g], fam: famOf[g] }));
    }
    function buildGenres(){
      if (!genBox) return;
      const rows = genreRows();
      genBox.innerHTML = rows.map(r =>
        `<label class="flt-gen"><input type="checkbox" data-g="${escapeHtml(r.name)}"
          ${FILT.hidden.includes(r.name) ? '' : 'checked'}>
          <span>${escapeHtml(r.name)}</span><i>${r.n}</i></label>`).join('');
      for (const cb of genBox.querySelectorAll('input')){
        cb.onchange = () => {
          const g = cb.dataset.g;
          const i = FILT.hidden.indexOf(g);
          if (cb.checked){ if (i >= 0) FILT.hidden.splice(i, 1); }
          else if (i < 0) FILT.hidden.push(g);
          onFilt();
        };
      }
    }
    function setGenres(pred){
      const rows = genreRows();
      FILT.hidden = rows.filter(r => !pred(r)).map(r => r.name);
      buildGenres(); onFilt();
    }
    if (genBox){
      $f('flt-gen-all').addEventListener('click', () => setGenres(() => true));
      $f('flt-gen-none').addEventListener('click', () => setGenres(() => false));
      /* "Electronic" is everything the taxonomy could place: Dance, Bass, Chill
         or Experimental. What it could not place lands in Other, which on a
         mostly-electronic library is the metal, punk and hip hop. */
      $f('flt-gen-elec').addEventListener('click', () => setGenres(r => r.fam !== 'Other'));
    }
    window.mapGenrePopulate = buildGenres;

    syncFilterUI = syncFilt;
    const onFilt = () => { syncFilt(); };
    $f('flt-artist').addEventListener('input', e => {
      FILT.artist = e.target.value.trim().toLowerCase(); onFilt();
    });
    $f('flt-key').addEventListener('change', e => { FILT.key = e.target.value; onFilt(); });
    $f('flt-style').addEventListener('change', e => { FILT.style = e.target.value; onFilt(); });
    $f('flt-playable').addEventListener('change', e => { FILT.playable = e.target.checked; onFilt(); });
    $f('flt-pl').addEventListener('change', async e => {
      FILT.playlist = e.target.value || null;
      const got = FILT.playlist ? await playlistHashSet(FILT.playlist) : null;
      playlistHashes = got ? got.hashes : null;
      onFilt();
    });
    for (const id of ['flt-bpm-lo','flt-bpm-hi']) $f(id).addEventListener('input', () => {
      FILT.bpm = readRange('flt-bpm-lo','flt-bpm-hi', bpmLo, bpmHi); onFilt();
    });
    for (const id of ['flt-len-lo','flt-len-hi']) $f(id).addEventListener('input', () => {
      FILT.len = readRange('flt-len-lo','flt-len-hi', lenLo, lenHi); onFilt();
    });
    $f('flt-reset').addEventListener('click', () => {
      FILT = JSON.parse(JSON.stringify(FILT_EMPTY));
      playlistHashes = null;
      $f('flt-artist').value = ''; $f('flt-key').value = ''; $f('flt-pl').value = '';
      $f('flt-playable').checked = false;
      if (window.mapGenrePopulate) window.mapGenrePopulate();   // re-tick every genre
      $f('flt-bpm-lo').value = 0; $f('flt-bpm-hi').value = 100;
      $f('flt-len-lo').value = 0; $f('flt-len-hi').value = 100;
      for (const b of filtPanel.querySelectorAll('.flt-tag.on')) b.classList.remove('on');
      syncFilt();
    });
    filtBtn.addEventListener('click', e => {
      e.stopPropagation(); closeMapPanels(filtPanel); filtPanel.hidden = !filtPanel.hidden;
    });
    filtPanel.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { filtPanel.hidden = true; });
  }

  /* ---- label options popover --------------------------------------- */
  /* Every toolbar panel opens in the same corner (`.map-panel` is absolutely
     positioned at the same spot), so only one can usefully be open. Each button
     stops its own click from reaching the document handler that closes them,
     which meant opening a second panel left the first stacked behind it. */
  function closeMapPanels(except){
    for (const id of ['map-filt-panel', 'map-recent-panel', 'map-lbl-panel', 'uni-panel']){
      const el = document.getElementById(id);
      if (el && el !== except) el.hidden = true;
    }
  }

  /* ---- recently viewed stars ---------------------------------------- */
  const recentBtn = document.getElementById('map-recent-btn');
  const recentPanel = document.getElementById('map-recent-panel');
  if (recentBtn && recentPanel){
    const listEl = document.getElementById('map-recent-list');
    const hintEl2 = document.getElementById('map-recent-hint');
    const clearEl = document.getElementById('map-recent-clear');

    renderRecent = () => {
      // A track can be omitted from the library after you looked at it. Drop
      // those rather than offering a row that goes nowhere -- but only once the
      // map has actually loaded, or an empty byHash would erase the whole list.
      const known = NODES.length
        ? RECENT.filter(r => r && byHash.has(r.hash))
        : RECENT.filter(Boolean);
      if (known.length !== RECENT.length && NODES.length){ RECENT = known; saveRecent(); }
      recentBtn.classList.toggle('on', known.length > 0);
      if (!known.length){
        listEl.innerHTML = '';
        hintEl2.textContent = 'Nothing yet. Every star you open lands here, newest first.';
        clearEl.disabled = true;
        return;
      }
      hintEl2.textContent = 'Newest first. Click one to go straight back to it.';
      clearEl.disabled = false;
      listEl.innerHTML = known.map(r => {
        const n = byHash.get(r.hash);
        const col = n ? famCss(n.fam) : 'var(--dim)';
        const sub = [r.artist, n && n.style].filter(Boolean).join(' \u00b7 ');
        return `<button class="recent-item" data-h="${escapeHtml(r.hash)}"
          title="${escapeHtml(r.title || r.hash)}">
          <span class="recent-dot" style="background:${col}"></span>
          <span class="recent-txt"><b>${escapeHtml(r.title || 'Track')}</b>
          ${sub ? `<i>${escapeHtml(sub)}</i>` : ''}</span></button>`;
      }).join('');
      for (const b of listEl.querySelectorAll('.recent-item')){
        b.onclick = () => {
          recentPanel.hidden = true;
          // Same arrival as the now-playing bar: you named the star, so cut to it.
          if (byHash.has(b.dataset.h)) selectNode(b.dataset.h, true);
        };
      }
    };
    renderRecent();

    clearEl.addEventListener('click', () => { RECENT = []; saveRecent(); renderRecent(); });
    recentBtn.addEventListener('click', e => {
      e.stopPropagation();
      renderRecent();                       // the list may have grown since it last opened
      closeMapPanels(recentPanel);
      recentPanel.hidden = !recentPanel.hidden;
    });
    recentPanel.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { recentPanel.hidden = true; });
  }

  const lblBtn   = document.getElementById('map-lbl-btn');
  const lblPanel = document.getElementById('map-lbl-panel');
  if (lblBtn && lblPanel){
    const $ = id => document.getElementById(id);
    // null-safe setters so an HTML/JS version mismatch never crashes the map
    const setChk = (id, v) => { const el = $(id); if (el) el.checked = v; };
    const setVal = (id, v) => { const el = $(id); if (el) el.value = v; };
    const setTxt = (id, v) => { const el = $(id); if (el) el.textContent = v; };
    // push current LBL state into the controls
    const syncLbl = () => {
      setChk('lbl-fam', LBL.showFam);
      setChk('lbl-sub', LBL.showSub);
      setChk('lbl-subalways', LBL.subAlways);
      setChk('lbl-color', LBL.colorFam);
      setChk('lbl-counts', LBL.counts);
      setChk('lbl-hidetext', LBL.hideText);
      setChk('lbl-leaders', LBL.leaders);
      setChk('lbl-rate', LBL.sizeByRating);
      setChk('lbl-rate-artist', LBL.useArtistRating);
      setVal('lbl-shine', Math.round(LBL.shine * 100));
      setTxt('lbl-shine-v', LBL.shine.toFixed(1) + '×');
      setVal('lbl-twinkle', LBL.twinkle);
      setVal('lbl-lblstyle', LBL.labelStyle);
      setVal('lbl-lw',   Math.round(LBL.linkWidth * 100));
      setTxt('lbl-lw-v', LBL.linkWidth.toFixed(1) + '×');
      setVal('lbl-op',   Math.round(LBL.opacity * 100));
      setVal('lbl-dist', Math.round(LBL.dist * 100));
      setVal('lbl-size', Math.round(LBL.size * 100));
      setVal('lbl-maxf', LBL.maxFam);
      setVal('lbl-maxs', LBL.maxSub);
      setTxt('lbl-op-v',   Math.round(LBL.opacity * 100) + '%');
      setTxt('lbl-dist-v', LBL.dist.toFixed(1) + '×');
      setTxt('lbl-size-v', LBL.size.toFixed(1) + '×');
      setTxt('lbl-maxf-v', LBL.maxFam ? LBL.maxFam : 'all');
      setTxt('lbl-maxs-v', LBL.maxSub ? LBL.maxSub : 'all');
      setVal('lbl-only', LBL.onlyFam || '');
      lblBtn.classList.toggle('on',
        !LBL.showFam || !LBL.showSub || !!LBL.onlyFam || !!LBL.maxFam || !!LBL.maxSub
        || LBL.linkWidth !== 1 || LBL.hideText || LBL.sizeByRating
        || LBL.twinkle !== 'subtle' || LBL.labelStyle !== 'halo' || LBL.shine !== 1.4);
    };
    syncLbl();
    lblBtn.addEventListener('click', e => {
      closeMapPanels(lblPanel);
      e.stopPropagation();
      lblPanel.hidden = !lblPanel.hidden;
    });
    lblPanel.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { lblPanel.hidden = true; });
    const bind = (id, fn) => { const el = $(id); if (el) el.addEventListener('input', () => { fn(el); saveLbl(); syncLbl(); }); };
    bind('lbl-fam',       el => LBL.showFam   = el.checked);
    bind('lbl-sub',       el => LBL.showSub   = el.checked);
    bind('lbl-subalways', el => LBL.subAlways = el.checked);
    bind('lbl-color',     el => LBL.colorFam  = el.checked);
    bind('lbl-counts',    el => LBL.counts    = el.checked);
    bind('lbl-hidetext',  el => LBL.hideText  = el.checked);
    bind('lbl-leaders',   el => LBL.leaders   = el.checked);
    bind('lbl-shine',     el => LBL.shine     = +el.value / 100);
    bind('lbl-twinkle',   el => LBL.twinkle   = el.value);
    bind('lbl-lblstyle',  el => LBL.labelStyle = el.value);
    bind('lbl-rate',      el => LBL.sizeByRating   = el.checked);
    bind('lbl-rate-artist', el => LBL.useArtistRating = el.checked);
    bind('lbl-lw',        el => LBL.linkWidth = +el.value / 100);
    bind('lbl-only',      el => LBL.onlyFam   = el.value);
    bind('lbl-op',        el => LBL.opacity   = +el.value / 100);
    bind('lbl-dist',      el => LBL.dist      = +el.value / 100);
    bind('lbl-size',      el => LBL.size      = +el.value / 100);
    bind('lbl-maxf',      el => LBL.maxFam    = +el.value);
    bind('lbl-maxs',      el => LBL.maxSub    = +el.value);
    $('lbl-reset').addEventListener('click', () => {
      LBL = Object.assign({}, LBL_DEFAULTS); saveLbl(); syncLbl();
    });
    // clear every custom genre + subgenre colour (back to the auto hues)
    $('lbl-reset-col').addEventListener('click', () => {
      FAM_HUE = {}; SUB_HUE = {};
      try{ localStorage.removeItem('vibeFamHue'); localStorage.removeItem('vibeSubHue'); }catch(_){}
      if (NODES.length) layout();
    });
  }

  // keyboard nav: W/S zoom · A/D orbit · arrows pan · +/- zoom · Space play/pause
  //               · f fit · Esc close
  document.addEventListener('keydown', e => {
    if (!document.body.classList.contains('view-map')) return;
    const tag = e.target.tagName || '';
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    const PAN = 45, ROT = 0.12;
    const k = e.key.toLowerCase();
    switch (k){
      case '+': case '=': case 'w': view.zoom = clamp(view.zoom*1.15, 0.04, 60); anim=null; break;
      case '-': case '_': case 's': view.zoom = clamp(view.zoom/1.15, 0.04, 60); anim=null; break;
      case 'a': rot.y -= ROT; break;                 // orbit left
      case 'd': rot.y += ROT; break;                 // orbit right
      case 'arrowleft':  panBy( PAN, 0); break;      // arrows fly the camera
      case 'arrowright': panBy(-PAN, 0); break;
      case 'arrowup':    panBy(0,  PAN); break;
      case 'arrowdown':  panBy(0, -PAN); break;
      case ' ': toggleSpin(); break;
      case 'f': applyFilter(null); break;
      case 'escape': closePopup(); break;
      default: return;
    }
    if (k.startsWith('arrow') || k === ' ') e.preventDefault();
  });
  /* Only the active mode's controls are shown. The toolbar already carries a
     lot; adding a playlist picker and two cluster selects that are meaningless
     in four of five modes would make it unreadable. */
  function syncModeControls(){
    document.querySelectorAll('.mode-only').forEach(el => {
      el.hidden = el.dataset.for !== mapMode;
    });
  }
  syncModeControls();

  modeEl && modeEl.addEventListener('click', async e => {
    const b = e.target.closest('.mm'); if (!b || b.dataset.mode===mapMode) return;
    mapMode = b.dataset.mode;
    modeEl.querySelectorAll('.mm').forEach(m => m.classList.toggle('active', m===b));
    closePopup(); closeTreeCard(); suggestEl.hidden = true;
    syncModeControls();
    if (mapMode === 'solar'){ await refreshPlaylists(); await loadSolarSet(); }
    if (NODES.length){ layout(); resetView(); }
  });

  /* Universe: how far apart the galaxies settle and how hard they pull.

     Both re-run the relaxation, which moves every star, so they relayout rather
     than adjusting the camera. Debounced: dragging a slider fires continuously
     and a full layout per pixel of travel is not something the thread can keep
     up with on a large library. */
  const uniPanel = document.getElementById('uni-panel');
  const uniBtn = document.getElementById('uni-btn');
  if (uniBtn && uniPanel){
    const sepIn = document.getElementById('uni-sep');
    const gravIn = document.getElementById('uni-grav');
    const sepV = document.getElementById('uni-sep-v');
    const gravV = document.getElementById('uni-grav-v');
    let relayoutT = null;
    const showVals = () => {
      sepV.textContent = UNI.sep.toFixed(1) + '\u00d7';
      gravV.textContent = UNI.grav.toFixed(1) + '\u00d7';
    };
    sepIn.value = String(Math.round(UNI.sep * 100));
    gravIn.value = String(Math.round(UNI.grav * 100));
    showVals();
    const relayoutSoon = () => {
      clearTimeout(relayoutT);
      relayoutT = setTimeout(() => {
        saveUni();
        if (NODES.length && mapMode === 'universe'){ layout(); resetView(); }
      }, 180);
    };
    sepIn.addEventListener('input', () => {
      UNI.sep = Math.max(0.3, Number(sepIn.value) / 100); showVals(); relayoutSoon();
    });
    gravIn.addEventListener('input', () => {
      UNI.grav = Math.max(0, Number(gravIn.value) / 100); showVals(); relayoutSoon();
    });
    uniBtn.addEventListener('click', e => {
      e.stopPropagation(); closeMapPanels(uniPanel); uniPanel.hidden = !uniPanel.hidden;
    });
    uniPanel.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { uniPanel.hidden = true; });
  }

  // Universe: what a galaxy represents. Relayouts, because it moves every star.
  const uniBy = document.getElementById('uni-by');
  if (uniBy) uniBy.addEventListener('change', () => {
    UNI.by = uniBy.value; saveUni();
    if (NODES.length && mapMode === 'universe'){ layout(); resetView(); }
  });

  // Solar: which playlist is the sun, and what decides an orbit.
  const solarPl = document.getElementById('solar-pl');
  if (solarPl) solarPl.addEventListener('change', async () => {
    SOLAR.playlist = solarPl.value; saveSolar();
    await loadSolarSet();
    if (NODES.length && mapMode === 'solar'){ layout(); resetView(); }
  });
  const solarBy = document.getElementById('solar-by');
  if (solarBy) solarBy.addEventListener('change', () => {
    SOLAR.by = solarBy.value; saveSolar();
    if (NODES.length && mapMode === 'solar'){ layout(); resetView(); }
  });

  /* ---- load + tab wiring ------------------------------------------- */
  // Refetches /map on every map-tab open ON PURPOSE: tracks analyzed since the
  // last open must show up without a page reload. Do NOT add fetch-once caching.
  /* Everything the map draws that does NOT live on a node: vibe membership
     (Universe can cluster by it), track and artist ratings (stars can be sized
     by them), and the playlist list (Solar picks one).

     All four are bulk endpoints and all four are optional -- each failure
     degrades one feature rather than breaking the map, which is why this
     settles rather than rejecting. A map that will not load because the
     ratings table is unreachable would be a bad trade. */
  async function loadOverlays(){
    const grab = url => fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
    const [mem, tr, ar] = await Promise.all([
      grab('/vibes/membership'), grab('/ratings'), grab('/artist-ratings'), refreshPlaylists(),
    ]);

    VIBES = Array.isArray(mem) ? mem : [];
    VIBE_OF = new Map();
    // First vibe by name wins a track that sits in several: it can only be in
    // one galaxy, and picking deterministically beats picking whatever the
    // query happened to return first.
    for (const v of VIBES) for (const h of v.hashes || []) if (!VIBE_OF.has(h)) VIBE_OF.set(h, v.name);

    TRACK_RATINGS = (tr && typeof tr === 'object') ? tr : {};
    ARTIST_RATINGS = {};
    if (Array.isArray(ar)) for (const a of ar){
      // Indexed under BOTH keys. The server normalises with Python's casefold()
      // and the client with toLowerCase(); they agree on ASCII but not on e.g.
      // "Straße" (casefold -> "strasse") or a Greek final sigma. Storing the
      // client-side key of the server's display name too means a lookup from a
      // track's artist string still resolves, instead of silently reading as
      // unrated -- which would look like the feature was off, not broken.
      ARTIST_RATINGS[a.key] = a;
      const alt = artistKey(a.artist);
      if (alt && alt !== a.key) ARTIST_RATINGS[alt] = a;
    }
    ratingsChanged();

    const uby = document.getElementById('uni-by');
    if (uby) uby.value = UNI.by;
    const sby = document.getElementById('solar-by');
    if (sby) sby.value = SOLAR.by;
  }

  /* Both playlist choosers -- Solar's sun and the filter panel's playlist facet
     -- rebuilt from PLAYLISTS, each keeping what it had selected.

     Rebuilt only when the LIST actually changed. Refreshing is cheap to ask for
     (see refreshPlaylists) and the guard means asking at the wrong moment --
     while the user has the dropdown open -- cannot yank the options out from
     under them. */
  function fillPlaylistPickers(){
    const sig = PLAYLISTS.map(pl => pl.id + ':' + pl.name).join('|');
    const opts = PLAYLISTS.map(pl =>
      `<option value="${pl.id}">${escapeHtml(pl.name)}</option>`).join('');
    const was = SOLAR.playlist;

    const sel = document.getElementById('solar-pl');
    if (sel && sel.dataset.sig !== sig){
      sel.dataset.sig = sig;
      sel.innerHTML = opts || '<option value="">no saved playlists yet</option>';
      if (SOLAR.playlist && PLAYLISTS.some(pl => String(pl.id) === String(SOLAR.playlist)))
        sel.value = SOLAR.playlist;
      else if (PLAYLISTS.length){ SOLAR.playlist = String(PLAYLISTS[0].id); sel.value = SOLAR.playlist; }
    }

    const flt = document.getElementById('flt-pl');
    if (flt && flt.dataset.sig !== sig){
      flt.dataset.sig = sig;
      const keep = FILT.playlist;
      flt.innerHTML = '<option value="">any playlist</option>' + opts;
      // A filter pointing at a playlist that has since been deleted falls back
      // to "any" rather than silently filtering against a list nothing matches.
      flt.value = (keep && PLAYLISTS.some(pl => String(pl.id) === String(keep))) ? keep : '';
    }
    return SOLAR.playlist !== was;      // the sun had to change: caller relays out
  }

  /* Re-read /playlists and refill the choosers.

     The list was built once, when the Map tab loaded. But playlists are saved
     and deleted from the Playlist panel, which slides over the map without
     reloading it -- so a playlist saved with the map open did not appear in
     Solar's picker until you left the tab and came back. With one playlist
     saved beforehand, that reads as "the app only lets me pick this one". */
  async function refreshPlaylists(){
    try{
      const r = await fetch('/playlists');
      if (!r.ok) return;
      const pls = await r.json();
      PLAYLISTS = Array.isArray(pls) ? pls : (pls && pls.playlists) || [];
      // Deleting the playlist Solar was drawing picks a different sun. Redraw,
      // rather than leaving a system on screen that no longer exists.
      if (fillPlaylistPickers() && mapMode === 'solar' && NODES.length){
        saveSolar();
        await loadSolarSet();
        layout(); resetView();
      }
    }catch(_){ /* keep the list we have */ }
  }
  // playlist.js fires this after every save and delete.
  document.addEventListener('vibe:playlists-changed', refreshPlaylists);

  /* The chosen playlist's tracks. Split in two so the network half can happen
     before NODES is swapped and the state half inside the swap -- see loadMap. */
  let solarPayload = null;

  /* One saved playlist's tracks, as {name, hashes: Set} -- or null if it no
     longer exists. r.ok first: a 404 body is still valid JSON ({"error": ...}),
     so parsing it blindly yielded an empty Set for a playlist that was gone,
     indistinguishable from an empty one. Tolerates both shapes the endpoint
     has used (`tracks` of objects, or bare `hashes`). */
  async function playlistHashSet(id){
    try{
      const r = await fetch(`/playlists/${id}`);
      if (!r.ok) return null;
      const d = await r.json();
      const hs = d.tracks || d.hashes || [];
      return { name: d.name || '',
               hashes: new Set(hs.map(x => (typeof x === 'string' ? x : x && x.hash)).filter(Boolean)) };
    }catch(_){ return null; }
  }

  async function fetchSolarPayload(){
    solarPayload = null;
    if (!SOLAR.playlist) return;
    const pl = PLAYLISTS.find(x => String(x.id) === String(SOLAR.playlist));
    const got = await playlistHashSet(SOLAR.playlist);
    if (got) solarPayload = { name: pl ? pl.name : got.name, hashes: got.hashes };
  }

  function solarSetFrom(payload){
    if (!payload){ SOLAR_SET = null; SOLAR_NAME = ''; return; }
    SOLAR_NAME = payload.name || '';
    SOLAR_SET = payload.hashes;
  }

  /* Fetch and apply in one step, for the callers that are not mid-swap. */
  async function loadSolarSet(){
    await fetchSolarPayload();
    solarSetFrom(solarPayload);
  }

  const loadEl = document.getElementById('map-loading');
  const phaseEl = document.getElementById('ml-phase');
  const fillEl = document.getElementById('ml-fill');
  const hintEl = document.getElementById('ml-hint');

  function loading(on, phase, frac){
    if (!loadEl) return;
    loadEl.hidden = !on;
    if (phase && phaseEl) phaseEl.textContent = phase;
    if (fillEl){
      // A negative fraction means "no idea yet" -- the bar goes indeterminate
      // rather than sitting at a dishonest 0%.
      const known = typeof frac === 'number' && frac >= 0;
      fillEl.classList.toggle('indet', !known);
      fillEl.style.width = known ? (Math.round(frac * 100) + '%') : '';
    }
  }

  /* fetch + JSON, reporting real download progress where the server gives us a
     Content-Length. Falls back to a plain .json() when it does not (a chunked
     or compressed response has no length to measure against). */
  async function fetchJsonProgress(url, onFrac){
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const total = Number(r.headers.get('Content-Length') || 0);
    if (!r.body || !total || !r.body.getReader) return r.json();
    const reader = r.body.getReader();
    const chunks = [];
    let got = 0;
    for (;;){
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      onFrac(Math.min(1, got / total));
    }
    const buf = new Uint8Array(got);
    let off = 0;
    for (const c of chunks){ buf.set(c, off); off += c.length; }
    return JSON.parse(new TextDecoder('utf-8').decode(buf));
  }

    /* The map is expensive to build and cheap to keep, so it is built once and
     kept, and each return to the Map asks the server whether the library it
     was built from is still the library that is there (see /map/stamp -- a
     revision counter, so the question costs microseconds). This replaced a
     scheme that watched every fetch for writes and kept an allow-list of the
     POSTs that were really reads; the allow-list had to grow for every new
     endpoint, and a miss was silent. The ↻ rebuild button is the escape hatch
     for anything that slips through. */
  /* The fingerprint the loaded map was built from -- see /map/stamp. */
  let MAP_STAMP = null;

  /* The digest of what the map would be built from right now, or null if the
     server can't say. */
  async function mapStamp(){
    try{
      const r = await fetch('/map/stamp');
      if (!r.ok) return null;
      const j = await r.json();
      return (j && j.stamp) || null;
    }catch(_){ return null; }
  }

  async function loadMap(force){
    /* Ask what the map would be keyed on before spending a rebuild. A match
       means the library the map was built from is the library that is there
       now, and there is nothing to rebuild -- only the overlays to re-read,
       which is four small requests. Most writes are not about what a track IS:
       rate a track, jump to another one, and the galaxy you were reading must
       not be torn down and rebuilt around you.

       The two overlays that DO move stars get placed again, because neither is in
       the stamp -- a vibe and a playlist are things you put tracks into, not part
       of what a track is. A vibe is a galaxy in Universe mode, so a membership
       change has to re-place; Solar draws one playlist and nothing else. Both are
       re-placed, which is the work those modes actually need -- not a whole map. */
    if (!force && NODES.length && MAP_STAMP){
      const now = await mapStamp();
      if (now && now === MAP_STAMP){
        const vibeSig = () => VIBES.map(v => v.name + '#' + (v.hashes || []).join(',')).join('|');
        const wasVibes = vibeSig();
        await loadOverlays();
        if (mapMode === 'solar') await loadSolarSet();
        if (mapMode === 'solar' || vibeSig() !== wasVibes) layout();
        countMap.textContent = mapCountText();
        return;
      }
    }
    try{
      // Phase 1 -- the server reads the library, classifies every track and
      // builds the response. Nothing is measurable until it starts sending.
      loading(true, 'Reading and sorting your library…', -1);
      countMap.textContent = 'loading…';
      const data = await fetchJsonProgress('/map', f => {
        loading(true, 'Downloading your library… ' + Math.round(f * 100) + '%', f);
      });
      /* NOTHING is published to NODES until layout() can follow immediately.

         The render loop is still running through every await below, and a node
         only gets its hue, phase and 3-D position in layout(). Assigning NODES
         first and awaiting afterwards let frame() iterate raw, un-laid-out
         nodes: undefined coordinates projected to NaN, an "hsla(NaN ...)" colour
         string, and addColorStop THROWS on that -- inside requestAnimationFrame,
         which killed the loop and left a black canvas. Staging the data in
         locals keeps the loop drawing the previous map until the new one is
         ready to replace it in one synchronous step. */
      const nextNodes = data.nodes || [];
      const nextEdges = data.edges || [];
      const nextStamp = data.stamp || null;
      if (!nextNodes.length){
        NODES = []; EDGES = []; MAP_STAMP = null;   // nothing to keep; look again next time
        loading(false);
        countMap.textContent='0 tracks -- scan some music first';
        return;
      }
      if (hintEl) hintEl.textContent = nextNodes.length.toLocaleString() + ' tracks';
      loading(true, 'Fetching your vibes and ratings…', 1);
      await loadOverlays();
      if (mapMode === 'solar') await fetchSolarPayload();
      // Phase 3 -- the client-side work: projection, clustering, label anchors.
      loading(true, 'Placing ' + nextNodes.length.toLocaleString() + ' stars…', 1);
      // Yield once so the phase actually paints before layout() blocks the
      // thread; without this the last message is never seen.
      await new Promise(r => setTimeout(r, 0));

      // --- the swap: no await between here and layout() ---
      NODES = nextNodes; EDGES = nextEdges; MAP_STAMP = nextStamp;
      byHash.clear();
      for (const n of NODES) byHash.set(n.hash, n);
      if (mapMode === 'solar') solarSetFrom(solarPayload);
      resize(); layout();
      loading(false);
    }catch(err){
      MAP_STAMP = null;                 // a half-built map must not look current
      loading(false);
      countMap.textContent='failed to load map';
      console.error('map load failed', err);
    }
  }

  const rebuildBtn = document.getElementById('map-rebuild');
  if (rebuildBtn) rebuildBtn.addEventListener('click', () => loadMap(true));
  function switchTo(viewName){
    tabsEl.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view===viewName));
    document.body.classList.toggle('view-guide', viewName === 'guide');
    document.body.classList.toggle('view-library', viewName === 'library');
    document.body.classList.toggle('view-options', viewName === 'options');
    document.body.classList.toggle('view-genres', viewName === 'genres');
    document.body.classList.toggle('view-vibes', viewName === 'vibes');
    const libView = document.getElementById('library-view');
    if (libView) libView.hidden = viewName !== 'library';
    const optView = document.getElementById('options-view');
    if (optView) optView.hidden = viewName !== 'options';
    const genView = document.getElementById('genres-view');
    if (genView) genView.hidden = viewName !== 'genres';
    const vibView = document.getElementById('vibes-view');
    if (vibView) vibView.hidden = viewName !== 'vibes';
    if (viewName === 'guide' && window.vibeLoadGuide) window.vibeLoadGuide();
    if (viewName === 'library' && window.vibeLoadLibrary) window.vibeLoadLibrary();
    if (viewName === 'options' && window.vibeLoadOptions) window.vibeLoadOptions();
    if (viewName === 'genres' && window.vibeLoadGenres) window.vibeLoadGenres();
    if (viewName === 'vibes' && window.vibeLoadVibes) window.vibeLoadVibes();
    showMap(viewName === 'map');
    const hash = viewName==='map' ? '#map' : (viewName==='guide' ? '#guide'
                 : (viewName==='library' ? '#library'
                 : (viewName==='vibes' ? '#vibes'
                 : (viewName==='genres' ? '#genres'
                 : (viewName==='options' ? '#options'
                 : (viewName==='list' ? '#analyzer' : '#'))))));
    try{ history.replaceState(null,'', hash); }catch(_){}
  }
  function showMap(on){
    const deepHash = location.hash;
    document.body.classList.toggle('view-map', on);
    document.getElementById('map-view').hidden = !on;
    if (on){
      loadMap().then(() => {
        resize();
        // Framing the whole library is for arriving with nothing in particular
        // to look at. Arriving to see one track, it is the wrong place to start.
        const want = /^#map=(.+)$/.exec(deepHash);
        if (!(want && byHash.has(want[1]))) fitView();
        startLoop();
        // the filter choosers are built from the loaded library, so they can only
        // be populated once the nodes exist
        if (window.mapFilterPopulate) window.mapFilterPopulate();
        if (window.mapGenrePopulate) window.mapGenrePopulate();
        if (want && byHash.has(want[1])) selectNode(want[1], true);   // cut, don't fly
      });
    } else { stopLoop(); }
  }
  tabsEl.addEventListener('click', e => {
    const b = e.target.closest('.tab'); if (!b) return; switchTo(b.dataset.view);
  });
  if (location.hash === '#universe' || location.hash === '#galaxy'
      || location.hash === '#tree' || location.hash === '#solar'){
    // '#galaxy' kept as an alias: the mode was renamed to 'universe', and old
    // bookmarks should not break.
    mapMode = location.hash === '#galaxy' ? 'universe' : location.hash.slice(1);
    modeEl && modeEl.querySelectorAll('.mm').forEach(m => m.classList.toggle('active', m.dataset.mode===mapMode));
    // Re-sync AFTER the hash has decided the mode. The call at definition time
    // runs while mapMode is still the 'regions' default, so a deep link to
    // #solar or #universe would render that mode with its own controls hidden.
    syncModeControls();
  }
  // Boot view. Library leads the tab bar and is the default landing view: an
  // established library is the thing you actually came back for. A deep link in
  // the hash still wins, and an empty library shows its own "go analyse
  // something" call to action rather than a blank table.
  {
    const h = location.hash;
    const boot =
      (h === '#map' || h.startsWith('#map=') || h === '#universe' || h === '#galaxy'
        || h === '#tree' || h === '#solar') ? 'map'
      : h === '#guide'   ? 'guide'
      : h === '#genres'  ? 'genres'
      : h === '#vibes'   ? 'vibes'
      : h === '#options' ? 'options'
      : (h === '#list' || h === '#analyzer') ? 'list'
      : 'library';
    switchTo(boot);
  }

  let rz;
  window.addEventListener('resize', () => {
    if (!document.body.classList.contains('view-map') || !NODES.length) return;
    clearTimeout(rz); rz = setTimeout(resize, 150);
  });

  // The key notation changed under an open map: the hover label repaints itself
  // every frame, but a popup already on screen would keep the old notation until
  // it was closed and reopened.
  window.vibeKeyViewChanged = () => {
    if (popEl && !popEl.hidden && selHash && byHash.has(selHash)) openPopup(byHash.get(selHash));
  };

  // let other UI (the review-reads panel) jump to a track on the map
  window.vibeMapGoto = (hash) => {
    try{ history.replaceState(null, '', '#map=' + hash); }catch(_){}
    switchTo('map');
  };
})();

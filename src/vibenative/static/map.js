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
  const FILT_EMPTY = { artist:'', key:'', style:'', tags:[], playlist:null,
                       bpm:[null,null], len:[null,null] };
  let FILT = JSON.parse(JSON.stringify(FILT_EMPTY));
  let playlistHashes = null;        // Set of hashes for the chosen playlist, or null
  // Hovered chip -> its tracks twinkle as a preview of what clicking would show.
  // {kind, value} rather than a bare tag: genre and artist chips preview the same
  // way, and they are the ones you can actually see on a library with no tags.
  let HL = null;

  // The one place that answers "does this track match that chip". Both the hover
  // preview and the filter go through it, so the twinkle can never promise a
  // different set than the click delivers -- which was the whole point of having
  // a preview.
  /* The artists credited on a track. The server splits the credit string (see
     vibenative/artists.py); this is the accessor everything else goes through
     so a node from an older payload without the split still behaves. */
  function artistsOf(n){
    if (n.artists && n.artists.length) return n.artists;
    return n.artist ? [n.artist] : [];
  }

  function nodeHas(n, kind, value){
    if (!value) return false;
    if (kind === 'tag')    return (n.tags || []).includes(value);
    // Substring over the SPLIT credits, matching how FILT.artist is applied, so
    // hovering an artist chip previews exactly the tracks clicking it filters to.
    if (kind === 'artist'){
      const v = String(value).toLowerCase();
      return artistsOf(n).some(a => a.toLowerCase().includes(v));
    }
    if (kind === 'style')  return n.style === value || (n.styles || []).includes(value);
    return false;
  }
  // Set by the filter panel so anything that changes FILT can refresh the
  // controls and the counter. A no-op until the panel has been wired.
  let syncFilterUI = () => {};

  const filtActive = () =>
    !!(FILT.artist || FILT.key || FILT.style || FILT.tags.length || FILT.playlist
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
    if (FILT.artist && !artistsOf(n).some(a => a.toLowerCase().includes(FILT.artist))) return false;
    if (FILT.key && n.camelot !== FILT.key) return false;
    // A track counts as its genre even when that genre is only a runner-up read,
    // so filtering to House finds the tracks that are partly House too.
    if (FILT.style && !nodeHas(n, 'style', FILT.style)) return false;
    // tags are AND: picking two means "has both", which is how you narrow down
    if (FILT.tags.length && !FILT.tags.every(t => (n.tags || []).includes(t))) return false;
    if (playlistHashes && !playlistHashes.has(n.hash)) return false;
    if (!inRange(n.bpm, FILT.bpm)) return false;
    if (!inRange(n.duration, FILT.len)) return false;
    return true;
  }
  const tipEl = document.getElementById('map-tip');
  let anim = null;                         // camera tween
  const proj = new Map();                  // hash -> {sx,sy,z,r} for this frame
  const CAM = 2.7;                         // camera distance (world units)

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
  function hueOf(fam){
    let h = 0; for (let i=0;i<fam.length;i++) h = (h*31 + fam.charCodeAt(i)) | 0;
    return ((h % 360) + 360) % 360;
  }
  // user-customisable per-family base hue (persisted); falls back to the hash hue
  let FAM_HUE = {};
  try { FAM_HUE = JSON.parse(localStorage.getItem('vibeFamHue') || '{}') || {}; } catch(_){ FAM_HUE = {}; }
  let legendCollapsed = false;
  try { legendCollapsed = localStorage.getItem('vibeLegend') === 'off'; } catch(_){ /* private mode */ }
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
    // flat: draw nodes and links as plain 2-D marks -- no depth shading on the
    // dots, no depth fade on the links. The layout still comes from the 3-D
    // positions (that's what the clustering means); only the *rendering* of
    // depth is dropped, which is what makes a flat map readable for picking.
    flat:false,
    // hideText   kill every label the canvas draws, in one switch. Distinct
    //            from unticking genre+subgenre: it also drops the leader lines
    //            and the solar ring labels, so the view is purely the stars.
    // twinkle    'off' | 'subtle' | 'flicker'. Subtle is the original gentle
    //            breathing; flicker is a real scintillation, closer to how a
    //            star actually behaves through atmosphere.
    // leaders    draw the line tying a moved label back to its cluster
    // labelStyle 'halo' (stroked outline) or 'pill' (solid rounded plate)
    // glow       render nodes as lit spheres with a corona instead of flat
    //            discs. Ignored in flat (2-D) mode, which is the point of it.
    // sizeByRating / useArtistRating / unratedScale -- see ratingBoost()
    hideText:false, twinkle:'subtle', leaders:false, labelStyle:'halo',
    glow:true, sizeByRating:false, useArtistRating:true, unratedScale:0.8,
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
  const keyfmt = n => n.camelot
    ? `${n.camelot} ${n.key||''} ${(n.scale||'').slice(0,3)}`.trim()
    : (n.key ? `${n.key} ${(n.scale||'').slice(0,3)}`.trim() : '--');

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

  /* Must match ratings.artist_key() on the server: casefolded, whitespace
     collapsed. If these two ever disagree the map silently sizes every star as
     unrated, which looks like the feature is off rather than broken. */
  const artistKey = name => String(name || '').split(/\s+/).filter(Boolean).join(' ').toLowerCase();

  function starsFor(n){
    const t = (TRACK_RATINGS[n.hash] || {}).stars || 0;
    if (!LBL.useArtistRating) return t;
    const a = (ARTIST_RATINGS[artistKey(n.artist)] || {}).stars || 0;
    // The better of the two, not the average: a 5-star track by an unrated
    // artist is still a 5-star track, and averaging would bury it.
    return Math.max(t, a);
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
  const CORE_SCALE = 1.45;                          // lit body vs. the old flat dot
  const GLOW_SCALE = 2.6;                           // corona reach vs. core radius
  // Above this on-screen core radius the sprite is being magnified past its own
  // resolution and goes soft, so those few stars are drawn with a real gradient
  // instead. The threshold is in CSS pixels and deliberately low: at any given
  // moment only a handful of stars are this big, so the per-frame gradient cost
  // is negligible, while every small star still comes from the cache.
  const CRISP_ABOVE = 9;
  // How much of the corona is added per star. Deliberately small: the corona is
  // drawn with 'lighter', which ACCUMULATES, and a dense cluster stacks hundreds
  // of them on the same pixels. At full strength that saturates to a solid white
  // blob and the cluster stops showing any structure at all -- which is exactly
  // what a first pass at this did.
  const GLOW_ALPHA = 0.16;

  /* Two sprites per colour, because they have to composite differently.

     `core` is the lit body: a small sphere shaded from a white-hot centre out to
     the genre's colour, drawn normally (source-over) so that overlapping stars
     occlude rather than sum. This is what keeps a dense cluster legible.

     `corona` is the halo, drawn additively at low alpha so that a handful of
     nearby stars genuinely brighten each other -- the part that reads as light
     being emitted -- without a crowd blowing out to white. */
  function starSprite(hue, sat, light, kind){
    const h = Math.round(hueOk(hue) / 6) * 6;
    const sa = Math.round(pctOk(sat, 64) / 8) * 8;
    const li = Math.round(pctOk(light, 50) / 6) * 6;
    const key = kind + '|' + h + '|' + sa + '|' + li;
    let cv = STAR_SPRITES.get(key);
    if (cv) return cv;
    cv = document.createElement('canvas');
    cv.width = cv.height = SPRITE_R * 2;
    const g = cv.getContext('2d');
    const grd = g.createRadialGradient(SPRITE_R, SPRITE_R, 0, SPRITE_R, SPRITE_R, SPRITE_R);
    if (kind === 'core'){
      // Opaque out to ~55% of the sprite, then a short soft edge. The soft edge
      // is what makes it read as a sphere instead of a flat disc; making it any
      // longer just looks out of focus.
      grd.addColorStop(0.00, `hsla(${h} ${Math.min(100, sa + 26)}% ${clamp(li + 34, 44, 96)}% / 1)`);
      grd.addColorStop(0.30, `hsla(${h} ${Math.min(100, sa + 12)}% ${clamp(li + 14, 26, 84)}% / 1)`);
      grd.addColorStop(0.62, `hsla(${h} ${sa}% ${li}% / 0.95)`);
      grd.addColorStop(0.86, `hsla(${h} ${sa}% ${clamp(li - 6, 10, 80)}% / 0.45)`);
      grd.addColorStop(1.00, `hsla(${h} ${sa}% ${clamp(li - 8, 8, 78)}% / 0)`);
    } else {
      grd.addColorStop(0.00, `hsla(${h} ${Math.min(100, sa + 14)}% ${clamp(li + 20, 34, 90)}% / 0.85)`);
      grd.addColorStop(0.35, `hsla(${h} ${sa}% ${li}% / 0.34)`);
      grd.addColorStop(1.00, `hsla(${h} ${sa}% ${li}% / 0)`);
    }
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
    MAXR = 0.5;
    for (const n of members){ const d = Math.hypot(n.x3, n.y3, n.z3); if (d > MAXR) MAXR = d; }
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
  let UNI = { by: 'arch', sep: 1 };
  try { UNI = Object.assign(UNI, JSON.parse(localStorage.getItem('vibeUniverse') || '{}') || {}); } catch(_){}
  const saveUni = () => { try{ localStorage.setItem('vibeUniverse', JSON.stringify(UNI)); }catch(_){} };
  let PLAYLISTS = [];                 // [{id, name}] saved playlists, for Solar
  let VIBES = [];                     // [{id, name, hashes}] from /vibes/membership
  let VIBE_OF = new Map();            // hash -> vibe name (first vibe wins)

  /* Which galaxy a track belongs to.

     A track can sit in several vibes at once, but it can only be in one place
     on screen, so the FIRST vibe by name owns it. Deterministic, and stated
     rather than silently picking whichever the query returned first. */
  function uniGroupOf(n){
    if (UNI.by === 'vibe') return VIBE_OF.get(n.hash) || UNI_FIELD;
    return n.fam || 'Other';
  }

  /* One anchor per galaxy, on a Fibonacci sphere so they distribute evenly
     rather than banding at the poles. The biggest galaxy takes the centre --
     it is the thing you orbit by default -- and the rest ring it. */
  function uniAnchors(){
    const count = {};
    for (const n of NODES){ const g = uniGroupOf(n); count[g] = (count[g]||0)+1; }
    const names = Object.keys(count).sort((a,b)=>count[b]-count[a]);
    if (!names.length) return {};
    const out = {};
    // Tighter members + wider anchors as separation rises; at sep=0 the galaxies
    // collapse back into the single sonic cloud the old galaxy view drew.
    const R = 2.1 * UNI.sep;
    const spread = clamp(1 - 0.55*UNI.sep, 0.32, 1);
    out[names[0]] = { x:0, y:0, z:0, spread };
    const rest = names.slice(1);
    rest.forEach((g,i) => {
      const k = i + 0.5;
      const phi = Math.acos(1 - 2*k/rest.length);
      const th  = Math.PI * (1 + Math.sqrt(5)) * k;
      out[g] = { x:R*Math.cos(th)*Math.sin(phi), y:R*Math.sin(th)*Math.sin(phi),
                 z:R*Math.cos(phi), spread };
    });
    return out;
  }

  /* ---- build 3-D positions for the current mode -------------------- */
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
      n.hue = sh.h; n.sat = sh.s; n.dl = sh.dl;
      byHash.set(n.hash, n);
    }
    /* n.grp is what the BIG labels name, which is not always the genre.

       In the Universe clustered by vibe, a galaxy IS a vibe -- so labelling
       those galaxies "HOUSE" and "TECHNO" describes the wrong thing entirely.
       The stars keep their genre colours (that is still what they are), but the
       label layer, the legend counts and the click-to-fly targets all follow the
       group the layout actually used. */
    const byVibe = (mapMode === 'universe' && UNI.by === 'vibe');
    for (const n of NODES) n.grp = byVibe ? uniGroupOf(n) : n.fam;
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
      const anchors = uniAnchors();
      for (const n of NODES){
        const r = rng(n.hash);
        const a = anchors[uniGroupOf(n)] || anchors[UNI_FIELD] || {x:0,y:0,z:0,spread:1};
        // spread<1 pulls a galaxy's members in around its anchor so the gaps
        // between galaxies read as empty space rather than one continuous fog.
        n.x3 = a.x + (clamp((n.e?n.e[0]:0)/p[0], -1.3, 1.3) + (r()-0.5)*0.04) * a.spread;
        n.y3 = a.y + (clamp((n.e?n.e[1]:0)/p[1], -1.3, 1.3) + (r()-0.5)*0.04) * a.spread;
        n.z3 = a.z + (clamp((n.e?n.e[2]:0)/p[2], -1.3, 1.3) + (r()-0.5)*0.04) * a.spread;
        n.ph = r()*6.28;
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
    MAXR = 0.5;
    for (const n of NODES){ const d = Math.hypot(n.x3, n.y3, n.z3); if (d > MAXR) MAXR = d; }

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
      if (mapMode === 'universe' && UNI.by === 'vibe'){
        STYLE_CENTROIDS = {};
        buildLegend();
        countMap.textContent = mapCountText();
        return;
      }
      for (const n of NODES){
        const key = `${n.fam}||${n.style || n.fam}`;
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
    const byVibe = (mapMode === 'universe' && UNI.by === 'vibe');
    return `${n(NODES.length, 'track')} · `
      + `${byVibe ? n(FAMS.length, 'vibe') : n(FAMS.length, 'genre')} · ${mapMode}`;
  }

  function buildLegend(){
    // Subgenre breakdown per group. n.grp is the genre family in every mode
    // except the Universe clustered by vibe, where it is the vibe -- and there
    // the legend must list the same things the map labels, or clicking a legend
    // row would filter on a name nothing on screen carries.
    const subs = {};
    for (const n of NODES){ const st = n.style || n.fam;
      (subs[n.grp] = subs[n.grp] || {})[st] = (subs[n.grp][st] || 0) + 1; }
    const groups = FAMS.map(f => {
      const active = filterFam === f ? ' active' : '';
      const head = `<span class="leg leg-fam${active}" data-fam="${escapeHtml(f)}">`
        + `<span class="dot" title="click to recolour this genre" style="background:${famCss(f)}"></span>`
        + `<b>${escapeHtml(f)}</b>&nbsp;${COUNTS[f]}</span>`;
      // a lone subgenre identical to the family isn't really a "sub" -> skip it
      const list = Object.entries(subs[f] || {}).filter(([st]) => st !== f).sort((a,b) => b[1]-a[1]);
      if (!list.length) return `<div class="leg-group">${head}</div>`;
      const shown = list.slice(0, 10), more = list.length - shown.length;
      const subHtml = shown.map(([st, c]) => {
        const sh = styleShade(f, st);
        const col = `hsl(${sh.h} ${clamp(sh.s, 40, 88)}% ${clamp(58 + sh.dl, 44, 70)}%)`;
        return `<span class="leg-sub" data-fam="${escapeHtml(f)}" data-style="${escapeHtml(st)}"`
          + ` title="zoom to ${escapeHtml(st)}"><span class="sdot" title="click to recolour this subgenre"`
          + ` style="background:${col}"></span>${escapeHtml(st)} ${c}</span>`;
      }).join('') + (more > 0 ? `<span class="leg-more">+${more} more</span>` : '');
      return `<div class="leg-group">${head}<div class="leg-subs">${subHtml}</div></div>`;
    }).join('');
    legendEl.innerHTML =
      `<button class="leg-toggle" type="button" title="show / hide the legend">&#9698; `
      + `${(mapMode === 'universe' && UNI.by === 'vibe') ? 'vibes' : 'genres'}</button>`
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
    stopPreview();
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
    if (n.camelot) bits.push(escapeHtml(n.camelot));
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
    if (mapMode === 'solar' && spinSpeed > 0 && !dragging){
      const st = t * (spinSpeed / 0.0006) * 0.06;
      for (const n of NODES) if (n.orb) solarPlace(n, st);
    }
    if (spinSpeed > 0 && !anim && !dragging && mapMode !== 'solar') rot.y += spinSpeed;
    // orbit centre (eased): a clicked genre's centroid, else the selected track,
    // else the origin. So clicking a genre orbits AROUND that cluster.
    const sel = selHash ? byHash.get(selHash) : null;
    const tx = famPivot ? famPivot.x : (sel ? sel.x3 : 0);
    const ty = famPivot ? famPivot.y : (sel ? sel.y3 : 0);
    const tz = famPivot ? famPivot.z : (sel ? sel.z3 : 0);
    pivot.x += (tx - pivot.x) * 0.12;
    pivot.y += (ty - pivot.y) * 0.12;
    pivot.z += (tz - pivot.z) * 0.12;
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
      // Depth drives dot brightness, alpha, size and the label fade. Pinning it
      // to 1 in flat mode neutralises all of those from one place, instead of
      // special-casing every draw site. Layout still comes from the 3-D
      // positions -- only the depth *cues* go away.
      const depth = LBL.flat ? 1 : clamp((z2+1.15)/2.3, 0, 1);
      const rp = LBL.flat ? 1 : persp;          // flat: every dot the same size
      const r = clamp(4.2*rp*Math.sqrt(view.zoom)*ratingBoost(n), 1.2, 46);
      // Cull anything whose glow cannot reach the viewport. At high zoom most
      // of the library sits off-screen, and blitting it was pure waste.
      const reach = r * GLOW_SCALE + 2;
      if (sxp < -reach || sxp > W + reach || syp < -reach || syp > H + reach) continue;
      visFam[n.grp] = (visFam[n.grp] || 0) + 1;
      const sk = `${n.fam}||${n.style || n.fam}`;
      visSub[sk] = (visSub[sk] || 0) + 1;
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
    for (const h of order){
      const p = proj.get(h), n = p.node;
      // Baseline shimmer, plus a much stronger pulse for tracks matching the
      // tag currently under the cursor -- the "what would this filter show me"
      // preview. Phase-offset per node so they sparkle rather than strobe in
      // unison, which reads as a glitch instead of a highlight.
      const lit = HL && nodeHas(n, HL.kind, HL.value);
      // Three twinkle modes. 'flicker' beats two detuned sines together so the
      // field scintillates irregularly instead of every star breathing on the
      // same cycle, which reads as a pulsing grid rather than a sky.
      const tw = lit
        ? 1.25 + 0.55*Math.sin(t*7 + n.ph*3)
        : LBL.twinkle === 'off' ? 1
        : LBL.twinkle === 'flicker'
          ? 0.70 + 0.30*Math.sin(t*6.1 + n.ph*5.3) + 0.16*Math.sin(t*2.3 + n.ph*11.7)
          : 0.9 + 0.1*Math.sin(t*1.6 + n.ph);
      const light = (26 + 44*p.depth) * tw;
      let compatible = false, dim = 1;
      if (harmonicOn && h !== selHash){         // harmonic mixing: mute non-matches
        compatible = keyCompatible(selNode.camelot, n.camelot) && bpmCompatible(selNode.bpm, n.bpm);
        dim = compatible ? 1 : 0.1;
      }
      ctx.globalAlpha = (0.45 + 0.55*p.depth) * dim;
      const li = clamp(light + (n.dl||0), 16, 84);
      if (!Number.isFinite(n.hue) || !Number.isFinite(li)) warnShade('node', n);
      if (LBL.glow && !LBL.flat){
        // A lit sphere, not a flat disc -- this is what actually separates the
        // 3-D view from the 2-D one, which previously differed only in size and
        // transparency. Corona first (additive, faint), then the solid core on
        // top, so a crowded cluster keeps its shape instead of saturating.
        const prevA = ctx.globalAlpha;
        const gr = p.r * GLOW_SCALE;
        // The corona is skipped on the smallest, faintest stars. At that size it
        // is under a pixel of visible contribution but still a full blit, and on
        // a 3000-track map that is thousands of wasted draws per frame.
        if (p.r > 1.8 && prevA > 0.12){
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = prevA * GLOW_ALPHA;
          ctx.drawImage(starSprite(n.hue, n.sat||64, li, 'corona'), p.sx-gr, p.sy-gr, gr*2, gr*2);
          ctx.globalCompositeOperation = 'source-over';
          ctx.globalAlpha = prevA;
        }
        const cr = p.r * CORE_SCALE;
        if (cr > CRISP_ABOVE){
          // Big enough that the 64px sprite would visibly blur -- shade it
          // directly. Same stops as the sprite, so a star does not change
          // appearance as it crosses the threshold. Same coercion too: these
          // strings reach addColorStop, which throws on a NaN component.
          const hh = hueOk(n.hue), ss = pctOk(n.sat, 64), ll = pctOk(li, 50);
          const g = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, cr);
          g.addColorStop(0.00, `hsla(${hh} ${Math.min(100, ss+26)}% ${clamp(ll+34,44,96)}% / 1)`);
          g.addColorStop(0.30, `hsla(${hh} ${Math.min(100, ss+12)}% ${clamp(ll+14,26,84)}% / 1)`);
          g.addColorStop(0.62, `hsla(${hh} ${ss}% ${ll}% / 0.95)`);
          g.addColorStop(0.86, `hsla(${hh} ${ss}% ${clamp(ll-6,10,80)}% / 0.45)`);
          g.addColorStop(1.00, `hsla(${hh} ${ss}% ${clamp(ll-8,8,78)}% / 0)`);
          ctx.fillStyle = g;
          ctx.beginPath(); ctx.arc(p.sx, p.sy, cr, 0, 6.2832); ctx.fill();
        } else {
          ctx.drawImage(starSprite(n.hue, n.sat||64, li, 'core'), p.sx-cr, p.sy-cr, cr*2, cr*2);
        }
      } else {
        ctx.beginPath(); ctx.arc(p.sx, p.sy, p.r, 0, 6.2832);
        ctx.fillStyle = `hsl(${hueOk(n.hue)} ${pctOk(n.sat, 64)}% ${pctOk(li, 50)}%)`;
        ctx.fill();
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
    if (mapMode === 'solar'){
      // Solar draws its own sun, orbits and ring labels, and then stops. The
      // genre-label section below is not merely redundant here -- it iterates
      // FAMS against CENTROIDS, which solarLayout() empties, so entering it
      // threw on undefined and took the whole render loop down with it.
      drawSolarChrome(t, projPtFactory(cy,sy,cx,sx,cxp,cyp,DISP));
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
    const projPt = c => {
      const ax = c.x-pivot.x, ay = c.y-pivot.y, az = c.z-pivot.z;
      const x = ax*cy + az*sy, z = -ax*sy + az*cy;
      const y2 = ay*cx - z*sx, z2 = ay*sx + z*cx;
      const persp = CAM/(CAM - z2);
      return { sx: cxp + x*persp*DISP, sy: cyp + y2*persp*DISP, z2, persp };
    };
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
    for (const f of FAMS){
      if (!LBL.showFam) break;                          // family labels hidden
      if (LBL.onlyFam && f !== LBL.onlyFam) continue;   // isolate one genre's label
      if (filterFam && f !== filterFam) continue;
      // No stars from this genre on screen -> no label. Chips, facet filters
      // and culling all feed this, so the labels always describe what is
      // actually drawn.
      if (!visFam[f]) continue;
      const p = projPt(CENTROIDS[f]);
      if (p.persp <= 0) continue;
      const depth = clamp((p.z2+1.15)/2.3, 0, 1);
      const alpha = (0.52 + 0.32*depth) * (1 - 0.9*(famFocus[f]||0)) * LBL.opacity;   // fade when focused
      if (alpha < 0.04) continue;
      const fs = Math.min(21, 13 + CENTROIDS[f].n*0.3) * clamp(p.persp, 0.9, 1.25) * LBL.size;
      const text = (LBL.counts ? `${f} ${CENTROIDS[f].n}` : f).toUpperCase();
      ctx.font = `800 ${fs}px Syne, sans-serif`;
      fl.push({ f, text, ax:p.sx, ay:p.sy, lx:p.sx, ly:p.sy,
                hw:ctx.measureText(text).width/2 + 5, hh:fs*0.62, fs, alpha, depth });
    }
    // declutter: keep only the N biggest genre labels (by track count)
    if (LBL.maxFam > 0 && fl.length > LBL.maxFam){
      fl.sort((a,b) => (CENTROIDS[b.f].n||0) - (CENTROIDS[a.f].n||0));
      fl.length = LBL.maxFam;
    }
    let cx0 = 0, cy0 = 0;
    for (const l of fl){ cx0 += l.ax; cy0 += l.ay; }
    if (fl.length){
      cx0 /= fl.length; cy0 /= fl.length;
      let spread = 0;                                   // how clustered are the anchors?
      for (const l of fl) spread += Math.hypot(l.lx-cx0, l.ly-cy0);
      spread /= fl.length;
      if (spread < 90){
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
      ctx.drawImage(starSprite(44, 92, 62, 'corona'), c0.sx-sr*2.4, c0.sy-sr*2.4, sr*4.8, sr*4.8);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      ctx.drawImage(starSprite(46, 95, 66, 'core'), c0.sx-sr, c0.sy-sr, sr*2, sr*2);
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
      if (mapMode === 'tree' || panning){ view.panx += dx; view.pany += dy; }
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
        + `${n.bpm?Math.round(n.bpm):'--'} bpm · ${escapeHtml(n.camelot||'--')}</span>`;
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
    const nz = clamp(view.zoom * (e.deltaY<0 ? 1.14 : 1/1.14), 0.3, 60);
    const f = nz / view.zoom;                          // actual factor after clamp
    // keep the point under the cursor fixed -> zoom into wherever you're looking
    view.panx = mx - (mx - (W/2 + view.panx)) * f - W/2;
    view.pany = my - (my - (H/2 + view.pany)) * f - H/2;
    view.zoom = nz;
  }, { passive:false });

  /* ---- select + camera fly ----------------------------------------- */
  /* ---- select-to-preview: sample-play a selected track's "drop" ----------
     Selecting a node auto-plays a short clip from its first big energy jump (the
     drop) — or the middle as a fallback — on a DEDICATED audio element, and
     pauses the bottom Now Playing bar so the two never overlap. */
  const PREVIEW_SECONDS = 22;
  const PREV = { audio: new Audio(), token: 0, stopAt: 0, url: null };
  PREV.audio.preload = 'auto';
  PREV.audio.addEventListener('timeupdate', () => {
    if (PREV.stopAt && PREV.audio.currentTime >= PREV.stopAt) stopPreview();
  });
  function stopPreview(){
    PREV.token++;                       // invalidate any in-flight start
    PREV.stopAt = 0;
    try { PREV.audio.pause(); } catch(_){ /* not started */ }
  }
  window.mapStopPreview = stopPreview;   // let the popup's ▶ play hand off cleanly

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

  async function previewTrack(n){
    stopPreview();
    // Tree mode used to be excluded here because nothing in it was selectable.
    // The tree card's "sample" button is, so the only thing left to reject is
    // an absent track.
    if (!n) return;
    const my = PREV.token;                          // stopPreview() just bumped it
    if (typeof PLAYER !== 'undefined'){ try { PLAYER.audio.pause(); } catch(_){ /* none */ } }
    // resolve a source: the server copy, else a persisted dropped-file handle
    let src = null;
    if (PREV.url){ URL.revokeObjectURL(PREV.url); PREV.url = null; }
    if (n.a) src = '/audio/' + n.hash;
    else if (typeof FSH !== 'undefined' && FSH.supported){
      const f = await FSH.file(n.hash);
      if (my !== PREV.token) return;                // a newer selection won
      if (f){ src = URL.createObjectURL(f); PREV.url = src; }
    }
    if (!src) return;                               // nothing playable — stay silent
    const start = await dropStart(n.hash, n.duration);
    if (my !== PREV.token) return;
    PREV.audio.src = src;
    const begin = () => {
      if (my !== PREV.token) return;
      try { PREV.audio.currentTime = start; } catch(_){ /* seek after load */ }
      PREV.stopAt = start + PREVIEW_SECONDS;
      PREV.audio.play().catch(() => {});
    };
    if (PREV.audio.readyState >= 1) begin();
    else PREV.audio.addEventListener('loadedmetadata', begin, { once: true });
  }

  function selectNode(hash){
    const n = byHash.get(hash); if (!n) return;
    selHash = hash; famPivot = null; focusedFam = null;   // orbit this track, not a genre
    if (mapMode !== 'tree'){
      // the pivot eases to this track (frame loop), so it becomes the orbit
      // centre. keep the rotation, just zoom in a bit and recentre the view.
      anim = { f:{rx:rot.x,ry:rot.y,z:view.zoom,px:view.panx,py:view.pany},
               t:{rx:rot.x, ry:rot.y, z:Math.max(1.9,view.zoom), px:0, py:0},
               t0:performance.now(), dur:600 };
    }
    openPopup(n);
    previewTrack(n);                                  // auto-sample the drop
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
      <span class="pop-fam" style="background:${famCss(n.fam)}">${escapeHtml(n.fam)}</span>
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
      <div class="pop-rate">
        <div class="rate-stars" role="group" aria-label="star rating">
          ${[1,2,3,4,5].map(i=>`<button class="rate-star" data-s="${i}"
            title="${i} star${i>1?'s':''}" aria-label="${i} star${i>1?'s':''}">&#9733;</button>`).join('')}
          <button class="rate-clear" data-s="0" title="clear rating">&#10005;</button>
        </div>
        <select class="rate-grade" title="letter grade (exports into the Rekordbox comment)">
          <option value="">grade</option>
          ${['A','B','C','D','F'].map(g=>`<option value="${g}">${g}</option>`).join('')}
        </select>
        <input class="rate-note" type="text" placeholder="note (exports as “A - note”)"
               autocomplete="off" spellcheck="false" maxlength="1000">
      </div>
      ${artistsOf(n).length ? `<div class="pop-h">rate the artist</div>
      <div class="arate-pick">${artistsOf(n).map((a, i) =>
        `<button class="arate-who${i === 0 ? ' on' : ''}" data-a="${escapeHtml(a)}"
          >${escapeHtml(a)}</button>`).join('')}</div>
      <div class="pop-rate pop-rate-artist">
        <div class="arate-stars" role="group" aria-label="artist star rating">
          ${[1,2,3,4,5].map(i=>`<button class="arate-star rate-star" data-s="${i}"
            title="${i} star${i>1?'s':''}" aria-label="${i} star${i>1?'s':''}">&#9733;</button>`).join('')}
          <button class="arate-clear rate-clear" data-s="0" title="clear artist rating">&#10005;</button>
        </div>
        <select class="arate-grade rate-grade" title="letter grade for the artist">
          <option value="">grade</option>
          ${['A','B','C','D','F'].map(g=>`<option value="${g}">${g}</option>`).join('')}
        </select>
        <input class="arate-note rate-note" type="text" placeholder="note about this artist"
               autocomplete="off" spellcheck="false" maxlength="1000">
      </div>
      <div class="pop-ratehint">Rates the selected artist across your whole library, not just
        this track.${artistsOf(n).length > 1 ? ' Pick which one above.' : ''}</div>` : ''}
      <div class="pop-omit-row">
        <button class="pop-adjust" title="nudge how much of each genre this track is — keeps the rest of the read">⚖ adjust</button>
        <button class="pop-override" title="set the genre yourself (persists + saved for training)">✎ override</button>
        <button class="pop-omit" title="delete this track's analysis (audio file untouched)">✕ omit</button>
      </div>
      <div class="pop-adj" hidden>
        <div class="ovr-h">how much of each genre is this?</div>
        <div class="adj-rows"><span class="pop-bar">…</span></div>
        <div class="ovr-typed">
          <input class="adj-add-in" type="text" placeholder="add a genre it missed…" list="ovr-genre-list"
                 autocomplete="off" spellcheck="false">
          <button class="adj-add">add</button>
          <button class="adj-close" title="done">✕</button>
        </div>
        <div class="ovr-hint">Nudges the read instead of replacing it — use <b>override</b> if it's flat wrong.</div>
      </div>
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
      stopPreview();                                 // hand off the sample to full playback
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
    wireRating(popEl, n.hash);
    {
      // A collaboration has several artists and each is rated separately, so the
      // widget is bound to whichever is picked and re-bound when that changes.
      const who = [...popEl.querySelectorAll('.arate-who')];
      const bind = name => wireArtistRating(popEl, name);
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
  function wireRating(root, hash){
    // Scoped to the TRACK block. The artist widget below reuses `rate-star`,
    // `rate-grade` and `rate-note` for styling, so an unscoped query returned
    // ten buttons instead of five and painted both rows from one hover.
    const box0  = root.querySelector('.pop-rate:not(.pop-rate-artist)') || root;
    const stars = [...box0.querySelectorAll('.rate-star')];
    const grade = box0.querySelector('.rate-grade');
    const note  = box0.querySelector('.rate-note');
    if (!stars.length || !grade || !note) return;

    // `saved` is the value on the server; `paint` is free to show a hover
    // preview on top of it. Only the server's answer updates `saved`, so
    // leaving the widget always restores the truth rather than the last hover.
    let saved = 0;
    const paint = v => stars.forEach(b => b.classList.toggle('on', +b.dataset.s <= v));
    const commit = j => {
      saved = j.stars || 0;
      paint(saved);
      // Keep the map's copy current so "size stars by rating" reacts now rather
      // than at the next full map load -- matching wireArtistRating.
      TRACK_RATINGS[hash] = { stars: j.stars || 0, grade: j.grade || '', note: j.note || '' };
    };

    const save = async body => {
      try {
        const r = await fetch(`/ratings/${hash}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        if (r.ok) commit(await r.json());
      } catch(_){ /* offline / backend down -- the UI keeps what you typed */ }
    };

    fetch(`/ratings/${hash}`).then(r => r.ok ? r.json() : null).then(j => {
      if (!j) return;
      commit(j); grade.value = j.grade || ''; note.value = j.note || '';
    }).catch(() => {});

    // hovering previews the value you'd set; leaving restores the saved one
    for (const b of stars){
      b.onmouseenter = () => paint(+b.dataset.s);
      b.onclick = () => save({stars: +b.dataset.s});
    }
    const clear = box0.querySelector('.rate-clear');
    if (clear) clear.onclick = () => save({stars: 0});
    const box = box0.querySelector('.rate-stars');
    if (box) box.onmouseleave = () => paint(saved);

    grade.onchange = () => save({grade: grade.value});
    // save the note on blur rather than per keystroke -- one request per edit
    note.onblur = () => save({note: note.value});
    note.onkeydown = e => { if (e.key === 'Enter') note.blur(); };
  }

  /* The artist rating widget. Same three fields and the same save-per-control
     discipline as wireRating, against the artist endpoints instead of the track
     ones -- a track rating and an artist rating answer different questions and
     neither is derived from the other.

     Kept as its own function rather than parameterising wireRating: the two
     share a shape but not a lifetime (this one also refreshes the in-memory
     ARTIST_RATINGS the map sizes stars from), and folding them together would
     mean a flag argument at every line. */
  function wireArtistRating(root, artist){
    const stars = [...root.querySelectorAll('.arate-star')];
    const grade = root.querySelector('.arate-grade');
    const note  = root.querySelector('.arate-note');
    if (!stars.length || !grade || !note) return;
    const url = `/artist-ratings/${encodeURIComponent(artist)}`;

    let saved = 0;
    const paint = v => stars.forEach(b => b.classList.toggle('on', +b.dataset.s <= v));
    const commit = j => {
      saved = j.stars || 0;
      paint(saved);
      // Keep the map's own copy current so "size stars by rating" reflects the
      // change immediately, instead of waiting for the next full map load.
      ARTIST_RATINGS[j.key || artistKey(artist)] = j;
    };

    const save = async body => {
      try{
        const r = await fetch(url, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body),
        });
        if (r.ok) commit(await r.json());
      }catch(_){ /* offline -- the UI keeps what you typed */ }
    };

    fetch(url).then(r => r.ok ? r.json() : null).then(j => {
      if (!j) return;
      saved = j.stars || 0; paint(saved);
      grade.value = j.grade || ''; note.value = j.note || '';
    }).catch(() => {});

    for (const b of stars){
      b.onmouseenter = () => paint(+b.dataset.s);
      b.onclick = () => save({stars: +b.dataset.s});
    }
    const clear = root.querySelector('.arate-clear');
    if (clear) clear.onclick = () => save({stars: 0});
    const box = root.querySelector('.arate-stars');
    if (box) box.onmouseleave = () => paint(saved);

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

  // Fill the shared <datalist> that backs the override input's dropdown.
  function refreshGenreList(){
    const dl = document.getElementById('ovr-genre-list');
    if (!dl) return;
    dl.innerHTML = knownGenres()
      .map(g => `<option value="${escapeHtml(g)}"></option>`).join('');
  }

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
  // An override answers "what is this" with one word and throws away everything
  // the model got right. This bends the read instead: each genre carries a step
  // you raise or lower, so "this is a VERY house track" and "that Tech Trance is
  // a misread" are both sayable without flattening the rest to zero.
  //
  // The step is what's stored, never the multiplier it computes -- the server
  // can retune the curve without silently rewriting what you meant by it.
  function wireAdjust(popEl, n){
    const btn  = popEl.querySelector('.pop-adjust');
    const box  = popEl.querySelector('.pop-adj');
    const rows = popEl.querySelector('.adj-rows');
    const omitRow = popEl.querySelector('.pop-omit-row');
    const addIn = popEl.querySelector('.adj-add-in');
    if (!btn || !box) return;

    let state = null;          // {steps, base, adjusted, max_step, words}
    let saving = null;         // in-flight POST, so rapid clicks coalesce
    let moved = false;         // did anything actually change? -> re-cluster on close

    // Re-cluster once, when the user is done. Doing it per-press would slide the
    // dot away from the cursor between clicks.
    const done = () => {
      box.hidden = true; omitRow.hidden = false;
      if (moved){ moved = false; if (NODES.length) layout(); }
    };

    const wordFor = s => (state && state.words && state.words[String(s)]) || 'as read';

    function render(){
      if (!state){ rows.innerHTML = `<span class="pop-bar">…</span>`; return; }
      const shown = new Map();
      for (const e of state.adjusted || []) shown.set(e.style, e.score);
      // A genre pushed all the way down can fall out of the top-N; keep its row
      // visible so the press is undoable rather than stranded.
      for (const g of Object.keys(state.steps || {})) if (!shown.has(g)) shown.set(g, 0);
      if (!shown.size){ rows.innerHTML = `<div class="ovr-h">nothing read for this track</div>`; return; }
      const max = state.max_step || 3;
      rows.innerHTML = [...shown.entries()].map(([style, score]) => {
        const step = (state.steps || {})[style] || 0;
        const pct  = Math.round((score || 0) * 100);
        return `<div class="adj-row${step ? ' moved' : ''}" data-g="${escapeHtml(style)}">
          <button class="adj-step" data-d="-1" ${step <= -max ? 'disabled' : ''} title="less">−</button>
          <button class="adj-step" data-d="1" ${step >= max ? 'disabled' : ''} title="more">＋</button>
          <span class="adj-meter" title="${escapeHtml(style)} — ${escapeHtml(wordFor(step))}">
            <i style="width:${pct}%"></i>
            <b>${escapeHtml(style)}</b>${step ? `<em>${escapeHtml(wordFor(step))}</em>` : ''}
          </span>
          <span class="adj-pct">${pct}%</span>
        </div>`;
      }).join('');
      for (const b of rows.querySelectorAll('.adj-step')){
        b.onclick = () => bump(b.closest('.adj-row').dataset.g, Number(b.dataset.d));
      }
    }

    // Optimistic: the row moves on click and the server's answer replaces it a
    // moment later. Waiting for the round-trip made the +/- feel broken.
    function bump(style, delta){
      if (!state) return;
      const max = state.max_step || 3;
      const next = Math.max(-max, Math.min(max, ((state.steps || {})[style] || 0) + delta));
      state.steps = { ...(state.steps || {}) };
      if (next) state.steps[style] = next; else delete state.steps[style];
      render();
      save();
    }

    function save(){
      const steps = state.steps || {};
      saving = (saving || Promise.resolve()).then(async () => {
        try{
          const r = await fetch(`/weights/${n.hash}`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ steps }) });
          const body = await r.json();
          if (steps !== state.steps) return;   // superseded by a later click
          state.steps = body.steps || {};
          state.adjusted = body.adjusted && body.adjusted.length ? body.adjusted : state.base;
          render();
          applyToNode(n, state.adjusted);
          moved = true;
        }catch(_){ /* the row already moved; the next click retries */ }
      });
    }

    btn.onclick = async () => {
      if (!box.hidden){ done(); return; }
      omitRow.hidden = true; box.hidden = false;
      refreshGenreList();
      rows.innerHTML = `<span class="pop-bar">…</span>`;
      try{
        state = await (await fetch(`/weights/${n.hash}`)).json();
      }catch(_){ rows.innerHTML = `<div class="ovr-h">couldn't load this track's read</div>`; return; }
      render();
    };
    popEl.querySelector('.adj-close').onclick = done;

    const addGenre = () => {
      const g = completeGenre(addIn.value) || (addIn.value || '').trim();
      if (!g || !state) return;
      addIn.value = '';
      // Enters at "moderately" -- a genre you had to type is one you mean, and
      // starting at +1 read as barely-there next to what the model already found.
      if (!(state.steps || {})[g]) { state.steps = { ...(state.steps || {}), [g]: 2 }; render(); save(); }
    };
    popEl.querySelector('.adj-add').onclick = addGenre;
    addIn.addEventListener('keydown', e => {
      if (e.key === 'Enter'){ addGenre(); return; }
      if (e.key === 'Escape'){ done(); return; }
      if (e.key === 'Tab' && addIn.value.trim()){
        const hit = completeGenre(addIn.value);
        if (hit && hit.toLowerCase() !== addIn.value.trim().toLowerCase()){
          e.preventDefault(); addIn.value = hit;
          addIn.setSelectionRange(hit.length, hit.length);
        }
      }
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
    n.hue = sh.h; n.sat = sh.s; n.dl = sh.dl;
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
    const sh = styleShade(n.fam, genre);
    n.hue = sh.h; n.sat = sh.s; n.dl = sh.dl;
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
    stopPreview();
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
    if (mapMode === 'tree'){ fitTree(); return; }
    if (mapMode === 'solar'){
      // Solar's bodies orbit in the XZ plane, so the default -0.15 tilt shows
      // the system almost edge-on and the rings collapse into lines. Look down
      // on it instead -- that is the view in which "which ring is this track
      // in" is actually answerable -- and fit the outermost orbit with a margin
      // for the ring labels, which sit outside it.
      rot.x = -0.62;
      view.zoom = clamp(0.88 / (MAXR || 1), 0.25, 2.2);
      return;
    }
    view.zoom = clamp(0.95 / (MAXR || 1), 0.25, 1.6);   // fit the cloud
  }
  function focusFamily(fam){          // fly to a genre's centroid + orbit around it
    const c = CENTROIDS[fam]; if (!c) return;
    closePopup();                     // drop any track selection...
    famPivot = c;                     // ...then orbit around this cluster's centre
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
    try{ if (localStorage.getItem('vibeNavKeys') === 'off') keysEl.classList.add('collapsed'); }catch(_){}
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
      try {
        const pls = await (await fetch('/playlists')).json();
        const list = Array.isArray(pls) ? pls : (pls.playlists || []);
        const psel = $f('flt-pl');
        if (psel) psel.innerHTML = `<option value="">any playlist</option>`
          + list.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
      } catch(_) { /* playlists are optional */ }
      syncFilt();
    }
    window.mapFilterPopulate = populate;

    // let anything outside this block (the popup's tag chips) refresh the panel
    syncFilterUI = syncFilt;
    const onFilt = () => { syncFilt(); };
    $f('flt-artist').addEventListener('input', e => {
      FILT.artist = e.target.value.trim().toLowerCase(); onFilt();
    });
    $f('flt-key').addEventListener('change', e => { FILT.key = e.target.value; onFilt(); });
    $f('flt-style').addEventListener('change', e => { FILT.style = e.target.value; onFilt(); });
    $f('flt-pl').addEventListener('change', async e => {
      FILT.playlist = e.target.value || null;
      playlistHashes = null;
      if (FILT.playlist){
        try {
          const d = await (await fetch(`/playlists/${FILT.playlist}`)).json();
          const hs = d.tracks || d.hashes || [];
          playlistHashes = new Set(hs.map(x => (typeof x === 'string' ? x : x && x.hash)).filter(Boolean));
        } catch(_) { playlistHashes = null; }
      }
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
      $f('flt-bpm-lo').value = 0; $f('flt-bpm-hi').value = 100;
      $f('flt-len-lo').value = 0; $f('flt-len-hi').value = 100;
      for (const b of filtPanel.querySelectorAll('.flt-tag.on')) b.classList.remove('on');
      syncFilt();
    });
    filtBtn.addEventListener('click', e => { e.stopPropagation(); filtPanel.hidden = !filtPanel.hidden; });
    filtPanel.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { filtPanel.hidden = true; });
  }

  /* ---- label options popover --------------------------------------- */
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
      setChk('lbl-flat', LBL.flat);
      setChk('lbl-hidetext', LBL.hideText);
      setChk('lbl-leaders', LBL.leaders);
      setChk('lbl-glow', LBL.glow);
      setChk('lbl-rate', LBL.sizeByRating);
      setChk('lbl-rate-artist', LBL.useArtistRating);
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
        || LBL.flat || LBL.linkWidth !== 1 || LBL.hideText || LBL.sizeByRating
        || LBL.twinkle !== 'subtle' || !LBL.glow || LBL.labelStyle !== 'halo');
    };
    syncLbl();
    lblBtn.addEventListener('click', e => {
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
    bind('lbl-flat',      el => LBL.flat      = el.checked);
    bind('lbl-hidetext',  el => LBL.hideText  = el.checked);
    bind('lbl-leaders',   el => LBL.leaders   = el.checked);
    bind('lbl-glow',      el => LBL.glow      = el.checked);
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
      case '+': case '=': case 'w': view.zoom = clamp(view.zoom*1.15, 0.3, 60); anim=null; break;
      case '-': case '_': case 's': view.zoom = clamp(view.zoom/1.15, 0.3, 60); anim=null; break;
      case 'a': rot.y -= ROT; break;                 // orbit left
      case 'd': rot.y += ROT; break;                 // orbit right
      case 'arrowleft':  view.panx += PAN; break;    // arrows pan the view
      case 'arrowright': view.panx -= PAN; break;
      case 'arrowup':    view.pany += PAN; break;
      case 'arrowdown':  view.pany -= PAN; break;
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
    if (mapMode === 'solar') await loadSolarSet();
    if (NODES.length){ layout(); resetView(); }
  });

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
    const [mem, tr, ar, pls] = await Promise.all([
      grab('/vibes/membership'), grab('/ratings'), grab('/artist-ratings'), grab('/playlists'),
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

    PLAYLISTS = Array.isArray(pls) ? pls : (pls && pls.playlists) || [];
    const sel = document.getElementById('solar-pl');
    if (sel){
      sel.innerHTML = PLAYLISTS.length
        ? PLAYLISTS.map(pl => `<option value="${pl.id}">${escapeHtml(pl.name)}</option>`).join('')
        : '<option value="">no saved playlists yet</option>';
      if (SOLAR.playlist && PLAYLISTS.some(pl => String(pl.id) === String(SOLAR.playlist)))
        sel.value = SOLAR.playlist;
      else if (PLAYLISTS.length){ SOLAR.playlist = String(PLAYLISTS[0].id); sel.value = SOLAR.playlist; }
    }
    const uby = document.getElementById('uni-by');
    if (uby) uby.value = UNI.by;
    const sby = document.getElementById('solar-by');
    if (sby) sby.value = SOLAR.by;
  }

  /* The chosen playlist's tracks. Split in two so the network half can happen
     before NODES is swapped and the state half inside the swap -- see loadMap. */
  let solarPayload = null;

  async function fetchSolarPayload(){
    solarPayload = null;
    if (!SOLAR.playlist) return;
    const pl = PLAYLISTS.find(x => String(x.id) === String(SOLAR.playlist));
    try{
      // r.ok first: a 404 body is still valid JSON ({"error": ...}), so parsing
      // it blindly yielded an empty Set for a playlist that no longer exists --
      // indistinguishable from an empty one, and it suppressed the hint.
      const r = await fetch(`/playlists/${SOLAR.playlist}`);
      if (!r.ok) return;
      const d = await r.json();
      solarPayload = { name: pl ? pl.name : (d.name || ''), tracks: d.tracks || d.hashes || [] };
    }catch(_){ solarPayload = null; }
  }

  function solarSetFrom(payload){
    if (!payload){ SOLAR_SET = null; SOLAR_NAME = ''; return; }
    SOLAR_NAME = payload.name || '';
    SOLAR_SET = new Set(
      (payload.tracks || []).map(x => (typeof x === 'string' ? x : x && x.hash)).filter(Boolean));
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

  async function loadMap(){
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
      if (!nextNodes.length){
        NODES = []; EDGES = [];
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
      NODES = nextNodes; EDGES = nextEdges;
      byHash.clear();
      for (const n of NODES) byHash.set(n.hash, n);
      if (mapMode === 'solar') solarSetFrom(solarPayload);
      resize(); layout();
      loading(false);
    }catch(err){
      loading(false);
      countMap.textContent='failed to load map';
      console.error('map load failed', err);
    }
  }
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
        fitView();
        startLoop();
        // the filter choosers are built from the loaded library, so they can only
        // be populated once the nodes exist
        if (window.mapFilterPopulate) window.mapFilterPopulate();
        const m = /^#map=(.+)$/.exec(deepHash);
        if (m && byHash.has(m[1])) selectNode(m[1]);
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

  // let other UI (the review-reads panel) jump to a track on the map
  window.vibeMapGoto = (hash) => {
    try{ history.replaceState(null, '', '#map=' + hash); }catch(_){}
    switchTo('map');
  };
})();

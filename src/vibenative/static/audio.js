/* One place to decide WHAT you hear, and how loud.

   Two audio sources exist in this app and they used to fight over your ears:

     • the TRACK  — PLAYER.audio (player.js). Full playback: a List row, the Map
       popup's ▶ play, the playlist. The Now Playing bar drives it.
     • the SAMPLE — a ~22s clip from the selected track's drop, started by the
       Map when you select a node. map.js owns the element and picks the clip.

   Whichever started last simply paused the other, so exploring the Map kept
   cutting off whatever you were listening to and there was no way to say which
   one you actually wanted. AUDIO.listen is that say: a sticky 'sample' | 'track'
   choice, persisted. The loser is paused and STAYS paused — selecting a new
   track still loads its sample, but only plays it if the sample is the side
   you're listening to. Flip the switch and the other side picks up where it was.

   Each source carries its own volume + mute (also persisted), so a sample can be
   a quiet audition underneath a loud track.

   Two entry points into the switch, deliberately different:
     AUDIO.claim(kind)     — "this source is starting itself right now": take the
                             focus and pause the other. Never resumes anything,
                             so a source can call it from inside its own start.
     AUDIO.setListen(kind) — the user flipped the switch: claim, then resume the
                             winner. Only ever called from the UI.

   LOAD ORDER: after player.js (needs PLAYER); before nowbar.js and map.js,
   which call AUDIO. */

/* exported AUDIO */ // defined here, used by player.js, nowbar.js and map.js

const AUDIO = (function () {
  const KEY = 'vibeAudio';
  const state = {
    listen: 'sample',            // matches the old behaviour: samples take over
    trackVol: 1, trackMute: false,
    sampleVol: 0.7, sampleMute: false,   // an audition, so quieter by default
  };
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}') || {}); } catch (_) { /* private mode */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* private mode */ } };

  /* The sample source. map.js registers its element and the two verbs only it
     can implement (restart the clip from the drop; give the clip up). */
  const sample = {
    audio: null, restart: null, release: null,
    loaded: false, meta: null, start: 0, seconds: 0,
  };

  const trackAudio = () => (typeof PLAYER !== 'undefined' ? PLAYER.audio : null);
  const trackLoaded = () => !!(typeof PLAYER !== 'undefined' && PLAYER.now);
  const isPlaying = a => !!(a && !a.paused && !a.ended);

  /* A source may sound when it holds the focus — or when the other side has
     nothing loaded, so "listening to the track" can never mean silence. */
  function wants(kind) {
    if (kind === 'sample') return state.listen === 'sample' || !trackLoaded();
    return state.listen === 'track' || !sample.loaded;
  }

  function applyVolume() {
    const t = trackAudio();
    if (t) { t.volume = state.trackVol; t.muted = state.trackMute; }
    if (sample.audio) { sample.audio.volume = state.sampleVol; sample.audio.muted = state.sampleMute; }
  }

  function pause(kind) {
    const a = kind === 'sample' ? sample.audio : trackAudio();
    try { if (a) a.pause(); } catch (_) { /* never started */ }
  }

  // Take the focus for a source that is already starting itself.
  function claim(kind) {
    if (state.listen !== kind) { state.listen = kind; save(); }
    pause(kind === 'sample' ? 'track' : 'sample');
    render();
  }

  // The user flipped the switch: take the focus AND pick the winner back up.
  function setListen(kind) {
    claim(kind);
    if (kind === 'sample') {
      if (sample.loaded && !isPlaying(sample.audio) && sample.restart) sample.restart();
    } else if (trackLoaded() && !isPlaying(trackAudio())) {
      const t = trackAudio();
      if (t) t.play().catch(() => { /* the bar's error handler reports it */ });
    }
    render();
  }

  /* ---- the sample strip, plus the Now Playing bar's volume + replay ---- */
  const bar = document.getElementById('samplebar');
  const $ = (root, s) => (root ? root.querySelector(s) : null);
  const el = {
    dot: $(bar, '.sb-dot'), title: $(bar, '.sb-title'), sub: $(bar, '.sb-sub'),
    play: $(bar, '.sb-play'), replay: $(bar, '.sb-replay'), stop: $(bar, '.sb-stop'),
    fill: $(bar, '.sb-seekfill'), listen: $(bar, '.sb-listen'),
    nbReplay: document.querySelector('#nowbar .nb-replay'),
  };
  const fmt = t => (typeof fmtTime === 'function' ? fmtTime(t) : '0:00');

  /* One volume widget = a mute button + a slider, wired to one source. */
  function wireVolume(root, kind) {
    if (!root) return null;
    const mute = root.querySelector('.vol-mute');
    const slider = root.querySelector('.vol-slider');
    if (!mute || !slider) return null;
    const volKey = kind === 'sample' ? 'sampleVol' : 'trackVol';
    const muteKey = kind === 'sample' ? 'sampleMute' : 'trackMute';
    const what = kind === 'sample' ? ' the sample' : ' the track';
    function draw() {
      const off = state[muteKey] || state[volKey] === 0;
      mute.textContent = off ? '🔇' : '🔊';
      mute.classList.toggle('off', off);
      mute.title = (state[muteKey] ? 'unmute' : 'mute') + what;
      slider.value = String(Math.round(state[volKey] * 100));
    }
    slider.addEventListener('input', () => {
      state[volKey] = Math.max(0, Math.min(1, Number(slider.value) / 100));
      if (state[volKey] > 0) state[muteKey] = false;    // dragging up is an unmute
      applyVolume(); save(); draw();
    });
    mute.addEventListener('click', () => {
      state[muteKey] = !state[muteKey];
      if (!state[muteKey] && state[volKey] === 0) state[volKey] = 0.5;   // unmute to something audible
      applyVolume(); save(); draw();
    });
    draw();
    return draw;
  }
  const drawTrackVol = wireVolume(document.querySelector('#nowbar .nb-vol'), 'track');
  const drawSampleVol = wireVolume($(bar, '.sb-vol'), 'sample');

  function tick() {
    if (!bar || !sample.loaded || !el.fill) return;
    const span = sample.seconds || 1;
    const into = (sample.audio ? sample.audio.currentTime : 0) - sample.start;
    el.fill.style.width = Math.max(0, Math.min(100, (into / span) * 100)) + '%';
  }

  function render() {
    if (drawTrackVol) drawTrackVol();
    if (drawSampleVol) drawSampleVol();
    if (!bar) return;
    bar.classList.toggle('on', sample.loaded);
    if (!sample.loaded) return;
    const playing = isPlaying(sample.audio);
    const m = sample.meta || {};
    el.title.textContent = m.title || 'Track';
    el.dot.style.background = m.color || 'var(--accent-b)';
    el.dot.style.color = m.color || 'var(--accent-b)';   // drives the glow
    el.play.textContent = playing ? '❙❙' : '▶';
    el.play.classList.toggle('playing', playing);
    // The sub-line answers the only question a silent strip raises: why?
    el.sub.textContent = (playing || wants('sample'))
      ? `sample · from ${fmt(sample.start)}`
      : 'sample · held — you’re listening to the track';
    // The switch is only a question worth asking when there are two answers.
    el.listen.hidden = !trackLoaded();
    el.listen.querySelectorAll('.sb-lsn').forEach(b =>
      b.classList.toggle('on', b.dataset.listen === state.listen));
    tick();
  }

  if (bar) {
    el.play.addEventListener('click', () => {
      if (isPlaying(sample.audio)) { pause('sample'); render(); return; }
      setListen('sample');                     // playing the sample IS choosing it
    });
    el.replay.addEventListener('click', () => {
      if (sample.restart) { claim('sample'); sample.restart(); }
    });
    el.stop.addEventListener('click', () => {
      pause('sample');
      // Stopping the sample hands your ears back to the track, if there is one.
      if (trackLoaded()) setListen('track'); else render();
    });
    el.listen.querySelectorAll('.sb-lsn').forEach(b =>
      b.addEventListener('click', () => setListen(b.dataset.listen)));
  }
  if (el.nbReplay) el.nbReplay.addEventListener('click', () => {
    const t = trackAudio();
    if (!t || !trackLoaded()) return;
    claim('track');
    try { t.currentTime = 0; } catch (_) { /* not seekable yet */ }
    t.play().catch(() => { /* the bar's error handler reports it */ });
  });

  applyVolume();
  render();

  return {
    claim, setListen, wants, render,
    get listen() { return state.listen; },

    /* map.js hands over its element and the verbs only it can implement. */
    registerSample(opts) {
      sample.audio = opts.audio;
      sample.restart = opts.restart;
      sample.release = opts.release;
      applyVolume();
      ['play', 'pause', 'ended'].forEach(ev => sample.audio.addEventListener(ev, render));
      sample.audio.addEventListener('timeupdate', tick);
    },
    /* A clip is cued for a track: show the strip, whether or not it plays. */
    sampleLoaded(meta) {
      sample.loaded = true;
      sample.meta = meta || {};
      sample.start = sample.meta.start || 0;
      sample.seconds = sample.meta.seconds || 0;
      render();
    },
    /* No clip any more (popup closed, or nothing playable): drop the strip. */
    sampleClear() {
      sample.loaded = false; sample.meta = null;
      if (sample.release) sample.release();
      render();
    },
  };
})();

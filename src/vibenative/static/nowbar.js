/* Persistent "Now Playing" bar. It observes the ONE shared <audio> (PLAYER from
   player.js) so it reflects whatever is playing — a List row or a Map track —
   without disturbing the per-row controllers.

   LOAD ORDER: after app.js (needs fmtTime) and player.js (needs PLAYER); before
   map.js, which calls the globals this file exposes:
     window.playHash(hash, meta)  — play a server track by hash (Map / playlist)
     window.__nowNext             — optional; playlist.js sets it to auto-advance
     window.nowClearQueue         — hook playlist.js overrides to stop queue play */

(function () {
  const bar = document.getElementById('nowbar');
  if (!bar || typeof PLAYER === 'undefined') return;

  const $ = s => bar.querySelector(s);
  const el = {
    dot: $('.nb-dot'), title: $('.nb-title'), artist: $('.nb-artist'),
    play: $('.nb-play'), prev: $('.nb-prev'), next: $('.nb-next'),
    cur: $('.nb-cur'), dur: $('.nb-dur'), seek: $('.nb-seek'),
    fill: $('.nb-seekfill'), close: $('.nb-close'),
  };
  const fmt = t => (typeof fmtTime === 'function' ? fmtTime(t) : '0:00');

  PLAYER.now = null;   // {hash, title, artist, color, dur} of the current track

  function renderMeta() {
    bar.classList.toggle('on', !!PLAYER.now);
    if (!PLAYER.now) return;
    el.title.textContent = PLAYER.now.title || 'Track';
    el.artist.textContent = PLAYER.now.artist || '';
    el.dot.style.background = PLAYER.now.color || 'var(--accent-a)';
    el.dot.style.color = PLAYER.now.color || 'var(--accent-a)';   // drives the glow
  }
  function renderPlay() {
    const playing = !PLAYER.audio.paused && !PLAYER.audio.ended && PLAYER.now;
    el.play.textContent = playing ? '❙❙' : '▶';
    el.play.classList.toggle('playing', !!playing);
  }
  function tick() {
    const d = PLAYER.audio.duration || (PLAYER.now && PLAYER.now.dur) || 0;
    const c = PLAYER.audio.currentTime || 0;
    el.fill.style.width = (d ? (c / d) * 100 : 0) + '%';
    el.cur.textContent = fmt(c);
    el.dur.textContent = fmt(d);
  }

  PLAYER.audio.addEventListener('timeupdate', tick);
  PLAYER.audio.addEventListener('loadedmetadata', tick);
  PLAYER.audio.addEventListener('play', () => { renderMeta(); renderPlay(); });
  PLAYER.audio.addEventListener('pause', renderPlay);
  PLAYER.audio.addEventListener('ended', () => {
    renderPlay();
    if (typeof window.__nowNext === 'function') window.__nowNext();   // playlist auto-advance
  });
  PLAYER.audio.addEventListener('error', () => {
    if (PLAYER.now) { el.title.textContent = '✕ no audio — re-scan its folder'; el.artist.textContent = ''; }
  });

  el.play.addEventListener('click', () => {
    if (!PLAYER.now) return;
    if (PLAYER.audio.paused) PLAYER.audio.play().catch(() => {});
    else PLAYER.audio.pause();
  });
  el.seek.addEventListener('click', e => {
    const r = el.seek.getBoundingClientRect();
    const d = PLAYER.audio.duration || 0;
    if (d) PLAYER.audio.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * d;
  });
  el.close.addEventListener('click', () => {
    PLAYER.audio.pause();
    if (typeof window.nowClearQueue === 'function') window.nowClearQueue();
    PLAYER.now = null;
    bar.classList.remove('on');
  });

  const keepUrl = u => { if (typeof OBJ_URLS !== 'undefined') OBJ_URLS.push(u); return u; };

  // Play a track by hash (used by the Map popup + playlist). Takes over the shared
  // audio, resetting any List row that was playing. Async because a dropped track
  // with no server copy may resolve through a persisted file handle (may prompt).
  window.playHash = async function (hash, meta) {
    if (!hash) return;
    if (PLAYER.ctl && PLAYER.ctl.stopVisual) PLAYER.ctl.stopVisual();
    PLAYER.ctl = { tick() {}, render() {}, stopVisual() {}, error() {} };  // bar owns playback now
    PLAYER.now = Object.assign({ hash }, meta || {});
    renderMeta();
    // Choose a source without a needless permission prompt:
    //   cached File (this session) -> server copy -> persisted handle.
    let url = null;
    const cached = (typeof HASH_FILES !== 'undefined') && HASH_FILES.get(hash);
    if (cached) url = keepUrl(URL.createObjectURL(cached));
    else {
      let serverOk = false;
      try { serverOk = (await fetch('/audio/' + hash, { method: 'HEAD' })).ok; } catch (_) { /* offline */ }
      if (serverOk) url = '/audio/' + hash;
      else if (typeof FSH !== 'undefined' && FSH.supported) {
        const f = await FSH.file(hash);   // reopens the dropped file (may prompt once)
        if (f) { if (typeof HASH_FILES !== 'undefined') HASH_FILES.set(hash, f); url = keepUrl(URL.createObjectURL(f)); }
      }
      if (!url) url = '/audio/' + hash;   // let it error -> the bar shows the message
    }
    // Always start from the beginning. Re-selecting the SAME track keeps the src,
    // so the element would otherwise resume mid-track — reset currentTime instead.
    const abs = new URL(url, location.href).href;
    if (PLAYER.audio.src === abs) PLAYER.audio.currentTime = 0;
    else PLAYER.audio.src = url;
    PLAYER.audio.play().catch(() => {});
  };

  // Let playlist.js toggle the prev/next buttons on when a queue is active.
  window.nowShowQueueControls = function (on) {
    el.prev.hidden = !on;
    el.next.hidden = !on;
  };
  el.prev.addEventListener('click', () => { if (window.__nowPrev) window.__nowPrev(); });
  el.next.addEventListener('click', () => { if (window.__nowNext) window.__nowNext(); });
})();

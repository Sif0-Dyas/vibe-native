/* Audio preview for List rows: one <audio>, one track at a time — play /
   pause, seek by clicking the waveform, and the moving playhead.

   LOAD ORDER: load AFTER app.js (attachPlayer uses fmtTime from app.js) and
   BEFORE audio.js, which wraps this element as the "track" audio source.
   Exposes the globals PLAYER, OBJ_URLS and attachPlayer(), which app.js's
   row builder and Clear handler use. See index.html. */

/* exported attachPlayer */ // defined here, called from app.js's finishRow (shared scope)

/* ---- shared audio preview player: one track plays at a time. Each row
   registers a controller (PLAYER.ctl) that the audio events drive; starting a
   new row hands the single <audio> over and resets the previous row's UI. ---- */
const PLAYER = { audio: new Audio(), ctl: null };
PLAYER.audio.preload = 'metadata';
const OBJ_URLS = [];   // blob URLs for dropped files, revoked on Clear
/* Dropped/browsed files have no server-side copy, so their only audio source is
   the in-memory File. Keep it keyed by content hash for the whole SESSION (this
   map deliberately survives Clear) so a track you analyzed by dropping stays
   playable afterwards — re-added from the Library, the Map, or the playlist.
   Cleared on page reload, when the File objects are gone anyway. */
const HASH_FILES = new Map();

/* ---- persistent audio access via the File System Access API (Chromium/WebView2).
   Dropped/browsed files have no server copy, and the in-memory File is lost on
   restart. So we also keep a FileSystemFileHandle per content hash in IndexedDB:
   handles are structured-cloneable, so they survive restarts, and re-opening one
   (with a one-time permission check, on a user gesture) reads the real file again.
   Everything degrades gracefully where the API is missing. ---- */
const FSH = (function () {
  const DB = 'vibe-fsh', STORE = 'handles';
  const supported = typeof window !== 'undefined' &&
    'showOpenFilePicker' in window && 'indexedDB' in window;
  function open() {
    return new Promise((res, rej) => {
      const rq = indexedDB.open(DB, 1);
      rq.onupgradeneeded = () => rq.result.createObjectStore(STORE);
      rq.onsuccess = () => res(rq.result);
      rq.onerror = () => rej(rq.error);
    });
  }
  async function tx(mode, makeRequest) {
    if (!supported) return null;
    let d;
    try { d = await open(); } catch (_) { return null; }
    try {
      return await new Promise((res, rej) => {
        const t = d.transaction(STORE, mode);
        const rq = makeRequest(t.objectStore(STORE));   // an IDBRequest
        rq.onerror = () => rej(rq.error);
        t.oncomplete = () => res(rq.result);            // populated by completion
        t.onerror = () => rej(t.error);
      });
    } catch (_) { return null; } finally { d.close(); }
  }
  // store the handle for a track by hash (fire-and-forget)
  async function put(hash, handle) {
    if (!hash || !handle) return;
    await tx('readwrite', s => s.put(handle, hash));
  }
  // resolve a stored handle to a readable File, prompting for permission if needed.
  // MUST be called during a user gesture (a play click) or requestPermission throws.
  async function file(hash) {
    if (!hash) return null;
    const handle = await tx('readonly', s => s.get(hash));
    if (!handle || handle.kind !== 'file') return null;
    try {
      const opts = { mode: 'read' };
      if ((await handle.queryPermission(opts)) !== 'granted' &&
          (await handle.requestPermission(opts)) !== 'granted') return null;
      return await handle.getFile();
    } catch (_) { return null; }
  }
  return { put, file, supported };
})();

PLAYER.audio.addEventListener('timeupdate', () => { if (PLAYER.ctl) PLAYER.ctl.tick(); });
PLAYER.audio.addEventListener('play',       () => {
  if (PLAYER.ctl) PLAYER.ctl.render();
  // Starting full playback IS choosing the track: take the focus, which pauses
  // any map sample. The choice sticks, so later selections won't cut this off.
  if (typeof AUDIO !== 'undefined') AUDIO.claim('track');
});
PLAYER.audio.addEventListener('pause',      () => { if (PLAYER.ctl) PLAYER.ctl.render(); });
PLAYER.audio.addEventListener('ended',      () => { if (PLAYER.ctl) PLAYER.ctl.render(); });
PLAYER.audio.addEventListener('error',      () => { if (PLAYER.ctl) PLAYER.ctl.error(); });

/* Wire the play button, playhead and waveform-seek for one List row. */
function attachPlayer(row, container, controls, c, file, data, dur){
    /* ---- audio preview: play/scrub this track through its waveform ---- */
    const playhead = document.createElement('div');
    playhead.className = 'playhead';
    container.appendChild(playhead);

    const playBtn = document.createElement('button');
    playBtn.className = 'playbtn'; playBtn.type = 'button';
    playBtn.textContent = '▶ play';
    playBtn.title = 'play / pause (or click the waveform to play from a point)';
    const playTime = document.createElement('span');
    playTime.className = 'playtime';
    controls.insertBefore(playTime, controls.firstChild);
    controls.insertBefore(playBtn, controls.firstChild);

    let objURL = null;
    function blobFor(f){
      if (!objURL){ objURL = URL.createObjectURL(f); OBJ_URLS.push(objURL); }
      return objURL;
    }
    // Resolve a playable source, best-first. Async because a persisted file handle
    // may need a permission prompt + read. Order avoids prompts when possible:
    //   1) a File already in hand (this row, or cached from a drop this session)
    //   2) the server copy (batch/folder tracks — no prompt)
    //   3) a persisted FileSystemFileHandle (dropped tracks, across restarts)
    async function resolveSrc(){
      const localFile = file || (data.hash && HASH_FILES.get(data.hash));
      if (localFile) return blobFor(localFile);
      if (data.hash && data.filepath) return '/audio/' + data.hash;   // server file
      if (data.hash){
        const f = await FSH.file(data.hash);          // may prompt (we're in a click)
        if (f){ HASH_FILES.set(data.hash, f); return blobFor(f); }
        return '/audio/' + data.hash;                 // last resort (404 -> error UI)
      }
      return null;
    }
    const isActive = () => PLAYER.ctl === ctl;
    function render(){
      const playing = isActive() && !PLAYER.audio.paused && !PLAYER.audio.ended;
      playBtn.textContent = playing ? '❙❙ pause' : '▶ play';
      playBtn.classList.toggle('playing', playing);
      playhead.style.display = (isActive() && (playing || PLAYER.audio.currentTime > 0)) ? 'block' : 'none';
      if (!isActive()) playTime.textContent = '';
    }
    function tick(){
      if (!isActive()) return;
      const d = PLAYER.audio.duration || dur || 0;
      const cur = PLAYER.audio.currentTime || 0;
      playhead.style.left = (d ? cur / d * 100 : 0) + '%';
      playTime.textContent = `${fmtTime(cur)} / ${fmtTime(d)}`;
    }
    function stopVisual(){
      playBtn.textContent = '▶ play'; playBtn.classList.remove('playing');
      playhead.style.display = 'none'; playTime.textContent = '';
    }
    function onError(){
      if (!isActive()) return;
      // src was a blob -> the audio really is an unsupported codec; otherwise the
      // server had no file for it (dropped track with no saved handle/copy).
      const blob = /^blob:/.test(PLAYER.audio.currentSrc || PLAYER.audio.src || '');
      playBtn.textContent = '✕ can’t play'; playBtn.disabled = true;
      playBtn.title = blob
        ? 'this audio format can’t be played by the browser'
        : 'no saved audio for this track — re-add it (drag-drop or Browse) to enable playback';
    }
    const ctl = { tick, render, stopVisual, error: onError, seek: null };
    row._playCtl = ctl;

    async function startPlay(seekFrac){
      if (!isActive()){                       // take over the shared player
        const src = await resolveSrc();       // only resolve (and maybe prompt) on takeover
        if (!src){
          playBtn.textContent = '✕ no audio'; playBtn.disabled = true;
          playBtn.title = 'no playable source — re-add this track to enable playback';
          return;
        }
        if (PLAYER.ctl) PLAYER.ctl.stopVisual();
        PLAYER.ctl = ctl;
        PLAYER.audio.src = src;
        // surface this track in the Now Playing bar (nowbar.js observes PLAYER.now)
        PLAYER.now = {
          hash: data && data.hash,
          title: (data && data.title) || (file && file.name) || 'Track',
          artist: (data && data.tags && data.tags.tag && data.tags.tag.artist) || '',
          dur,
        };
      }
      if (seekFrac != null){
        const f = Math.max(0, Math.min(1, seekFrac));
        const setT = () => { PLAYER.audio.currentTime = f * (PLAYER.audio.duration || dur || 0); };
        if (PLAYER.audio.readyState >= 1) setT();
        else PLAYER.audio.addEventListener('loadedmetadata', setT, {once:true});
      }
      try { await PLAYER.audio.play(); } catch(e){ /* error event drives the UI */ }
      render();
    }
    // the cue strip (app.js) plays from a cue through this: a track fraction in
    ctl.seek = frac => startPlay(frac);
    function togglePlay(){
      if (isActive() && !PLAYER.audio.paused) PLAYER.audio.pause();
      else startPlay(isActive() ? null : 0);
    }
    playBtn.addEventListener('click', togglePlay);
    c.addEventListener('pointerdown', e => {
      if (e.shiftKey) return;            // shift-drag is a segment-override selection, not a seek
      const rect = c.getBoundingClientRect();
      startPlay((e.clientX - rect.left) / rect.width);
    });
}

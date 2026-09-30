/* The blind-labelling page (/label). Standalone: it imports nothing from the
   Analyzer, and it calls only /api/v1/labels* and /api/v1/audio/<h> -- none of
   which carry the model's read -- so nothing on this page can show it.
   tests/test_labels.py holds the script to that list. */

const API = '/api/v1';
const $ = id => document.getElementById(id);
const skipped = [];
let current = null;

function setStatus(text, isErr){
  const el = $('lbl-status');
  el.textContent = text || '';
  el.classList.toggle('err', !!isErr);
}

function showCount(n){
  $('lbl-count').textContent = `${n} labelled`;
}

async function getJSON(url, opts){
  const r = await fetch(url, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `${r.status} ${r.statusText}`);
  return j;
}

async function loadVocabulary(){
  try {
    const names = await getJSON(`${API}/labels/vocabulary`);
    const dl = $('lbl-vocab');
    dl.replaceChildren(...names.map(n => {
      const o = document.createElement('option');
      o.value = n;
      return o;
    }));
  } catch (_){ /* typing a name still works */ }
}

async function loadRecent(){
  const j = await getJSON(`${API}/labels?limit=20`);
  showCount(j.labelled);
  const ul = $('lbl-recent');
  ul.replaceChildren(...j.labels.map(l => {
    const li = document.createElement('li');
    const g = document.createElement('span');
    g.className = 'g';
    g.textContent = l.genre;
    const t = document.createElement('span');
    t.className = 't';
    t.textContent = l.artist ? `${l.artist} — ${l.title}` : l.title;
    const undo = document.createElement('button');
    undo.type = 'button';
    undo.textContent = 'undo';
    undo.title = 'remove this label';
    undo.addEventListener('click', async () => {
      try {
        await getJSON(`${API}/labels/${encodeURIComponent(l.hash)}`, {method: 'DELETE'});
        await loadRecent();
      } catch (e){ setStatus(`undo failed: ${e.message}`, true); }
    });
    li.append(g, t, undo);
    return li;
  }));
}

async function nextTrack(){
  const q = skipped.length ? `?skip=${encodeURIComponent(skipped.join(','))}` : '';
  const j = await getJSON(`${API}/labels/next${q}`);
  showCount(j.labelled);
  current = j.track;
  $('lbl-card').hidden = !current;
  $('lbl-done').hidden = !!current;
  if (!current) return;
  $('lbl-title').textContent = current.title;
  $('lbl-artist').textContent = current.artist;
  const audio = $('lbl-audio');
  audio.src = `${API}/audio/${encodeURIComponent(current.hash)}`;
  $('lbl-genre').value = '';
  $('lbl-genre').focus();
}

$('lbl-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  if (!current) return;
  const genre = $('lbl-genre').value.trim();
  if (!genre){ setStatus('name a genre first, or skip', true); return; }
  const save = $('lbl-save');
  save.disabled = true;
  try {
    await getJSON(`${API}/labels/${encodeURIComponent(current.hash)}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({genre}),
    });
    setStatus(`saved: ${genre}`);
    $('lbl-audio').pause();
    await Promise.all([nextTrack(), loadRecent()]);
  } catch (e){
    setStatus(`save failed: ${e.message}`, true);
  } finally {
    save.disabled = false;
  }
});

$('lbl-skip').addEventListener('click', async () => {
  if (!current) return;
  skipped.push(current.hash);
  $('lbl-audio').pause();
  setStatus('skipped');
  try { await nextTrack(); } catch (e){ setStatus(e.message, true); }
});

$('lbl-audio').addEventListener('error', () => {
  if (current) setStatus('this file will not play here — skip it', true);
});

loadVocabulary();
Promise.all([nextTrack(), loadRecent()]).catch(e => setStatus(e.message, true));

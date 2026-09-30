/* The one entry module (index.html loads only this, type="module").

   The files are imported in the order they used to load as <script> tags. Each
   one's imports point only at files earlier in this list -- the calls from an
   earlier file into a later one go through hooks.js -- except app.js, which
   imports player.js and panels.js (both use app.js only inside functions called
   later). A module's imports run before its own body, so player.js and panels.js
   now run just before app.js instead of after it; every other file runs in
   exactly this order.
*/

import './app.js';
import './player.js';
import './audio.js';
import './panels.js';
import './nowbar.js';
import './playlist.js';
import './library.js';
import './options.js';
import './genres.js';
import './vibes.js';
import './map.js';
import { runBatch } from './app.js';

/* Names the page puts on window, and why -- the only ones.

   runBatch(path)  The desktop shell (desktop/genre_app.pyw, INJECT_JS) takes over
                   the "batch folder" button: it opens the native folder picker and
                   calls window.runBatch(winPath) with the folder chosen. */
window.runBatch = runBatch;

/* Late-bound calls: a file that loads earlier calling into one that loads later.

   Importing the later module directly would put a back-edge in the import graph,
   and a module's imports are evaluated before its own body -- so the later file
   would run first, before the things it uses at load exist. These calls only
   happen long after load (a click, a track ending), so they go through this one
   object instead: the owner sets its entry when it sets itself up, the caller
   reads it at call time. (They used to be window.* names.)

     reloadLibrary       library.js sets; app.js calls after a key correction
     vibeKeyViewChanged  map.js sets;     app.js calls when the key notation changes
     vibeMapGoto         map.js sets;     app.js and audio.js call (a title click)
     nowNext / nowPrev   playlist.js sets; nowbar.js calls (queue play)
     nowClearQueue       playlist.js sets; nowbar.js calls
     audio               audio.js sets (AUDIO); player.js calls .claim('track') on play

   Nothing here is on window. The desktop shell's names are in main.js. */

export const hooks = {
  reloadLibrary: null,
  vibeKeyViewChanged: null,
  vibeMapGoto: null,
  nowNext: null,
  nowPrev: null,
  nowClearQueue: null,
  audio: null,
};

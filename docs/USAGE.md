# Vibedentify — User Guide

Vibedentify listens to your tracks and tells you their **genre, BPM, and key**, then lets you explore your whole collection as an interactive **map of sound** — or browse it as a sortable **list**. It's built for DJs, producers, and collectors who want to understand and organize a library fast.

Everything runs on your own machine: **your audio never leaves the computer, and your files are never changed** — analyzing only reads them.

*Just want to install or run it? See the [README](../README.md). This guide is about* using *the app.*

---

## Contents

1. [Getting started](#1-getting-started)
2. [Adding your music — and which method to use](#2-adding-your-music--and-which-method-to-use)
3. [Reading a track](#3-reading-a-track)
4. [Two deeper looks: Refine & Compare](#4-two-deeper-looks-refine--compare)
5. [How the genre is decided — the lens system](#5-how-the-genre-is-decided--the-lens-system)
6. [Organizing your library: overrides, vibes & playlists](#6-organizing-your-library-overrides-vibes--playlists)
7. [The Library tab — your collection as a sortable list](#7-the-library-tab--your-collection-as-a-sortable-list)
8. [Exploring the Map](#8-exploring-the-map)
9. [Harmonic mixing (for DJs)](#9-harmonic-mixing-for-djs)
10. [Options & settings](#10-options--settings)
11. [Good to know](#11-good-to-know)

---

## 1. Getting started

The app has seven tabs across the top, roughly in the order you'll use them:

- **≣ Library** — every track you've ever analyzed, as a fast, searchable, sortable list. This is where you land when you open the app.
- **≣ Analyzer** — where new music comes in. Drop tracks here to read their genre / BPM / key.
- **✷ Map** — a 3-D "constellation" of everything you've analyzed, for exploring by sound.
- **◉ Genres** — every genre found in your library: what it is, how fast it runs, and your best tracks in it.
- **◈ Vibes** — your own categories: moods and sets you invent yourself.
- **ⓘ Guide** — this document, in-app.
- **⚙ Options** — status and settings (engine, database, version).

**To try it right now:** go to **Analyzer** and drag an audio file anywhere onto the window. In a second or two you'll see its genre, tempo, key, and a colored waveform. That's the whole loop — analyze on **Analyzer**, then browse it on **Library** or explore it on **Map**.

> **New here? The two words to learn.** A **genre** is decided *for* you — Vibedentify listens to the track and works out what it is. A **vibe** is decided *by* you — your own label for a mood, a moment, or a set. Genres live on the **Genres** tab, vibes on the **Vibes** tab, and both show up on the **Map**.

**A quick mental model.** Vibedentify doesn't slap one label on a track. It listens *moment by moment* across the whole song, guessing the genre continuously, then summarizes those guesses into an overall read. That single idea explains a lot of the app: the **waveform** shows the moment-by-moment guesses, the **genre breakdown** shows the summary, and the **lenses** (section 5) let you change how that summary is formed — all instantly, without re-listening to the audio.

---

## 2. Adding your music — and which method to use

There are two ways to get tracks into the analyzer. They do the same analysis; they differ in scale.

### Drag & drop / Browse files

Drag any number of files onto the Analyzer window, or click **⊕ Browse files…**. Supported formats: MP3, FLAC, WAV, M4A, OGG, AIFF, and more. Tracks are processed one at a time; each row appears immediately and fills in when it's done.

> **Use this when** you're checking a handful of tracks, testing a new download, or just poking around. It's the everyday method.

### Batch folder

Click **⊕ batch folder** and give it the path to a folder of music. It scans that folder (and everything inside it) and analyzes every track it finds, several at a time, showing a running `done / total` count.

> **Use this when** you want to bring in a whole library or crate at once — it's noticeably faster than dropping files one by one, and you can walk away while it runs.

**Either way, nothing is ever analyzed twice.** If a track has been analyzed before — this session or months ago — the result comes back instantly instead of being recomputed. So re-scanning a folder only spends time on what's new.

A track you drop in that's **already in your library still appears on the list**, marked `· cached`, with every row control a freshly analyzed one gets. That's how you reach **adjust**, **override**, **omit** or **lookup** for a track you already know about without going hunting for it in the Library. Drop the same file twice and the list scrolls to the row it's already on rather than adding a second one. (**⊕ batch folder** still only lists what's *new* — a whole-library re-scan would otherwise put thousands of rows on screen.)

---

## 3. Reading a track

Each analyzed row shows three things:

- **Track** — the title with a **genre-colored waveform** underneath. The colors come from the moment-by-moment genre guesses, so you can literally *see* where a track changes character — an ambient intro, a drop, a half-time breakdown. Hover the waveform to magnify it; click anywhere on it to **play and seek** from that point. **Shift-drag** a time range to **override that section as a genre** — it repaints in the override style and the extracted clip is saved into that genre's training folder (needs a track added from a folder/batch, not a browser-dropped file). To undo one, **shift-click** its span and confirm **remove** (this also deletes the extracted clip).
- **BPM / Key** — the tempo and musical key. The key is shown in **Camelot** notation (like `8A`), the wheel DJs use for harmonic mixing, alongside the plain key. Next to the length sits the **⚡ energy level**, 1–10 (section 9).
- **Genre** — the breakdown: the dominant genre(s) and their share of the track, tagged with the broad **family** they belong to (House, Trance, Bass Music, …). If a read looks shaky, you may also see a **⚠ "sounds like …"** hint suggesting a better fit (see section 6).

Every analyzed track also has a built-in **preview player** — play and scrub it right from its waveform.

---

**Vibes and tags** share one wrapping strip at the bottom of the genre column rather than a line each, so a track in two vibes with three tags doesn't push everything below it down the row.

**The waveform.** Each row draws a rough shape immediately and then replaces it
with a detailed one a moment later. Tracks that were dragged in and analysed
without ever being linked to a music folder used to be stuck on the rough version
forever — the app had no copy of the audio to draw the detailed one from. Dropping
such a track in now sends the audio along with it, once, so it draws at full
detail from then on.

---

## 4. Two deeper looks: Refine & Compare

These are optional, on-demand tools you run on a single track when the normal read isn't enough. You'll find both on each row.

### fine (Refine) — for tracks that change mid-song

Click **fine** to re-analyze that one track at much higher time resolution. The normal read looks at the track in coarse chunks; **fine** looks at it in fine slices, so brief genre shifts stop getting smeared together.

> **Use this when** a track clearly moves between styles — a DnB tune with a half-time breakdown, an intro in a totally different vibe — and you want to see exactly where those switches happen. (It costs more compute, which is why it's on demand.)

### ⚖ compare engines — a second opinion

Click **⚖ compare engines** to run a *second*, different AI model alongside the default one and see both reads plus a blend, with a live **slider** between them.

> **Use this when** a genre read looks off and you want a tie-breaker. If both models agree, trust it. If they disagree, the track is genuinely ambiguous — which is useful to know on its own. (The second model is slower, so it only runs when you ask.)

---

## 5. How the genre is decided — the lens system

Because the genre read is a *summary* of moment-by-moment guesses, there's no single "correct" way to summarize — it depends on what you care about. **Lenses** let you switch between summaries instantly (nothing is re-analyzed). Set a default in the header; any single row can use a different lens on its own (marked with a `*`).

There are two lenses.

### Identity lens — "what genre *is* this track?"

This decides the overall label.

- **v2 · salience** *(default)* — weights the loud, confident, recurring parts of the track more than a brief or quiet moment. **Pick this** for the most "human" answer — a track whose drops are Dubstep reads as Dubstep even if the intro is Ambient.
- **v1 · flat %** — just counts how much of the track (by time) each genre wins. **Pick this** if you want a simpler, more literal split that treats a quiet intro the same as the main section.

### Segmentation lens — "what plays *when*?"

This controls how the **waveform** is colored — how the moment-by-moment stream is grouped into visible sections.

- **raw** — every instant's single top genre. Most detailed, but flickers between near-identical labels.
- **hysteresis** *(default)* — sticks with the current genre until a challenger clearly wins for a while. Kills the flicker and shows real sections. A good everyday choice.
- **sibling-merge** — first pools near-synonyms (Deep House / Tech House / Bassline → House) so cousins don't fight. The groups are **editable** via the **siblings ⚙** button.
- **family** — rolls everything up to broad families (House, Trance, Techno, Bass Music, …). The coarsest, big-picture view.
- **hyst + sibling** — sibling-merge *and* hysteresis together: grouped and smoothed. The cleanest read of a track's structure.

> **Rule of thumb:** leave both on their defaults (salience + hysteresis) for normal use. Reach for **family** or **sibling-merge** when the raw genres feel too granular, and **raw** or **fine** (section 4) when you want maximum detail.

Very minor genres in the stream collapse into a single grey **"Other"** bucket so the picture stays readable.

---

## 6. Organizing your library: overrides, vibes & playlists

Per-track actions live on each row (and many are repeated in the Map popup); library-wide tools sit in the footer.

### Per-track fixes

- **⚖ adjust** — nudge how much of each genre a track is, instead of replacing the read. An override answers *"what is this?"* with one word and throws away everything the model got right; a track reading Techno 66% / House 17% / Tech Trance 16% is *mostly* right. This bends it: **＋** and **−** on each genre move it from *not at all* through *as read* to *very*, and the percentages re-settle around it. You can also **type a genre it missed** to add one, or **✕** a genre to take it off the track entirely — which is a different statement from pushing it all the way down (*"not at all"* leaves it in the read at a trace; **✕** removes it). Anything you remove is listed under **removed**, and clicking it there puts it back. The same panel is on the Map popup, on the same track — adjust it in either place and both agree.
- **✎ override** — set the genre yourself (say your own *Riddim* or *Tearout*). Your choice **sticks everywhere and survives reloads** — it becomes the track's genre on the Analyzer, the Library, the Map, and exports, and re-adding the file later keeps your label instead of the model's. (It also copies the track into `~/genre_training/<genre>/` — those folders are the training set for a **custom genre head**: once you've labelled enough tracks, the scripts in `training/` can train a model that adds your own genres as a **custom** row in each read. See *Training custom genres* in the README.) The same override is on the **Map popup** and behaves identically. To undo one, **omit** the track and re-scan it.
- **✕ omit** — remove a track's analysis (for a bogus read you don't want cluttering things). It disappears from the Analyzer, the Library, and the Map, and the database entry is deleted. **Your audio file is untouched** — re-scanning brings it back fresh.
- **Tags** — attach your own labels ("high energy", "opener", "peak time") to tracks for your own organization.
- **Hovering a chip previews it.** Point at a genre, artist or tag chip in the
  Map popup and every track it would show you flashes white and fades, over and
  over, so a scattered handful of matches is findable among three thousand stars
  without clicking anything. The **genre tier chips above the title** are chips
  too: the subgenre filters by style, the genre by keystone (a fusion counts
  under both parents), the archgenre by itself — hover to preview, click to
  filter, click again to clear.
- **⚠ review reads** *(footer)* — a one-click sweep for likely mistakes. The app flags reads it's unsure about — specifically, a low-confidence label whose closest-sounding neighbors strongly disagree (the classic "a bass track got called K-pop" case). The panel lists every flagged track with its suggested fix, plus buttons to jump to it on the Map or omit it. It only ever **flags and suggests** — it never changes a genre on its own.
- **Clear list** empties the on-screen Analyzer list (without deleting any analysis); **Export .txt** dumps the current list (genre, BPM, key, duration) to a text file.

### ◈ vibes — playlists by feel

A **vibe** is a playlist built from *sound*, not hand-picking. Add a few tracks to a vibe (with **+ vibe** on a track) and it gathers everything else in your library that *sounds* similar, ranked by closeness. 👍/👎 individual tracks to steer the vibe toward or away from examples.

Open the **◈ vibes** panel to manage them. Each vibe row has:

- **tracks** — show the tracks currently seeding the vibe.
- **playlist** — build a playlist of everything in your library that matches this vibe (drops straight into the playlist panel, below).
- **✎ rename** · **↺ reset** (put every track's weight back to the default 1.0, undoing your 👍/👎 nudges) · **⌫ clear** (remove all tracks but keep the empty vibe) · **✕ delete** (remove the vibe entirely).
- At the top of the panel, **⭳ export** saves *all* your vibes to a `.json` file and **⭱ import** loads vibes from one (merging by name) — handy for backups or moving vibes between machines.

### Playlists — a queue you can save

The **☰ playlist** button (footer, and on the Map) opens the playlist panel — an ordered queue you build up, then play or export:

- Add tracks with **add to playlist** (Map popup) / **+ playlist** (the now-playing bar), or all at once from a vibe's **playlist** button.
- The bar itself has **▶ play/pause**, a **seek** strip, **↻ replay** (start the track over), **volume + mute**, and **✕ stop**. Volume and mute are remembered between sessions, separately from the Map's sample volume (section 8).
- **▶ play all** plays the queue in order.
- **★ save** stores the current queue under a name; **☰ saved** lists your saved playlists to reload or delete. Saved playlists live in the database, so they persist across restarts.
- **⭳ .m3u** exports the queue as a standard **`.m3u`** file — the universal playlist format that opens in VLC, Rekordbox, Serato, foobar2000, and most DJ/player software, pointing at your actual audio files.
- **clear** empties the queue (your saved playlists are untouched).

---

## 7. The Library tab — your collection as a sortable list

The **≣ Library** tab is every track you've ever analyzed, shown as a plain text table — no waveforms, so it stays fast even at many thousands of tracks. It's the counterpart to the Map: where the Map is for *exploring by sound*, the Library is for *finding and sorting by the facts* (title, artist, BPM, key…).

- **Search** — type to filter by title, artist, genre, key, or Camelot code as you go. The count shows how many match.
- **Sort** — pick a field from the **sort** dropdown and flip **▲ / ▼** for ascending/descending, or just **click any column header** to sort by it (click again to reverse).
- **▦ columns — choose what you see.** Click **▦ columns** (or **right-click any column header**, Windows-Explorer style) to toggle which columns appear: **Title** (always on), **Artist**, **Genre**, **BPM**, **Key**, **Camelot**, **Energy** (the 1–10 level, section 9), **Length**, and **Added** (the date analyzed). Show only the columns you care about.
- **Group by — collapsible sections.** Use the **group by** dropdown to split the list into collapsible sections by **Genre**, **Key**, **Camelot**, **BPM range**, or **Artist**. Each section shows its track count; **click a section header to collapse or expand it** — great for folding away genres you're not looking at and focusing on one at a time.
- **Click any row** to load that track into the **Analyzer** tab (with its full waveform and per-track tools).
- **↻ refresh** reloads the library; **⭳ .txt** downloads the currently visible columns as a tab-separated text file (opens in Excel/Sheets).

Your choices here — which columns show, the sort, the grouping, and which sections are collapsed — are **remembered** between sessions.

---

## 8. Exploring the Map

The **✷ Map** tab plots your entire analyzed library in 3-D. **Tracks that sound alike sit near each other**, faint lines connect each track to its closest sonic neighbors, and color = genre family. It's the fun part — a birds-eye view of your whole collection.

### Four layouts — and which to use

Switch between them with the buttons at the top. Each view's own controls appear on the toolbar's second row, under the view buttons, while that view is showing — so the first row reads the same wherever you are. They answer different questions:

- **◎ regions** *(default)* — organized by genre: each family forms its own cluster, and within a family tracks group by subgenre (Dubstep and Drum n Bass sit apart). As you zoom in, big family labels give way to subgenre labels. **Use this to** see your library laid out by genre and find where a style lives.
- **✦ universe** — your library as a sky of **galaxies**. Each galaxy is a group of tracks, and you choose what a galaxy means with the dropdown next to the buttons: **by genre** (one galaxy per archgenre) or **by vibe** (one galaxy per vibe you've made, with everything unfiled drifting as background stars). Inside a galaxy, position is still pure sonic similarity. **Use this to** see how your own categories sit relative to each other, and to spot surprising neighbours the genre labels miss.
- **☼ solar** — a saved **playlist** as a solar system. The dropdown on the view's bar picks which playlist is the sun — or **all playlists**, which lays every saved playlist out as its own system so the whole collection is in view at once (a track in several playlists orbits the first that claims it). The list keeps up with the playlist panel: **save a playlist while the Map is open and it appears right away.** The playlist's name is the sun, and every track orbits it. The **rings** dropdown decides what distance means: *fit* (how close a track is to the playlist's overall sound — the core hugs the sun, the odd ones out orbit far away), *tempo*, or *genre*. **Use this to** sanity-check a set: anything way out on the last ring probably doesn't belong.
- **⊢ tree** — your library as a branching **taxonomy**: root → genres → subgenres, with bigger branches for the parts of your collection you have more of. Tick **EDM only** on the view's bar to drop the rock, pop and spoken-word a DJ library picks up, so the diagram is the electronic taxonomy and nothing else, and **☵ genres** opens a checklist of every branch so you can take any single genre off the tree. **Use this to** understand the make-up of your library at a glance (hover a branch to reveal its track count).

**At a glance** — the same library, arranged four ways:

```
◎ REGIONS  —  arranged by GENRE
     ·House·                ·Techno·
   ····                          ····
        ·····Bass Music·····
   ·Trance·                 ·Chill-out·
   -> each genre is its own cluster;
      subgenres form patches inside it.
      "where does a genre live?"

✦ UNIVERSE  —  arranged into GALAXIES
      ..:'Sunset Warmup':..
     . *  *   *  *  .          ..:'Peak Time':..
      ':.  *  * .:'           . *   *  *  *  .
   ·   ·    ·                  ':.  *   * .:'
   (unfiled tracks drift as background stars)
   -> one galaxy per vibe, or per genre;
      inside each, position = pure sound.
      "how do my own categories relate?"

☼ SOLAR  —  ONE PLAYLIST as a system
        ☼ "Sunset Warmup"
    ◦ ─── the core      (28)
      ◦ ─── close fit   (28)
        ◦ ─── fits      (28)
          ◦ ─── outliers (28)
   -> the sun is the playlist; distance
      is fit, tempo, or genre.
      "does this set hang together?"

⊢ TREE  —  the HIERARCHY / proportions
   root ─┬─ Bass Music ─┬─ Dubstep
         │              └─ Drum n Bass
         ├─ House ──────┬─ Deep House
         │              └─ Bassline
         └─ Techno ───── …
   -> a branching taxonomy; longer
      branches = more tracks.
      "what's the make-up of my library?"
```

Regions, universe and solar are the explorable 3-D views (drag to orbit, click a genre to fly in); tree is a flat 2-D diagram of the structure.

### ⊙⋮ Galaxies (Universe view)

In **✧ universe** each genre is its own galaxy, and the sky is built the way a
sky is built rather than laid out on a grid.

- **Size is mass.** A galaxy's width grows with the square root of its track
  count, so your 1,360-track House galaxy really is the biggest thing out there
  and a 40-track genre is a legible speck rather than the same blob at a
  different address.
- **They face different ways, and they turn.** Each galaxy gets its own stable
  tilt and its own rate and direction of spin, seeded from its name, so it looks
  observed rather than drawn. Its disc is wound into trailing arms — the outside
  lags the inside, which is what makes a rotating disc a spiral. The orbit-speed
  slider sets how fast everything moves and pausing it stops them; the camera
  holds still here, because spinning it as well would give you two unrelated
  motions and no way to tell which is which.
- **Made of systems.** A genre is not a smooth thing — House is Progressive
  House and Bassline and Electro House and Tech House, and those are real
  divisions with their own sound. Each one is its own cluster inside the galaxy,
  in its own orbit around the middle, with its tracks turning inside it: a moon
  goes round faster than its planet goes round the sun. Where a system sits comes
  from its members' sound, so subgenres that genuinely resemble each other are
  neighbours. Always one tier below whatever a galaxy is, so family galaxies are
  made of genres and genre galaxies are made of subgenres.
- **Bright in the middle, and full of gas.** Stars concentrate toward the centre
  of each system and thin out toward its edge, and each system carries a cloud of
  lit gas in its own colour. Stars alone draw a galaxy as points with nothing
  between them; the gas is the thing every photograph of one has that a scatter
  plot does not. It follows the **Glow** slider under **🏷** — turn that to 0 and
  the gas goes with it.
- **Only the links inside a galaxy are drawn.** A similarity line between two
  galaxies is true, but strung across the gap that is meant to separate them it
  is the one thing that stops the sky reading as a sky. Inside a galaxy the same
  lines trace its structure. Selecting a track still shows its own web across the
  whole map, because "what else sounds like this" is a question about elsewhere.
- **Gravity places them.** Nothing is assigned a slot. Galaxies repel by mass, so
  the big ones claim room, and attract along the similarity links your library
  already has — so genres whose tracks are genuinely each other's nearest
  neighbours drift together. That is where the swirl comes from: a genre that
  bridges two others gets pulled between them and all three end up in one
  another's tide, with the outer stars streaming toward the neighbour. None of
  that is hardcoded — take the bridge tracks out and the pull goes with them.

Three controls behind **⊙⋮**:

- **Separation** — how much empty space sits between galaxies. It widens the
  gaps, not the galaxies: scaling both would just be zoom, which is why the old
  version of this control appeared to do nothing.
- **Gravity** — how hard related genres pull on each other. At 0 they spread out
  evenly and ignore each other; turn it up and the related ones clump and swirl.
- **Spread** — how far apart the stars inside each galaxy sit. The galaxies stay
  where they are and grow or shrink into the space between them, so past about
  1.5× neighbours can start to touch — raise Separation with it. Both dials go a
  very long way (Separation to 100×, Spread to 20×), and the sliders are
  logarithmic so the useful low end is not crushed into a few pixels.

**◎ regions** has the same two dials behind **◎⋮** on its own row: **Separation**
moves the genre clusters out from the middle (the biggest stays at the core),
**Spread** is how far each cluster's stars reach from its centre.

Galaxy names are sized by how big the galaxy is, and only the biggest sixteen
are shown at once — naming seventy galaxies at the same time means naming none of
them, because no single one can be read. The rest are a hover or a zoom away, and
**Max genre labels** under **🏷** overrides the cap if you want them all.

The **galaxy =** picker chooses what a galaxy *is*: **genre** (the default, one
per keystone — Dubstep and Drum n Bass are different places), **family** (the old
behaviour: Bass, Dance, Chill as single galaxies) or **vibe** (your own
categories).

### ⏱ Recently viewed

Every star you open is remembered — the last 24, newest first — behind the **⏱**
button in the map toolbar. Click any of them to go straight back to that star.
It survives closing the app, drops tracks you have since omitted, and **clear
history** empties it. The list is kept in your browser, not in your library:
which tracks you happened to look at is a trail through an evening's listening,
not a fact about the music.

### Making the map readable

The **🏷 labels** button opens the display options. The ones worth knowing:

- **Hide all text** — every label off in one switch, when you just want to look at the shape of your library.
- **Lines from labels to genres** — off by default. Turn it on if you want each label tied back to its cluster by a dashed line; on a dense map they add clutter, which is why they start off.
- **Label background** — *outline only* is lighter; *solid plate* is easier to read over a crowded cluster.
- **Glow** — how far each star's light spreads into the black around it. Every track is drawn as a coloured disc with a halo of its own colour, so a cluster reads as light being emitted rather than dots printed on black. Slide it up for a brighter sky, or down to **0** for plain flat discs. Dense clusters stay legible at any setting: the disc itself is solid, so neighbours overlap rather than blowing out to white.
- **Flicker** — *off*, *subtle*, or *all stars flicker* for a live night-sky feel.
- **Size stars by rating** — bigger star = better rating, so your best music is the most visible thing on the map. **Count artist ratings too** means a track by an artist you rated highly is boosted even if you haven't rated that particular track. Unrated tracks stay small but visible — nothing ever disappears.

### Rating tracks and artists

Click any track to open its popup. It has **two** rating blocks:

- **Rate this track** — stars, a letter grade and a note, for that one recording.
- **Rate the artist** — the same three fields, applied to *everything* by that artist.

They're deliberately separate: a favourite artist still puts out the odd weak track, and a great track can come from someone you otherwise don't rate. Ratings live in this app's database only — **nothing is ever written to your audio files** — and they materialise when you export a playlist to Rekordbox.

### Getting around

You can **orbit** (rotate), **pan** (slide), and **zoom** independently. The **⌨ nav** button beside the speed control lists every control; the **◤ genres** legend at the bottom-left starts closed — it sits on top of the map, and what you came for is behind it.

**🚀 fly** (or `V`) puts you *in* the field instead of looking at it: a first-person camera you walk with **W A S D**, rise and sink with **Q / E**, look around by dragging (or the arrow keys), with **Shift** for speed and the **scroll wheel** to set your pace. Stars grow as you approach them, so a galaxy is a place you move through rather than a picture. Click a star to open its panel as usual — the camera stays yours. **F**, view reset, or `V` again lands you back in the orbit view.

The camera also backs off as the map gets bigger, so the perspective stays the
same whatever the layout is measuring. It used to sit at a fixed distance, which
meant a large sky had part of itself at or past the lens — stars magnified wildly
and vanished as you orbited.

You can also now zoom out much further than before — the floor was close enough
to the fit view that there was no way to stand back from the map, which a sky of
mass-sized galaxies needs.

- **Mouse:** left-drag orbits · right-drag / middle-drag / **Shift + left-drag** pans · scroll zooms into wherever you point.
- **Keyboard:** **W / S** zoom in / out · **A / D** orbit left / right · **arrow keys** pan · `+` / `-` also zoom · `space` play/pause the spin · `f` fit · `esc` close a popup.
- The map gently **auto-spins**; the **⏸ / ▶ button** (next to the speed slider) or `space` pauses it, and the **↻ slider** sets the speed.
- **What it orbits around.** With nothing selected the camera settles on your library's **centre of mass** — the densest part of the cloud, found by walking uphill into the crowd rather than averaging every position (an average lands in the empty space *between* two clusters). That point is the centre of the frame and the axis the map spins around, so the busiest music is what you are looking at by default. Click a genre and it orbits that cluster instead; click a track and it orbits the track; close the popup and it eases back to the centre of mass.
- **Panning re-aims the camera** — it doesn't just slide the picture. Whatever you drag to the middle becomes the new point the view rotates around, and it *stays* there through the next orbit and zoom. That's what lets you get out from under a fixed centre: in **☼ solar**, push the sun off to one side and spin around a particular ring instead of always circling the star. **⊙ view reset** (or `f`) puts the camera back on the resting centre.

### Showing only the genres you want

The **☰ filter** panel lists every genre in your library with a tick-box and a
track count. Untick one and it comes off the map. **all** / **none** do the
obvious thing, and **electronic** ticks everything the genre taxonomy could
actually place (Dance, Bass, Chill, Experimental), which leaves out the metal,
punk and hip hop that land in *Other* in a mostly-electronic library.

Like every filter here it only hides. The layout is worked out from your whole
library, so the stars that remain keep their positions.

### Only tracks with audio

Under **☰ filter** there's **Only tracks with audio**. It hides stars whose audio file was never found — usually tracks dragged in and analyzed without ever being linked to a folder. They can't be previewed or exported, so they're stars you can look at but not use.

**It only hides them.** Where every star sits is worked out from your whole library, so the ones left keep their exact positions and their neighbours still mean what they meant — same map, fewer dots. To bring them back for real, repair their paths under **⚙ Options → Music file paths**.

### Selecting a track

**Click the title in the now-playing bar** to go back to whatever you're listening to: the map cuts straight to that track's star and opens its panel. Playback isn't interrupted — you arrive at the star still hearing the track rather than being cut off by a preview of it. **The sample strip's title works the same way**, so an audition you like is one click from the star it came from; if that clip is still playing, going back to it doesn't restart it.

Arriving this way is a *cut*, not a flight: the map opens already centered on the star rather than framing your whole library and zooming in. Clicking a dot on a map you are already looking at still glides, because there the movement is what tells you which star you picked.

**Click any dot** (or use the **Search** box to fly to one). The view re-centers to orbit around it, and a popup opens with: its genre, tempo, key, and other reads it was close to ("also reads as"); **similar artists** and **similar tracks** pulled from across your library; a **🎲 "a match for you"** suggestion (with a re-roll) — a quick way to surface something you forgot you had; and **⚖ adjust** / **✎ override** / **✕ omit** / **add to playlist** buttons (same actions as the Analyzer, on the same track).

Above the title is the track's genre, read narrow to wide: **subgenre · genre · archgenre** — *Grime · Dubstep · Bass*. A tier that would repeat the one beside it is dropped rather than printed twice, so a House track says *House* once and a Progressive House track says *Progressive House · House*: House is the top of its own tree, not a room inside something wider. The chips share the star's own colour and get more solid as they widen, so the widest one is the chip the card has always shown and the narrower ones read as detail hanging off it.

Selecting a track also **auditions it**: a ~22-second clip starts from the track's *drop* (its first sustained burst of energy, or 40% in if there isn't one). A **sample strip** appears above the now-playing bar with its own **▶ play/pause**, **↻ replay** (back to the drop), **■ stop**, and **volume + mute** — so auditioning can sit quietly under whatever else you're doing.

**Listening to — sample / track.** When something is also playing in the now-playing bar, the strip shows a switch, and it *sticks*: choose **track** and clicking around the Map keeps cueing samples but never interrupts you (the strip says "held"); flip to **sample** and it plays that clip instead, pausing the track. Each side keeps its own volume, so a sample can be a quiet audition underneath a loud track. Starting full playback — the popup's **▶ play**, a List row, the playlist — counts as choosing **track**.

### Why the map opens instantly (and the ↻ rebuild button)

Building the map means reading every track in your library, working out what each
one is, and placing every star. That used to happen from scratch every single time
you opened the Map tab — which is why coming back to it, or jumping to the playing
track, sat on *building your map* for several seconds to arrive at the map you had
just left.

Now it is built once and kept, on both sides: the app remembers the built map for
as long as it is open, and the result is also stored next to your library file, so
**reopening the app doesn't rebuild it either**. Anything that changes your library
— analysing new music, an override, an adjustment, an omit, a tag, a palette
change, editing the taxonomy — invalidates it automatically, so the map you see is
never out of date with the library it came from.

The app deliberately assumes the worst here: *anything* it writes to your library
counts as a change, because a map that quietly disagrees with your library is much
worse than a slow one. But most of those writes turn out not to touch the map at
all — rating a track is the common one — so before rebuilding it asks the library
one cheap question: *would the map come out the same?* If it would, nothing is
rebuilt and nothing moves. Rating a track and then jumping to another one no longer
tears down the galaxy you were reading.

**↻ rebuild** forces a fresh build anyway. You shouldn't need it, but it's there
if something ever looks out of step.

### Map controls

The toolbar is two rows. The first is **what you are looking at**: search, the
four views, and **what is shown** (the genre picker, harmonic, the connection
lines, and the filter / recently-viewed / text panels). The second is **motion**
(pause and speed), then **the active view's own controls** — the Universe's
galaxy dropdown and ⊙⋮ sliders, Solar's playlist and rings pickers, the tree's
EDM-only switch — which appear only while that view is showing, and at the far
end the track count with the **actions** (playlist, rebuild, view reset). On a
narrow window a row wraps a whole group at a time rather than squashing what is
in it.

- **Search** — jump to any track, artist, or genre.
- **Click a genre or subgenre name** — on the map, or in the legend — to fly to that cluster and orbit around it (subgenres zoom in a little tighter than their overarching genre).
- **🎧 harmonic** — highlight what you could mix next (see section 9).
- **≈ edges** — show or hide the connecting lines.
- **Genre legend** *(bottom-left, collapsible)* — groups each **overarching genre** with its **subgenres** beneath it (in their shade colors), so you can see the hierarchy. Click a genre or subgenre **name** to fly to it; click a genre's **color dot** to recolor it (your colors are remembered).
- **Genre filter** *(top-bar dropdown)* — show just one genre, or just the **⚠ likely misreads**.
- **fit** — reset the view and clear any filter.

Each track's dot is a **shade of its genre's color** keyed to its subgenre, and leans toward its second-closest genre's color — so a big cluster visibly shows the subgenres inside it, and tracks that sit between two genres get a blended, in-between color.

You can also share a view: the address bar updates as you go (`#map`, `#universe`, `#solar`, `#tree`, `#review`), so those links reopen the same place. (`#galaxy` still works — it's the old name for `#universe`.)

---

## 9. Harmonic mixing (for DJs)

On the Map, select a track and turn on **🎧 harmonic**. Vibedentify rings every track that would mix smoothly with it — matching **key** (neighbors on the Camelot wheel, or the relative major/minor) **and tempo** (within about ±6%, or at half/double time) — and dims everything else.

It turns the Map into a "what can I play next?" tool: pick a track, flip harmonic on, and your compatible options light up across the whole library. Pair it with the **playlist** panel (section 6) to build a harmonically-ordered set, then **⭳ .m3u** it into your DJ software.

### ⚡ Energy level

Every track gets an **energy level from 1 to 10** — the same scale Mixed In Key popularised — shown next to its length in the Analyzer, in the Map popup, and as a sortable **Energy** column in the Library. It's a read of how hard the track hits *at its peak*: loudness (in real dBFS, so tracks compare across your library), brightness (hats, noise, distortion), rhythmic density, and tempo (octave-blind — a 174 and an 87 BPM read of the same drum & bass tune agree). Roughly: ambient and downtempo 1–3, deep house 4–5, house and techno 6–7, tech house and trance 7–8, dubstep, hard drum & bass, hardstyle and trap 9–10. A quiet master of a heavy track reads lower than a loud one — that's deliberate; energy on a dancefloor is partly the master.

Under the waveform, a thin **energy strip** paints the same scale over time — cool blue where the track is quiet, red at its peaks — so you see the arc of a track before you hear it.

### ▼ Cue points

Under the waveform is a row of **cue chips** — click one to play from it. They are detected from the audio, snapped to a beat grid, and numbered in bars from the intro:

- **Intro** — the first audible downbeat (bar 1).
- **Drop 1, Drop 2, …** — where the track steps up into its loudest zone: bass and loudness jump and stay up.
- **Build** — a step up that doesn't reach the peak yet (the energy is climbing).
- **Break** — a breakdown: the step down between drops.
- **Outro** — the last step down that never comes back up.
- **End** — the last audible beat, for planning a mix-out.

Each chip's tooltip gives the bar number and the energy of the section that follows. The markers also sit on the waveform itself, and hovering near one names it. There are at most eight (Rekordbox's count), strongest first, so a busy track never drowns in flags.

The beat grid comes from the analysed BPM refined against the track's own onsets; the bar lines are anchored to the strongest drop, since in electronic music a drop *is* a phrase boundary. Hover the word **cues** to see the grid (BPM and first-beat offset). A track with no usable grid — no BPM, or nothing beat-like to lock onto — still gets cues, just unsnapped and without bar numbers.

Tracks analysed before this feature existed are filled in the first time they appear on the list (from their folder file, or from the file you drop) and stored, so it happens once.

**Rekordbox export** (Library → saved playlist → Rekordbox XML) carries all of it: the cues as **memory cues** named like `Drop 1 (E8)`, the beat grid as the track's tempo and first-beat, and the energy level at the front of the Comments field (`Energy 7 - A - peak time`) — the place Mixed In Key puts it, so Rekordbox sorts and searches it the same way.

---

## 10. Options & settings

The **⚙ Options** tab is a quick status-and-settings dashboard. Each item shows a green ✓ (all good) or amber ⚠ (worth a look) badge.

- **About** — the app version and how many tracks are in your library.
- **Engine** — whether **GPU acceleration** (DirectML) is active and whether **ffmpeg** (used to decode audio) was found. If ffmpeg shows ⚠ *missing*, some formats won't decode — see the README's setup notes.
- **Database** — where your library file lives on disk. Everything you build — analyses, tags, vibes, saved playlists — lives in this one file. Point the **`GENRE_DB`** environment variable at another path to move or share it.
- **Manage** — shortcuts to Browse library, Vibes, Playlists, and this Guide.
- **Appearance** — **Theme**: **Neon** is the app's own look; **Light** is for daylight; **Midnight**, **Synthwave**, **Forest** and **Ember** are the same dark layout in a different key. The map's sky stays dark in every theme — it is a sky. **Key notation** picks how keys are written: **Camelot** (`8A`), **musical** (`A min`), or **both**. Camelot is what you mix by, the musical name is what you read; both together is fine on one row and noise across a whole library. It applies to the Analyzer, the Map and the exported list (the Library tab keeps its own Key and Camelot columns, chosen under **columns**). **Size** scales the whole app, for a small laptop screen or a monitor across the room. The app is dark-themed for now; a light mode is planned for a future update.
- **Playback** — how long a preview **sample** runs, where it starts (**the drop** — the first sustained loud section — **the middle**, or **the beginning**), and whether selecting a star on the map plays one automatically or waits for you to press play.
- **Map** — which view the Map tab **opens on**, and **reset map settings**, which puts every map control (labels, glow, the Universe and Solar sliders, recoloured genres) back to its default without touching your library.
- **Analyzer** — the two lenses every row starts with: **overall genre** (weight the loud, characteristic parts of a track more, or take a plain average) and **genre over time** (how the coloured bands along the waveform are smoothed). The Analyzer's **advanced** panel sets the same two and can override them per track.
- **Preferences** — **reset everything to defaults**: every setting on this tab and every remembered view state. Your library is untouched.

---

## 11. Good to know

- **Cards fold.** On the Genres and Vibes tabs, "How this works", the totals card and every archgenre section close and open from their heading; "How this works" starts closed, the rest open, and the app remembers what you folded.
- **Training data lives on the Genres tab** (under *Library actions*): what the app has collected from your genre corrections, and how ready each genre is for training.
- **Header**: the animation behind the app's name is yours to pick under Options → Appearance — a spectrum in four styles (bars, LED blocks, bubbles, soft glow), a scrolling waveform, a starfield, a spinning record, or nothing.
- **Your files are safe.** Analyzing only reads your audio; it's never modified or moved, and nothing is uploaded anywhere — it all stays on your machine.
- **Nothing is analyzed twice.** Results are remembered by the audio itself, so the same track returns instantly even if you rename or move the file, and re-scanning a big folder only works on what's new.
- **The Analyzer is temporary; your library is permanent.** Reloading the page clears the on-screen Analyzer list, but every analysis is saved — it's all still on the **Library** and **Map**, and re-dropping files repopulates the Analyzer instantly from memory.
- **Vibes and saved playlists persist too.** They live in the database (see Options → Database), so they survive restarts and reinstalls as long as that file is kept.
- **Very large libraries:** the Analyzer can get heavy past a few thousand rows (each keeps a waveform), so for big collections lean on **batch folder** to bring them in, the **Library** tab to sort and search them, and the **Map** to explore them.

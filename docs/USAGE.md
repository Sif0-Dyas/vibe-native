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

The app has five tabs across the top:

- **≣ List** — the analyzer. Drop tracks in and read their genre / BPM / key.
- **≣ Library** — every track you've ever analyzed, as a fast, searchable, sortable text list.
- **✷ Map** — a 3-D "constellation" of everything you've analyzed, for exploring by sound.
- **ⓘ Guide** — this document, in-app.
- **⚙ Options** — status and settings (engine, database, version).

**To try it right now:** stay on **List** and drag an audio file anywhere onto the window. In a second or two you'll see its genre, tempo, key, and a colored waveform. That's the whole loop — analyze on **List**, then browse it on **Library** or explore it on **Map**.

**A quick mental model.** Vibedentify doesn't slap one label on a track. It listens *moment by moment* across the whole song, guessing the genre continuously, then summarizes those guesses into an overall read. That single idea explains a lot of the app: the **waveform** shows the moment-by-moment guesses, the **genre breakdown** shows the summary, and the **lenses** (section 5) let you change how that summary is formed — all instantly, without re-listening to the audio.

---

## 2. Adding your music — and which method to use

There are two ways to get tracks into the analyzer. They do the same analysis; they differ in scale.

### Drag & drop / Browse files

Drag any number of files onto the List window, or click **⊕ Browse files…**. Supported formats: MP3, FLAC, WAV, M4A, OGG, AIFF, and more. Tracks are processed one at a time; each row appears immediately and fills in when it's done.

> **Use this when** you're checking a handful of tracks, testing a new download, or just poking around. It's the everyday method.

### Batch folder

Click **⊕ batch folder** and give it the path to a folder of music. It scans that folder (and everything inside it) and analyzes every track it finds, several at a time, showing a running `done / total` count.

> **Use this when** you want to bring in a whole library or crate at once — it's noticeably faster than dropping files one by one, and you can walk away while it runs.

**Either way, nothing is ever analyzed twice.** If a track has been analyzed before — this session or months ago — the result comes back instantly instead of being recomputed. So re-scanning a folder only spends time on what's new, and re-dropping a file you already have just skips it.

---

## 3. Reading a track

Each analyzed row shows three things:

- **Track** — the title with a **genre-colored waveform** underneath. The colors come from the moment-by-moment genre guesses, so you can literally *see* where a track changes character — an ambient intro, a drop, a half-time breakdown. Hover the waveform to magnify it; click anywhere on it to **play and seek** from that point. **Shift-drag** a time range to **override that section as a genre** — it repaints in the override style and the extracted clip is saved into that genre's training folder (needs a track added from a folder/batch, not a browser-dropped file). To undo one, **shift-click** its span and confirm **remove** (this also deletes the extracted clip).
- **BPM / Key** — the tempo and musical key. The key is shown in **Camelot** notation (like `8A`), the wheel DJs use for harmonic mixing, alongside the plain key.
- **Genre** — the breakdown: the dominant genre(s) and their share of the track, tagged with the broad **family** they belong to (House, Trance, Bass Music, …). If a read looks shaky, you may also see a **⚠ "sounds like …"** hint suggesting a better fit (see section 6).

Every analyzed track also has a built-in **preview player** — play and scrub it right from its waveform.

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

- **✎ override** — set the genre yourself (say your own *Riddim* or *Tearout*). Your choice **sticks everywhere and survives reloads** — it becomes the track's genre on the List, the Library, the Map, and exports, and re-adding the file later keeps your label instead of the model's. (It also copies the track into `~/genre_training/<genre>/` — those folders are the training set for a **custom genre head**: once you've labelled enough tracks, the scripts in `training/` can train a model that adds your own genres as a **custom** row in each read. See *Training custom genres* in the README.) The same override is on the **Map popup** and behaves identically. To undo one, **omit** the track and re-scan it.
- **✕ omit** — remove a track's analysis (for a bogus read you don't want cluttering things). It disappears from the List, the Library, and the Map, and the database entry is deleted. **Your audio file is untouched** — re-scanning brings it back fresh.
- **Tags** — attach your own labels ("high energy", "opener", "peak time") to tracks for your own organization.
- **⚠ review reads** *(footer)* — a one-click sweep for likely mistakes. The app flags reads it's unsure about — specifically, a low-confidence label whose closest-sounding neighbors strongly disagree (the classic "a bass track got called K-pop" case). The panel lists every flagged track with its suggested fix, plus buttons to jump to it on the Map or omit it. It only ever **flags and suggests** — it never changes a genre on its own.
- **Clear list** empties the on-screen List (without deleting any analysis); **Export .txt** dumps the current list (genre, BPM, key, duration) to a text file.

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
- **▶ play all** plays the queue in order.
- **★ save** stores the current queue under a name; **☰ saved** lists your saved playlists to reload or delete. Saved playlists live in the database, so they persist across restarts.
- **⭳ .m3u** exports the queue as a standard **`.m3u`** file — the universal playlist format that opens in VLC, Rekordbox, Serato, foobar2000, and most DJ/player software, pointing at your actual audio files.
- **clear** empties the queue (your saved playlists are untouched).

---

## 7. The Library tab — your collection as a sortable list

The **≣ Library** tab is every track you've ever analyzed, shown as a plain text table — no waveforms, so it stays fast even at many thousands of tracks. It's the counterpart to the Map: where the Map is for *exploring by sound*, the Library is for *finding and sorting by the facts* (title, artist, BPM, key…).

- **Search** — type to filter by title, artist, genre, key, or Camelot code as you go. The count shows how many match.
- **Sort** — pick a field from the **sort** dropdown and flip **▲ / ▼** for ascending/descending, or just **click any column header** to sort by it (click again to reverse).
- **▦ columns — choose what you see.** Click **▦ columns** (or **right-click any column header**, Windows-Explorer style) to toggle which columns appear: **Title** (always on), **Artist**, **Genre**, **BPM**, **Key**, **Camelot**, **Length**, and **Added** (the date analyzed). Show only the columns you care about.
- **Group by — collapsible sections.** Use the **group by** dropdown to split the list into collapsible sections by **Genre**, **Key**, **Camelot**, **BPM range**, or **Artist**. Each section shows its track count; **click a section header to collapse or expand it** — great for folding away genres you're not looking at and focusing on one at a time.
- **Click any row** to load that track into the **List** tab (with its full waveform and per-track tools).
- **↻ refresh** reloads the library; **⭳ .txt** downloads the currently visible columns as a tab-separated text file (opens in Excel/Sheets).

Your choices here — which columns show, the sort, the grouping, and which sections are collapsed — are **remembered** between sessions.

---

## 8. Exploring the Map

The **✷ Map** tab plots your entire analyzed library in 3-D. **Tracks that sound alike sit near each other**, faint lines connect each track to its closest sonic neighbors, and color = genre family. It's the fun part — a birds-eye view of your whole collection.

### Three layouts — and which to use

Switch between them with the buttons at the top. They answer different questions:

- **◎ regions** *(default)* — organized by genre: each family forms its own cluster, and within a family tracks group by subgenre (Dubstep and Drum n Bass sit apart). As you zoom in, big family labels give way to subgenre labels. **Use this to** see your library laid out by genre and find where a style lives.
- **✦ galaxy** — no genre grouping at all; position is *pure* sonic similarity, so clusters form naturally from how tracks actually sound. **Use this to** discover surprising neighbors and natural groupings the genre labels miss.
- **⊢ tree** — your library as a branching **taxonomy**: root → families → subgenres, with bigger branches for the parts of your collection you have more of. **Use this to** understand the make-up of your library at a glance (hover a branch to reveal its track count).

**At a glance** — the same library, arranged three ways:

```
◎ REGIONS  —  arranged by GENRE
     ·House·                ·Techno·
   ····                          ····
        ·····Bass Music·····
   ·Trance·                 ·Chill-out·
   -> each genre is its own cluster;
      subgenres form patches inside it.
      "where does a genre live?"

✦ GALAXY  —  arranged by SOUND
            ····  ·····  ··
        ··························
        ····· ··············· ····
            ····  ······  ···
   -> one blob; a track's position is
      pure sonic similarity, not label.
      "what actually sounds alike?"

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

Regions and galaxy are the explorable 3-D point clouds (drag to orbit, click a genre to fly in); tree is a flat 2-D diagram of the structure.

### Getting around

You can **orbit** (rotate), **pan** (slide), and **zoom** independently. A small **nav legend in the top-left corner** always lists the controls (click its header to collapse it):

- **Mouse:** left-drag orbits · right-drag / middle-drag / **Shift + left-drag** pans · scroll zooms into wherever you point.
- **Keyboard:** **W / S** zoom in / out · **A / D** orbit left / right · **arrow keys** pan · `+` / `-` also zoom · `space` play/pause the spin · `f` fit · `esc` close a popup.
- The map gently **auto-spins**; the **⏸ / ▶ button** (next to the speed slider) or `space` pauses it, and the **↻ slider** sets the speed.

### Selecting a track

**Click any dot** (or use the **Search** box to fly to one). The view re-centers to orbit around it, and a popup opens with: its genre family, tempo, key, and other reads it was close to ("also reads as"); **similar artists** and **similar tracks** pulled from across your library; a **🎲 "a match for you"** suggestion (with a re-roll) — a quick way to surface something you forgot you had; and **✎ override** / **✕ omit** / **add to playlist** buttons (same actions as the List).

### Map controls

- **Search** — jump to any track, artist, or genre.
- **Click a genre or subgenre name** — on the map, or in the legend — to fly to that cluster and orbit around it (subgenres zoom in a little tighter than their overarching genre).
- **🎧 harmonic** — highlight what you could mix next (see section 9).
- **≈ edges** — show or hide the connecting lines.
- **Genre legend** *(bottom-left, collapsible)* — groups each **overarching genre** with its **subgenres** beneath it (in their shade colors), so you can see the hierarchy. Click a genre or subgenre **name** to fly to it; click a genre's **color dot** to recolor it (your colors are remembered).
- **Genre filter** *(top-bar dropdown)* — show just one genre, or just the **⚠ likely misreads**.
- **fit** — reset the view and clear any filter.

Each track's dot is a **shade of its genre's color** keyed to its subgenre, and leans toward its second-closest genre's color — so a big cluster visibly shows the subgenres inside it, and tracks that sit between two genres get a blended, in-between color.

You can also share a view: the address bar updates as you go (`#map`, `#galaxy`, `#review`), so those links reopen the same place.

---

## 9. Harmonic mixing (for DJs)

On the Map, select a track and turn on **🎧 harmonic**. Vibedentify rings every track that would mix smoothly with it — matching **key** (neighbors on the Camelot wheel, or the relative major/minor) **and tempo** (within about ±6%, or at half/double time) — and dims everything else.

It turns the Map into a "what can I play next?" tool: pick a track, flip harmonic on, and your compatible options light up across the whole library. Pair it with the **playlist** panel (section 6) to build a harmonically-ordered set, then **⭳ .m3u** it into your DJ software.

---

## 10. Options & settings

The **⚙ Options** tab is a quick status-and-settings dashboard. Each item shows a green ✓ (all good) or amber ⚠ (worth a look) badge.

- **About** — the app version and how many tracks are in your library.
- **Engine** — whether **GPU acceleration** (DirectML) is active and whether **ffmpeg** (used to decode audio) was found. If ffmpeg shows ⚠ *missing*, some formats won't decode — see the README's setup notes.
- **Database** — where your library file lives on disk. Everything you build — analyses, tags, vibes, saved playlists — lives in this one file. Point the **`GENRE_DB`** environment variable at another path to move or share it.
- **Manage** — shortcuts to Browse library, Vibes, Playlists, and this Guide.
- **Appearance** — the app is dark-themed for now; a light mode is planned for a future update.

---

## 11. Good to know

- **Your files are safe.** Analyzing only reads your audio; it's never modified or moved, and nothing is uploaded anywhere — it all stays on your machine.
- **Nothing is analyzed twice.** Results are remembered by the audio itself, so the same track returns instantly even if you rename or move the file, and re-scanning a big folder only works on what's new.
- **The List is temporary; your library is permanent.** Reloading the page clears the on-screen List, but every analysis is saved — it's all still on the **Library** and **Map**, and re-dropping files repopulates the List instantly from memory.
- **Vibes and saved playlists persist too.** They live in the database (see Options → Database), so they survive restarts and reinstalls as long as that file is kept.
- **Very large libraries:** the List can get heavy past a few thousand rows (each keeps a waveform), so for big collections lean on **batch folder** to bring them in, the **Library** tab to sort and search them, and the **Map** to explore them.

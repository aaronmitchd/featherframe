# Featherframe on your own Pi 5: how the illustrations work, and how to own them

A guide to running Featherframe on a Raspberry Pi 5 with BirdNET-Pi, and to
keeping the illustrations on your own Pi.

---

## 0. The short answer

**A self-hosted Featherframe server doesn't use a Featherframe cloud database.**
It already keeps its own plate library on your Pi:

- **At install:** `install.sh` runs `server/scripts/fetch_plates.py` once. That
  script downloads the public-domain scans (Audubon's Havell edition, plus
  Gould's books) from public sources and stores them in `server/plates/`.
  This is about 2.7 GB.
- **At runtime:** every bird is matched and drawn locally from those files. No
  request is made per detection.

The only outbound calls a self-hosted server makes after install:

| Call | When | Can you avoid it? |
|---|---|---|
| GitHub `releases/latest` (`firmware_release.py`) | Once a day, to offer frame firmware updates | It's harmless. It only fetches an image when a frame is marked for update. |
| `api.openai.com` (`render/genart.py`) | Only if you paste an OpenAI key into the webapp | Don't add a key. Species with no plate then get the typographic fallback. |
| `plates.featherframe.app` (`plate_library.py`) | Only if you set `FEATHERFRAME_PLATE_LIBRARY` to that URL | Don't set it. It's off by default. |

"The cloud" (`cloud.featherframe.app`) only comes into play in two cases:

1. You sign up for **Featherframe Cloud** instead of self-hosting.
2. You use a frame flashed with a **release** firmware build. Those builds set
   `FF_HOSTED_DEFAULT` (`firmware/include/ff_config.h:204`) and start pointed
   at the cloud. DIY builds start with no server and find yours over mDNS. A
   cloud-pointed frame can also be redirected: type your Pi's URL into its
   setup portal.

So you don't have to build anything to avoid the cloud. Sections 1–5 explain
how the existing system works. Section 6 covers taking full ownership: pinning
your own plates, mirroring the sources, and adding your own illustrations.

---

## 1. The whole pipeline at a glance

```
 BUILD TIME (once, needs internet)
 ─────────────────────────────────
 scripts/folios/*.yaml  ──►  scripts/fetch_plates.py  ──►  plates/index.json
 (crosswalk: modern                (downloads scans)        plates/img/*.jpg
  species → plate no.)

 RUN TIME (offline, every 5 s)
 ─────────────────────────────
 ~/BirdNET-Pi/scripts/birds.db  (read-only)
        │  birdnet.py: SELECT … WHERE rowid > :cursor
        ▼
 service.py tick()  ── which picture? (latest bird  or  the day's collage)
        │
        ▼
 Provider chain (render/provider.py)
   PlateProvider ── names.SpeciesIndex.match()  (exact scientific name)
        │ none?
   GeneratedArtProvider (only with an OpenAI key)
        │ none?
   typographic fallback  ("never a wrong bird")
        │
        ▼
 render/plate.py    crop the scan to the bird, clean the paper
 render/compose.py  lay out on a 1404×1872 sheet + caption + corner marks
 render/collage.py  (or) grid of N plates + date + numbered key
 render/pipeline.py fit to panel, mat inset, dither to 16 grays, pack
        │
        ▼
 data/frames/drawn/…  (.fff framebuffer + .png preview, named by hash)
        │
        ▼
 Frame:  GET /api/frame  (If-None-Match: <etag>)  → 304, or new pixels
```

Every web request only reads bytes that are already drawn. Nothing is rendered
inside a request.

---

## 2. How illustrations are fetched (build time)

### 2.1 Folios: the crosswalks

`server/scripts/folios/` holds one YAML file per historical edition, called a
"folio":

| File | Edition | Species pinned | Region |
|---|---|---|---|
| `havell.yaml` | Audubon, *The Birds of America* (Havell, 1827–38) | ~457 (27 marked `plate: none`) | north-america |
| `gould_europe.yaml` | Gould, *Birds of Europe* | ~406 | europe |
| `gould_britain.yaml` | Gould, *Birds of Great Britain* (gap-filler) | 7 | europe |
| `gould_australia.yaml` | Gould, *Birds of Australia* | ~402 | australia |
| `gould_asia.yaml` | Gould, *Birds of Asia* | ~256 | asia |

Each folio maps a **modern species, as BirdNET names it**, to a **plate
number** that a person checked by eye:

```yaml
- {common: "Northern Cardinal", scientific: "Cardinalis cardinalis", plate: 159, audubon_title: "Cardinal Grosbeak"}
- {common: "House Finch", scientific: "Haemorhous mexicanus", plate: 424, composite: true,
   sci_synonyms: ["Carpodacus mexicanus"]}
```

Useful per-entry fields:

| Field | Meaning |
|---|---|
| `plate` | The plate number, or `none` (that folio has no plate for it, so the next folio is asked) |
| `composite` | Several birds on one sheet: shown whole, never cropped to one bird |
| `sci_synonyms` | Older Latin names BirdNET might report |
| `crop_box` | `[x, y, w, h]` (0–1): a hand-placed crop |
| `margins` | `[l, t, r, b]` (0–1): the part of the sheet kept (default `plate.HAVELL_MARGINS`) |
| `mask` | Boxes whose lettering is painted out with the paper colour |
| `legend` | Lines printed under the name (Havell's come from `scripts/legends.yaml`) |

### 2.2 `fetch_plates.py`: where the scans come from

**Havell (Audubon).** Sources are tried in this order, and every file is
checksummed:

1. This repo's GitHub release `plates-v1`: the whole edition as tarballs of
   about 100 plates each (`featherframe/plate_release.py`). A tarball is only
   fetched when at least 8 of its plates are missing.
2. `raw.githubusercontent.com/nathanbuchar/audubon-bird-plates`, a mirror of
   audubon.org's public-domain scans. Its `data.json` is the plate catalog.
3. `media.audubon.org/boa_illustration/…`.

**Gould folios.** Each folio's header has a `scans:` URL template. Gould's
books come from the Biodiversity Heritage Library's public S3 bucket. If that
fails, the fallback is the `wr/historical-bird-plates` dataset release. On
download, a Gould scan is turned upright (`rotate`) and its paper is evened to
white (`flatten`).

**Output.** `plates/index.json` (every folio's species and headers) and
`plates/img/`. The script is idempotent: a re-run only fetches what's missing.
Useful flags:

```bash
python scripts/fetch_plates.py --dry-run     # resolve, download nothing
python scripts/fetch_plates.py --all         # cache EVERY Havell plate (~2.9 GB), not just the pinned species
python scripts/fetch_plates.py --no-release  # skip the GitHub tarballs
python scripts/fetch_plates.py --folios DIR  # use a different folio directory
```

If you leave an entry's `plate:` out, `fetch_plates` uses `names.fuzzy_resolve_plate`
to suggest one by title and prints it for you to pin. That fuzzy match only
runs at build time. **It is never used live**, because token overlap picks
wrong birds (for example, "European Starling" matches a blackbird plate).

---

## 3. How a detection becomes a plate (run time)

### 3.1 Reading BirdNET-Pi

`featherframe/birdnet.py` opens `~/BirdNET-Pi/scripts/birds.db` with
`?mode=ro`. It never writes to or locks BirdNET's database. Every 5 s
(`service.POLL_SECONDS`) it reads new rows with `WHERE rowid > :cursor`.
Detections below 0.7 confidence are ignored (`CONFIDENCE_FLOOR`). The path is
`Config.birdnet_db_path`, which matches the Nachtzuster BirdNET-Pi layout on a
Pi 5.

### 3.2 Matching: `names.SpeciesIndex.match()`

- The lookup is **exact**: the scientific name (plus `sci_synonyms`) first,
  then the normalised common name.
- Folios are asked in order. Your **Region** setting's folios come first, then
  the rest, Havell first. `plate: none` hands the species to the next folio.
- If a scan isn't on disk, the next folio is tried. If nothing matches, the
  result is `None`.
- `None` → the **typographic fallback**: the name, set on an empty engraved
  bough (`compose.render_fallback`). It never guesses.

`PlateProvider` and `GeneratedArtProvider` sit in a `ChainedProvider`. The
first provider that returns art wins. Without an OpenAI key, the generated
provider never returns anything.

### 3.3 Which bird is shown

`service.tick()` runs two passes:

- `_tick_pictures()` decides what each picture shows: the latest qualifying
  detection (the most novel species wins a tie), or the collage, with quiet
  hours and the blocklist applied.
- `_tick_frames()` finishes that picture for each frame.

If the chosen species' sheet is already what's showing, nothing is redrawn. The
goal is as few panel refreshes as possible.

---

## 4. How a plate is drawn for e-ink

### 4.1 Cropping the scan (`render/plate.py`)

1. **Load downscaled** to 2200 px on the long side (`WORK_MAX_SIDE`), using the
   JPEG decoder's draft mode, so a 100-megapixel scan stays cheap.
2. **Trim the marginalia** (`_trim_marginalia`). Crop to `margins` (Havell's:
   `0.025, 0.068, 0.975, 0.912`), paint out `mask` boxes, then remove the
   "N° 32 / PLATE CLIX" corner lettering and a caption block that sits beside
   the art.
3. **Find the bird** (`content_box`):
   - Take the heaviest band of ink.
   - Extend it through faint, connected ink (like hanging straw) until it
     reaches a real paper gap.
   - **Mirror it about the plate's centre**, so Audubon's own composition and
     headroom survive.
   - A composite plate is kept whole. A `tight` folio (Gould) is cropped to
     the art's own box plus a white border.
4. **Normalise the paper** (`paper_normalize`): aged paper becomes clean white
   and ink keeps its tone.

### 4.2 Layout (`render/compose.py`, `typography.py`, `theme.py`)

The sheet is always 1404×1872, portrait 3:4.

- **The art** fills the box above the caption. A plate whose ink runs to its
  edges is cover-fitted if that crops 25 % or less of it. Otherwise it's
  contain-fitted and centred.
- **The caption** has three parts:
  - The common name in a copperplate script (Pinyon Script, bundled).
  - The Latin name in engraved capitals.
  - The plate's own printed legend lines, if any.
- **The corners** carry the artist on the left (from `plate_credits.json`) and
  "Plate CLIX" on the right. A generated sheet shows "✦ AI GENERATED" instead.

### 4.3 Finishing for the panel (`render/pipeline.py`, `finish.py`, `framebuffer.py`)

1. **Fit** to the panel (`_fit_to_panel`). The EE03 is also 1404×1872.
2. **Mat inset**: shrink by `mat_inset_pct` (4 % by default) so the physical
   mat doesn't cover the art.
3. **Dither** to 16 grays with a blue-noise mask: vectorised, and fast on a Pi.
   The colour EE02 panel uses Stucki diffusion over six measured inks
   (`spectra.py`).
4. **Pack** as an FFF framebuffer: a 16-byte header, then 4 bits per pixel,
   with the high nibble as the left pixel (0 = black, 15 = white). The image
   is rotated to the panel's native landscape (1872×1404) because the
   firmware's `setRotation()` does nothing.
5. **ETag** = a hash of the frame. The frame sends `If-None-Match`, and an
   unchanged picture gets a `304`, so the panel isn't repainted.

Drawn files are kept once, named by what they were drawn from, under
`data/frames/drawn/`. A species that returns reuses its sheet without
redrawing it.

---

## 5. How the collage is made (`render/collage.py`)

### 5.1 Choosing the species

`service._collage_composer()` builds the list:

1. `birdnet.top_species_today()` runs:
   ```sql
   SELECT Com_Name, Sci_Name, COUNT(*) FROM detections
   WHERE Date = ? AND Confidence >= 0.7
   GROUP BY Sci_Name ORDER BY count DESC, MAX(Time) DESC
   ```
2. Blocked species are removed.
3. **Corroboration**: a species that is new today and was heard only once is
   dropped unless that detection reached 0.85 (`CORROBORATE_CONFIDENCE`).
   This keeps one-off false positives off the wall.
4. The list is cut to `collage_species_max` (10 by default; 0 means every
   species).
5. With fewer than 2 species, the frame shows a single plate instead.

### 5.2 Drawing the grid (`render_collage`)

- **Grid shape** (`_grid`): the fewest columns where rows ≤ columns + 1, so
  each cell stays near a plate's upright shape. 6 → 2×3, 12 → 3×4, 20 → 4×5.
  The gutters narrow as the grid fills.
- **Bottom block** (`_bottom_block`): no header. Under the art goes the date
  in wide-spaced engraved capitals, then a numbered key ("1. BLUE JAY …") in
  order of prominence, packed into columns.
- **Each cell**:
  - A small figure numeral goes down first.
  - Then `provider.artwork()` gives the same cropped plate a single sheet
    would use, contain-fitted into the cell.
  - A species with no plate gets a typographic mini-cell: its Latin name in
    engraved capitals. Even in a collage, it never shows a wrong bird.
- The sheet is then finished exactly like a single plate (§4.3).

### 5.3 When the collage is drawn

- Every `collage_interval_hours` (6 by default) for a frame set to show the
  collage.
- Overnight: during quiet hours (sunset → sunrise at your BirdNET-Pi's
  latitude/longitude), once the nightly collage is drawn, every frame on
  individual birds shows it until morning.
- Optional **AI composite** (`render_generated_collage`, with an OpenAI key):
  one painted scene of the day's birds on a seasonal branch, with the same
  date and key. A sheet is only bought again when the day's species list
  changes. Without a key, you always get the grid.

---

## 6. Owning your illustration database

From the least work to the most.

### Level 1: Keep everything on your Pi (default self-host)

On the Pi 5 (Raspberry Pi OS 64-bit, BirdNET-Pi already installed):

```bash
git clone https://github.com/wr/featherframe ~/featherframe
cd ~/featherframe/server
./install.sh --all-plates      # whole Havell edition (~2.9 GB), so you never need the network for plates again
```

This creates a venv, downloads the plates, and installs a `systemd` service on
port 8181 (`Nice=10`, idle I/O, so BirdNET's analyzer keeps priority). The Pi
5 easily handles the optional `numba` install. Then:

- Open `http://<pi>.local:8181`. Set **Region** to *North America* for
  Audubon-first. **Don't add an OpenAI key** if you want everything local.
- Check the pipeline without a frame:
  ```bash
  cd ~/featherframe && make preview && make preview-collage   # → test_output/*.png
  ```
- If you're building the frame yourself, flash a non-release env, such as
  `pio run -e xiao_ee03` or the webapp's USB flasher. Then the frame finds
  your Pi over mDNS. On a release-flashed kit, type `http://<pi-ip>:8181` into
  its setup portal.

Once the plates are on disk you're cloud-independent. **Back up
`server/plates/`** (and `server/data/` for your settings and history). With a
copy of those two folders, a reinstall needs no internet for art.

### Level 2: Pin, fix or add Audubon plates

Edit `server/scripts/folios/havell.yaml`:

```yaml
- {common: "Your Bird", scientific: "Exactus binomialis", plate: 123, audubon_title: "Archaic Title"}
```

- **Find the name BirdNET uses.** The match is exact, so use the `Sci_Name`
  your BirdNET-Pi stores:
  ```bash
  sqlite3 -readonly ~/BirdNET-Pi/scripts/birds.db \
    "SELECT DISTINCT Sci_Name, Com_Name FROM detections ORDER BY Com_Name;"
  ```
- **Find the plate number.** Browse audubon.org's *Birds of America*, or leave
  `plate:` out and run `fetch_plates.py --dry-run` to get a suggestion.
  **Check it by eye** before you pin it.
- **Rebuild and restart:**
  ```bash
  cd ~/featherframe/server
  ./.venv/bin/python scripts/fetch_plates.py   # rewrites plates/index.json; offline if you used --all
  sudo systemctl restart featherframe          # the index is read when the service starts
  ```
- **Fix a bad crop** with `crop_box`, `margins` or `mask` on the entry. Check
  the result with `./.venv/bin/python -m featherframe.preview --species "Your Bird"`.

> Note: `git pull` will conflict with your edits to `havell.yaml`. Your own
> folio file (Level 3) avoids that.

### Level 3: Your own illustrations (the `my-pi` branch)

The `my-pi` branch of your fork is set up for this. Your images go through the
same crop, caption, dither and collage steps as Audubon's plates.

**What's on the branch:**

| Path | What it is |
|---|---|
| `server/local/folios/mine.yaml` | Your folio: one line per species, with every field explained at the top |
| `server/local/images/` | Your image files |
| `server/scripts/fetch_plates.py` | Also reads `server/local/folios/`, copies local images, and supports `first: true` and `auto: true` |
| `server/scripts/missing_plates.py` | Lists every species your BirdNET-Pi has heard that has no plate yet |

**Finding the species that need an image:**

```bash
cd ~/featherframe/server
./.venv/bin/python scripts/missing_plates.py          # add --all to list every species and its plate
```

It reads BirdNET-Pi's database read-only and lists each species heard at 70 %
confidence or more that has no plate in your Region, most heard first, with
the file name to give its image.

**Adding a bird:**

1. Copy the image into `server/local/images/`, named for its scientific name
   as BirdNET-Pi stores it: `Cardinalis cardinalis.jpg`. With `auto: true` in
   the folio's header (it's on in `mine.yaml`), that's all it needs.
   An image with another name needs a line under `species:` in
   `server/local/folios/mine.yaml`, which is also where a legend goes:
   ```yaml
   - {common: "Northern Cardinal", scientific: "Cardinalis cardinalis", plate: 1, file: cardinal.jpg,
      legend: ["Male, on a wild grape."]}
   ```
2. Rebuild the index and restart the service:
   ```bash
   cd ~/featherframe/server
   ./.venv/bin/python scripts/fetch_plates.py
   sudo systemctl restart featherframe
   ```
3. Check it without the frame:
   ```bash
   ./.venv/bin/python -m featherframe.preview --species "Northern Cardinal"   # → ../test_output/
   ```

**How the folio behaves:**

- **It's asked first.** `first: true` in the header puts your folio ahead of
  Audubon and Gould. A species you list shows your image. A species you don't
  list still gets its Audubon or Gould plate.
- **The paper is evened out to white.** `flatten: true` runs on the copy, so a
  cream or gray background doesn't show as a gray box on the panel.
- **A changed image is redrawn.** The copy in `plates/img/mine/` is named by
  the image's content, so after you replace `cardinal.jpg` and rerun
  `fetch_plates.py`, the frame draws the new one instead of reusing the old
  sheet.
- **Images found by name are numbered after the listed ones**, in
  alphabetical order. Adding a file can renumber the ones after it, and the
  frame then redraws them once.
- **A missing image is reported.** `fetch_plates.py` prints
  `no image at …` and the species falls through to Audubon.

**Rules for each entry:**

| Rule | Why |
|---|---|
| `scientific` must equal BirdNET's `Sci_Name` | Matching is exact. Add `sci_synonyms` for older names. |
| `plate` must be a positive number | `plate: none` means "no plate". The number prints as "Plate N" in the corner. |
| One bird per image is best | For several birds, set `composite: true` and the image is shown whole. |
| Portrait images, roughly 3:4 | They fill the sheet best. Landscape images are fitted with white space, or use `rotate`. |
| 2,000 px or more on the long side | The art is drawn up to 1404 px wide. |
| Gray or color both work | Gray panels use the luminance. The color EE02 uses the RGB. |

The left corner (artist) stays blank for your folio, because credits come from
`featherframe/plate_credits.json`.

**Good public-domain sources for more plates:**

- audubon.org's *Birds of America*.
- The Biodiversity Heritage Library (Gould, Wilson's *American Ornithology*,
  Catesby).
- The open dataset `github.com/wr/historical-bird-plates` (CC0).

Check each image's license.

### Level 4: Mirror the sources yourself

If you want to stop depending on the GitHub release and mirrors entirely:

1. On a machine with the whole edition (`fetch_plates.py --all`), run
   `make plates-pack`. It writes the release tarballs, `data.json`, a manifest
   and `SHA256SUMS` into `dist/plates/`.
2. Host that folder anywhere: a NAS, another Pi, or `python3 -m http.server`.
3. Point the fetcher at your copy:
   ```bash
   export FEATHERFRAME_PLATES_RELEASE_URL=http://nas.local:8000/plates   # instead of GitHub's plates-v1
   export FEATHERFRAME_PLATES_MIRROR_URL=http://nas.local:8000/mirror    # instead of nathanbuchar's repo
   ```
   A mirror must use nathanbuchar's layout: `data.json` at its root and
   `plates/<1-99|100-199|…|400-435>/plate-NNN-name.jpg`.

### Level 5 (optional): A crops-only plate library

The server can read pre-cut crops instead of full scans: about 1.2 GB for the
edition instead of about 2.9 GB, and nothing is cropped at runtime. Build it
from your own scans and point the server at a **local directory**, not
featherframe.app:

```bash
cd ~/featherframe/server
./.venv/bin/python -m featherframe.plate_library build ~/ff-library
# then add to the systemd unit:  Environment=FEATHERFRAME_PLATE_LIBRARY=/home/<you>/ff-library
```

On a Pi 5 with an SD card or SSD this isn't needed. It's meant for small boxes
and the cloud container.

---

## 7. Things to watch for

- **The service caches the index.** After any `fetch_plates.py` run, restart
  `featherframe.service`.
- **Never a wrong bird.** If a bird shows the typographic fallback, its name
  didn't match exactly. Compare the folio entry with the `sqlite3` query in
  Level 2.
- **A dev server on your LAN can steal the frame.** Run any test copy (on your
  Mac, say) with `FEATHERFRAME_NO_MDNS=1`, or a frame may adopt it.
- **Disk.** Plates take about 2.7–2.9 GB. `data/` stays small: history
  thumbnails are capped, and drawn files are pruned to the last 25 pictures.
- **Upgrades.** Run `git pull && ./install.sh`. Your `data/` and existing
  plates are kept; only new folio entries are fetched.

## 8. Where to read the code

| Topic | File |
|---|---|
| Downloading plates | `server/scripts/fetch_plates.py`, `featherframe/plate_release.py` |
| Species → plate | `featherframe/names.py` (`SpeciesIndex.match`) |
| Art providers | `featherframe/render/provider.py`, `render/genart.py`, `plate_library.py` |
| Cropping a scan | `featherframe/render/plate.py` (`extract`, `content_box`, `_trim_marginalia`) |
| Single sheet layout | `featherframe/render/compose.py`, `typography.py`, `theme.py` |
| Collage | `featherframe/render/collage.py`; species choice in `service.py` `_collage_composer` |
| Dither + framebuffer | `featherframe/render/pipeline.py`, `finish.py`, `framebuffer.py` |
| BirdNET-Pi ingest | `featherframe/birdnet.py` |
| The scheduler | `featherframe/service.py` (`tick`, `_tick_pictures`, `_tick_frames`) |
| Install / paths | `server/install.sh`, `featherframe/paths.py` |

---
name: pixel-art-storyboard
description: >
  Convert short scene descriptions, book/album cover briefs, or 2-paragraph synopses into
  seamless-loop animated pixel-art covers rendered as self-contained HTML+canvas. Companion
  skill to pixel-art-studio. Use when the user asks to "make a cover for", "animated book
  cover", "looped pixel scene", "convert this story description to pixel art", "create
  ambient pixel animation", "обложка для книги в пиксель-арте", "анимированная обложка",
  "封面 像素画", "픽셀 아트 표지", or provides a short narrative/synopsis and wants a visual
  result. Covers: 5-element scene framework (Subject + Setting + Lighting + Palette + Motion),
  iconographic shorthand for symbolic accents, seamless loop techniques (phase-based
  parametric, sub-pixel breathing, LCM-clean parallax, deterministic particle systems),
  loop period selection by mood, three prompt registers (LLM agent / human artist / SDXL
  LoRA), single-HTML-file deliverable in dark-atmospheric style with parametrized canvas
  rendering. Generates the same engine pattern as the user's `Grass Field with City.html`
  reference (canvas + requestAnimationFrame + phase-derived parameters). Do NOT use for
  individual game sprites, character sheets, walk/attack cycles, or PNG/GIF sprite-sheet
  export; use pixel-art-studio for that (this skill makes looped HTML+canvas scene covers,
  not raster sprite assets).
version: 1.0.0
---

# Pixel Art Storyboard

Take a short scene description (2-3 paragraphs, 1-3 elements, mood-driven) and turn it into a self-contained HTML file with one or more **canvas-rendered seamless-loop pixel art** scenes.

This is the bridge from **narrative input** to **animated visual output**. It pairs with `pixel-art-studio` (which handles palettes, dithering, quality scoring) by providing the workflow for going from "I want a cover for X" to "here is a working HTML you can open in a browser."

---

## When to use

| User says | Use this skill |
|---|---|
| "Make a cover for [book/album/game]" | Yes — single-cover workflow |
| "Animate this scene" + 1-3 paragraph description | Yes |
| "I want a looping pixel background showing X" | Yes |
| "Generate covers for these N books" | Yes — multi-cover grid layout |
| "Just draw a sprite of X" | Use `pixel-art-studio` directly (no scene narrative) |
| "Convert this image to pixel art" | Use `pixel-art-studio` preprocess.py |
| "Score the quality of my pixel art" | Use `pixel-art-studio` + `pixel-art-reviewer` agent |

---

## The 5-element scene framework

**Every scene description must specify these five elements**, either explicitly given by user or inferred from their input.

| Element | What | Example |
|---|---|---|
| **Subject** | 1-3 foreground icons that carry meaning | "Red apple in pale hands" |
| **Setting** | Background environment, depth layers (max 3) | "Deep night void, single distant star" |
| **Lighting** | Source, direction, mood | "Cool moonlight from upper-left, warm highlight on subject" |
| **Palette** | 3-6 named colors, NOT hex | "Midnight black, ivory skin, deep crimson, warm highlight" |
| **Motion** | What loops + period in seconds | "Highlight on apple orbits in 4s; petal drifts down once per loop" |

If user gives a vague brief ("a moody book cover"), **fill in the missing elements with sensible defaults** before generating, then list them in your output so they can confirm/adjust. Do NOT proceed without all 5 elements settled.

See `references/scene-description-framework.md` for full guidance and 3 worked examples (Romeo & Juliet, lonely cabin, cyberpunk alley).

---

## Workflow

### Step 1 — Parse the user's input into the 5-element framework

If user gave a paragraph synopsis: extract Subject + Setting + symbolic accents. Often the iconography is named explicitly (e.g. "the apple symbolizes forbidden fruit") — that's your Subject.

If user just gave a title: research the work (WebSearch for "X cover symbolism" or "X iconic imagery") to find the canonical visual icons. Use those as Subject.

Output a draft scene-description block:
```
SUBJECT: <1-3 icons>
SETTING: <1-3 layers of depth>
LIGHTING: <source + direction + mood>
PALETTE: <3-6 named colors + accent>
MOTION: <what loops + period>
```

### Step 2 — Pick the canvas/loop spec

| Choose | When |
|---|---|
| **64×96 (book aspect, 2:3)** | Book/album covers |
| **96×96 (square)** | Album art, Spotify-style square covers |
| **128×72 (landscape, 16:9)** | Game splash, banner |
| **64×64 (square)** | Game tile / icon set |
| **256×144 (wide)** | Twitch/YouTube banner |

Loop period (see `references/looped-animation-techniques.md` for full table):

| Loop | Feels like | Use |
|---|---|---|
| 2-3s | Alive, ambient | Idle breathe, water, candle |
| 4-6s | Subtle motion | Breathing, slow drift, ribbon flutter |
| 8-15s | Atmospheric breathing room | Petal fall, smoke plumes |
| 30-60s+ | Slow ambient | Day cycle, wave breaks |

### Step 3 — Design the canvas program

For each cover, write a `draw{Name}(ctx, W, H, t)` function where `t ∈ [0, 1)` is the loop phase. **All animation must derive from t** — no `Math.random()` (use seeded `hash(n)`), no `pos += dt` (use `sin(t * TAU)`), no off-palette ad-hoc colors.

Layer order (bottom to top):
1. **Background** (sky gradient, void, atmospheric base)
2. **Far depth** (stars, distant mountains, fog)
3. **Mid depth** (mid-ground objects, settings)
4. **Subject** (the iconographic foreground — the "apple in hands")
5. **Foreground motion** (falling petals, drifting embers, dust)

Each layer can have its own loop sub-period, but the parent loop must be the LCM (or use periods that don't drift visibly within reasonable view time).

See `templates/single-cover.html` (one cover) and `templates/grid-cover.html` (a grid) for starter canvas programs.

### Step 4 — Compose into HTML

Single self-contained HTML file. Layout: 1 cover OR a responsive grid of covers (2×2 / 4×1 with `@media` breakpoints).

Style anchors (matches user's example aesthetic):
- Background `#0b0812` (near-black with violet undertone)
- Foreground text `#a896b4` (lavender-grey)
- Accent (titles, year tags) `#ffb4c8` (pale pink)
- Border `rgba(255,255,255,.06)` (barely-visible)
- Font: `"JetBrains Mono", ui-monospace, Menlo, monospace`
- Letter-spacing: 0.2-0.35em on titles (lots of breathing room)
- Cover image-rendering: `pixelated` + `crisp-edges` (forces nearest-neighbor scale)

See `templates/single-cover.html` for skeleton, `templates/grid-cover.html` for multi-cover layout.

### Step 5 — Test in browser

Use `preview_start` to launch a static server pointing at the output folder. Take `preview_screenshot` to verify visual. Check `preview_console_logs` for errors. Iterate.

If multiple covers: verify each independently animates (each on its own `requestAnimationFrame` driver) by waiting 2-3 seconds between screenshots and confirming visual change.

---

## Loop technique cheat-sheet

The single-most-important rule: **never accumulate state**. Always derive position/color from `t = (now - start) % period`.

```javascript
// CORRECT — phase-derived, drift-free
const t = ((now - start) % period) / period;
const offset = Math.sin(t * Math.PI * 2) * amplitude;

// WRONG — accumulates float drift, may seam visibly after hours
let pos = 0;
function frame(dt) { pos += velocity * dt; ... }
```

Five techniques to combine for richer motion (see `references/looped-animation-techniques.md`):

1. **Phase-based parametric** — `sin(t * TAU)` for swaying, breathing, hover
2. **Sub-pixel breathing** — animate AA (intermediate) pixels without moving silhouette
3. **Particle phase-locked** — particle position is `f(phase, seed[i])`, not `pos += vel`
4. **Parallax LCM** — layer scroll rates 1, 2, 3, 4, 8 px/frame all complete cycles in 96-frame canvas
5. **Palette interpolation** — `mix(colorA, colorB, t)` for day/night, mood shifts

---

## Three registers for scene description

Match output register to consumer:

### LLM agent (Claude generating canvas program)
Be **explicit and parameter-heavy**. Constraints first.

```
Generate canvas pixel art for book cover.
Canvas: 64x96 logical, scale 4x via image-rendering: pixelated.
Subject: red apple in pale cupped hands, centered.
Setting: deep night void, 1 distant pulsing star upper-left.
Lighting: warm highlight on apple from upper-right (subject self-light).
Palette: 6 colors {midnight #0a0814, ivory skin #e6d4c8, skin shadow #a89486,
         deep crimson #5a0a14, apple body #b22838, warm highlight #ffe8d8}.
Motion: 4-second loop. Apple highlight orbits its surface; once per loop a
        single petal drifts diagonally from above.
Render: ctx.fillRect(x|0, y|0, 1, 1) for each pixel. Use phase t derived from
        (performance.now() % 4000) / 4000.
```

### Human pixel artist (commission brief)
Atmospheric, emotional. Trust artist for technical details.

> "A red apple cupped in pale hands, centered against pure dark. The kind of scene where the apple is the only warm thing in the world and the hands could be either offering or about to take a bite. Cool dark, single warm highlight, 4-second loop with a slow drift of something falling — petal, ember, tear."

### SDXL Pixel Art LoRA (Stable Diffusion prompt)
Noun-heavy, comma-separated, with style anchors.

```
pixel art, 16-bit style, book cover, red apple, pale female hands cupping, dark
midnight background, single bright highlight, dramatic lighting, vertical
composition, twilight saga aesthetic
Negative: blurry, photorealistic, antialiased, smooth gradients, 3d render
LoRA: Pixel Art XL by nerijs (weight 1.2)
Steps: 8, CFG: 1.5
```

See `references/three-registers.md` for the full taxonomy.

---

## Working examples (case studies)

The skill ships with one fully worked-through case study: the **Twilight Saga 4-cover example**. See:
- Scenarios: `../pixel-art-studio/examples/twilight-covers/` (HTML + scenarios markdown)
- Research source: `research/product/pixel-art-2026-05-10/twilight-scenarios.md`

The Twilight example demonstrates:
1. Mining a famous work for canonical iconography (apple / tulip / ribbon / chess pieces)
2. 5-element scene description for each book (2 paragraphs each)
3. Grid layout with 4 independent canvas covers
4. Different loop periods per cover (4s / 8s / 5s / 10s) so beats don't sync mechanically
5. Style match to user's reference HTML aesthetic

Use it as a template when generating new multi-cover sets.

---

## Quality standards (verified by pixel-art-reviewer agent)

A "ship-ready" cover from this skill must pass:

1. **Console clean** — no JS errors, no "color is undefined", no NaN coordinates
2. **All canvases render** — 4×1 / 2×2 grid layout works, no missing covers
3. **Animation runs** — visible motion within 2-3 seconds of page load
4. **Loop seamless** — no visible "snap" at the end of the period (frame N == frame 0 in some sense)
5. **Palette discipline** — each cover uses only its declared colors (verifiable via `palette.py --analyze`)
6. **Symbolic accent visible** — the icon (apple / ribbon / etc) reads at 1:1 logical scale (not just at upscaled display size)
7. **Layout matches reference aesthetic** — dark bg, lavender-grey text, pink accent, monospace, generous letter-spacing

If you generate covers and any of these fails, fix before declaring done.

---

## Mandatory rules

1. **Single self-contained HTML** — no external CSS/JS files, no CDN links (works offline)
2. **Canvas dimension parity** — `<canvas width=W height=H>` matches the logical pixel grid; CSS sizes are scaling only
3. **`image-rendering: pixelated`** — REQUIRED on every canvas (otherwise browser smooths and pixel art looks blurry)
4. **`requestAnimationFrame` per canvas** — each cover runs independently; never share a single RAF across multiple canvases (one slow draw blocks the others)
5. **No `Math.random()` in render path** — must be deterministic. Use `hash(seed)` instead
6. **No transcendent state** — everything derived from `t`. No counters that accumulate frame-to-frame
7. **Test in browser before declaring done** — preview_start + preview_screenshot + preview_console_logs

---

## Gotchas

- **`Math.random()` in render breaks loop seamlessness** — particles will drift between cycles. Use seeded `hash(seed * 12.9898) * 43758.5453 % 1`.
- **Canvas resolution vs CSS size mismatch** — if `<canvas width=64 height=96>` is styled `width: 256px; height: 384px`, browser scales by 4×. Without `image-rendering: pixelated`, the upscale is bilinear and pixel art is blurred.
- **`@media (max-width: 1280px)` collapses 4-col to 2-col** — verify at multiple viewport widths or write breakpoints to taste.
- **`requestAnimationFrame` continues running on hidden tabs throttled to 1Hz** — for screenshot tools that don't actually display, animation may pause. Render once on first frame to ensure non-empty visual.
- **`ctx.imageSmoothingEnabled = false` does NOT affect `fillRect`** — only `drawImage`. Pixel-by-pixel rendering is unaffected, but if you mix with sprite sheets, set this.
- **`x | 0` truncation introduces 1px jitter on ranges crossing 0** — for negative coordinates use `Math.floor(x)` instead. For our usual range (positive coords on canvas), `x | 0` is fine and faster.
- **Loop period not divisible by frame interval can cause perceptible step** — for 60fps display, period 1000ms = 60 frames cleanly, period 4000ms = 240 frames cleanly. Period 4500ms = 270 frames (still fine but 7.5 frames per quarter is slight). Stick to round periods.
- **Palette interpolation gotcha** — if you `mix(colorA, colorB, t)` and one channel has saturated value (255), interpolation can clip. Use HSL space for hue-shifting palettes; use RGB only for value-shift.
- **Background gradient overdraw** — drawing `H` rows of full-width rect each frame is wasteful; pre-render to an offscreen canvas once on init, then `drawImage` per frame. For our use case (single canvas at 64×96 = 6144 pixels) it's fine; for larger canvases optimize.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Canvas appears blurry | Missing `image-rendering: pixelated` | Add to canvas CSS |
| Animation snaps at loop boundary | First and last frame differ | Drive everything from `t = (now % period) / period`; use `sin(t * TAU)` |
| Particles random per page-load | `Math.random()` instead of seeded hash | Replace with `hash(seed_index)` |
| Two animations drift apart over time | Each accumulates own state | Both derive from `performance.now()` directly |
| Color suddenly NaN/undefined | Hex parser fails on shorthand | Always use `#RRGGBB`, never `#RGB` |
| Empty canvas in screenshot | Tab throttled, RAF paused | Call draw once on init outside RAF |
| 2×2 layout when expecting 4×1 | Viewport <1280px, media query collapses | Adjust breakpoint or test at wider viewport |
| Loop "stutters" at boundary | Period not divisible by frame interval | Use periods 1s/2s/4s/8s (clean for 60fps) |
| Sub-pixel breathing not visible | Logical pixel grid too small | At 16×16, breathing is 1-2 pixel jumps; use 32+ |

---

## Reference index

| Topic | File |
|---|---|
| Looped animation techniques (frame match, sub-pixel, parallax, particles, palette interp) | `references/looped-animation-techniques.md` |
| Scene description 5-element framework + worked examples | `references/scene-description-framework.md` |
| Three prompt registers (LLM / human / LoRA) | `references/three-registers.md` |
| Cover-style canvas template (single + grid) | `templates/single-cover.html`, `templates/grid-cover.html` |
| Common animation easing functions for pixel art | `references/easing-curves.md` |
| Retouch-style production standard (8-layer composition) | `references/retouch-style-guide.md` |
| Smoother animation via baking (Playwright + ffmpeg) | `references/smoother-animation-baking.md` |

## Palette selection: use Design Seeds curated palettes

Before hand-picking colors, search the Design Seeds curated catalog (10 palettes covering moods nature / twilight / dawn / mystic / vintage / autumn / dreamy / dramatic):

```bash
# By tag
python ../pixel-art-studio/scripts/palette.py --search-tag twilight
python ../pixel-art-studio/scripts/palette.py --search-tag dramatic
python ../pixel-art-studio/scripts/palette.py --search-tag mystical

# By mood (free-form)
python ../pixel-art-studio/scripts/palette.py --mood "night warm"
python ../pixel-art-studio/scripts/palette.py --mood "romantic"
python ../pixel-art-studio/scripts/palette.py --mood "peaceful retreat"
```

The Design Seeds palettes are PRE-VALIDATED for visual harmony (artist-curated, hue-shifted, mood-coherent). Using one of these as the base palette saves the "color discipline" step entirely.

For cultural / hardware-authentic specific palettes (NES, GameBoy DMG, 五行, 오방색), use the bundled palettes in `pixel-art-studio/scripts/palettes/`.

## Baking finished animations

Once your canvas animation is verified working at runtime, bake it to GIF / WebM-alpha / MP4 / PNG-sequence for archival distribution:

```bash
# Smooth GIF (30fps × 4s = 120 frames)
python ../pixel-art-studio/scripts/bake_animation.py http://localhost:9132/index-v2.html \
  --canvas-id c1 --period-ms 4000 --fps 30 --format gif -o twilight.gif

# WebM with alpha channel (transparent video for compositing into other media)
python ../pixel-art-studio/scripts/bake_animation.py http://localhost:9132/index-v2.html \
  --canvas-id c1 --period-ms 4000 --fps 30 --format webm-alpha -o twilight.webm
```

The bake samples `t` at any density you want, so output is SMOOTHER than runtime. See `references/smoother-animation-baking.md` for details.

## Quality gate: 4-reviewer board

After your animation works in browser, run the comprehensive quality board:

```
@pixel-art-quality-board "Review skills/creative/pixel-art-studio/examples/twilight-covers/index-v2.html against retouch-style"
```

Spawns 4 specialized reviewers in parallel:
- **style** (palette tier, surface detail, layer depth, hue rotation, accent, anti-AI-slop)
- **animation** (loop seamlessness, motion physics, multi-component, particle determinism, period, phase correctness)
- **composition** (silhouette test, focal point, hierarchy, negative space, scale, framing)
- **interaction** (gravity/support, occlusion order, light direction consistency, anchor, scale plausibility, animation frame consistency)

Synthesizes 4 verdicts → board PASS/NEEDS_WORK/REJECT + ranked fixes. The interaction reviewer catches things others miss (chess pieces floating above the board, contradictory light sources, etc.).

---

## Companion skills

- **`pixel-art-studio`** (sister skill): static sprite design + palette tools + dithering + quality_check.py + 20 bundled palettes. Use for non-narrative pixel art tasks.
- **`pixel-art-reviewer`** (Generator-Evaluator agent): independent quality review of generated covers. Run after `pixel-art-storyboard` produces output.

The three together form a complete pixel-art creation pipeline: storyboard → static design → animation → review.

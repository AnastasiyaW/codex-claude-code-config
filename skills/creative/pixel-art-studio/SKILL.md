---
name: pixel-art-studio
description: >
  Create production-quality pixel art and animations programmatically. Use when the user asks to "create
  pixel art", "draw a sprite", "make pixel animation", "generate sprite sheet", "convert image to pixel art",
  "pixelate this image", "make a pixel character", "пиксель арт", "пиксельная графика", "спрайт",
  "像素画", "像素艺术", "도트 그래픽", "픽셀 아트", "8-bit/16-bit/hi-bit style", "retro game art",
  "Aseprite-like output", "indie game sprite". Covers single-frame sprites, frame-by-frame animations,
  walk cycles, idle/attack/death animations, sprite sheets, GIF/APNG export, image-to-pixel-art
  preprocessing (downsample + quantize + dither), 30+ bundled palettes (NES, GameBoy, PICO-8,
  Endesga 32/64, DawnBringer 16/32, Sweetie 16, Resurrect 64, Korean 오방색/단청, Chinese 故宫/青花/五行,
  Russian Stoneshard-inspired), 5 dithering algorithms (Bayer 2/4/8, Floyd-Steinberg, Atkinson, Ordered,
  Blue Noise), automated quality scoring (orphan pixels, doublies, banding, pillow-shading, AI-slop
  detection), and Generator-Evaluator review via the pixel-art-reviewer agent. Do NOT use for
  seamless-loop animated scene/book/album covers as self-contained HTML+canvas; use
  pixel-art-storyboard for that (this skill outputs raster sprites and sprite sheets, not
  narrative loop-cover HTML).
version: 1.0.0
---

# Pixel Art Studio

Programmatic pixel art creation with palette discipline, dithering, animation, and automated quality control. Designed for **production-quality output**, not "look-pixelated filter on a photo."

## When to use this skill

| User says | What to do |
|---|---|
| "make a pixel art X" / "create a sprite" | [Static sprite workflow](#workflow-1-single-frame-sprite) |
| "animate this", "walk cycle", "idle animation" | [Animation workflow](#workflow-2-animation) |
| "convert this image to pixel art", "pixelate this" | [Preprocessing workflow](#workflow-3-image-to-pixel-art) |
| "generate sprite sheet" | [Sprite sheet workflow](#workflow-4-sprite-sheet) |
| "review this pixel art / score it" | [Quality review workflow](#workflow-5-quality-review) |
| "show palette options" / "use Endesga 64" | [Palette browsing](#palette-management) |

If user provides only a vague description ("a cat sprite"), pick the **standard sprite workflow** with **32×32 + Endesga 32 palette** as the safe default, then offer to iterate.

---

## Prerequisites

```bash
pip install Pillow numpy
# Optional but recommended for advanced quality checks:
pip install scikit-image scipy
```

`Pillow` is **mandatory**; `numpy` is mandatory; the rest are optional (the scripts will degrade gracefully).

---

## Core principle: design discipline > pixel quantity

A 16×16 sprite with deliberate cluster choices reads better than a 64×64 with random pixel noise. **Always start from the smallest grid that conveys the subject**, expand only when needed for detail.

The four pillars of quality (encoded in `scripts/quality_check.py`):

1. **Per-pixel hygiene** — no orphan single pixels, no parallel doublies, no banded ramps
2. **Cluster coherence** — pixel groups read as recognizable shapes, not noise
3. **Palette discipline** — limited (≤32 typically), with hue rotation across luminance ramp
4. **Silhouette readability** — render-as-solid-shape and verify subject is recognizable

When in doubt, run `quality_check.py` after generation and fix issues until score ≥ 80/100.

---

## Workflow 1: Single-frame sprite

### Step 1 — Pick canvas size

| Subject complexity | Canvas | Examples |
|---|---|---|
| Icon / glyph | 8×8 | heart, key, arrow, smiley |
| Simple sprite | 16×16 | NES character, item, tile |
| **Standard sprite** ⭐ | **32×32** | indie character, animal, prop |
| Detailed character | 48×48 - 64×64 | hi-bit hero, boss, building |
| Mobile RPG humanoid (CN/KR) | 48×72 | 8-direction walking character |
| Hero / portrait | 96×96 - 128×128 | promotional art, big boss |

When user is vague: **32×32**.

### Step 2 — Pick palette

Three modes:
- **Bundled palette** (recommended): Use `scripts/palette.py --list` to enumerate. Default for vague subjects: **Endesga 32**.
- **Style-anchored palette**: subject-specific recommendations in `references/02-palette-theory.md`
- **Custom palette**: 4-16 hex colors curated by hand. Validate with palette ramp checker.

Common style → palette mapping:
| User intent | Palette |
|---|---|
| Generic, modern indie | `endesga-32` or `endesga-64` |
| 8-bit retro / Famicom feel | `nes` or `pico-8` |
| Mono / GameBoy DMG | `gameboy-dmg` |
| Soft pastel / cute | `sweetie-16` |
| Atmospheric / cinematic | `apollo` or `slso8` |
| Industrial / cool | `steam-lords` |
| Chinese xianxia / palace | `gugong-red-wall` or `qinghua` |
| Korean traditional | `obangsaek` (5-color) |
| Dark fantasy (Stoneshard-style) | `stoneshard-inspired` |

### Step 3 — Design layer-by-layer

**Always think in this order, not free-form:**

1. **Silhouette** (darkest color, just outline) — does shape read at intended size?
2. **Base fill** — primary 1-2 colors covering largest areas
3. **Cell shading** — pick **3-4 discrete shades**, place them per a single light direction (default: top-left)
4. **Hue shift** — shadows shift **cooler+desaturated** (toward blue-violet); highlights **warmer+saturated** (toward yellow-orange). Hue rotation across ramp ≥ 30°
5. **Selective AA** — only on staircase patterns longer than 1×1, using intermediate-color halftone strip
6. **Details** — eyes, patterns, small features. Each pixel must belong to a cluster ≥ 2-3 pixels (no orphans)

**NEVER do pillow shading**: dark border + light center regardless of light source. Auto-detected as anti-pattern in `quality_check.py`.

### Step 4 — Generate JSON

Use the [Sparse Coordinate JSON format](references/08-json-schema.md). Minimal example:

```json
{
  "width": 16,
  "height": 16,
  "background": "transparent",
  "pixel_size": 16,
  "palette_ref": "endesga-32",
  "pixels": [
    {"x": 7, "y": 4, "color": "#a8ca58"},
    ...
  ]
}
```

For **animation**, use the multi-frame extended schema (`frames` array — see Workflow 2).

### Step 5 — Render PNG

```bash
python "${CLAUDE_SKILL_DIR}/scripts/render.py" \
  sprite.json -o sprite.png
```

### Step 6 — Quality check

```bash
python "${CLAUDE_SKILL_DIR}/scripts/quality_check.py" sprite.png
```

Output is JSON. **Score ≥ 80** = ship. Score 60-80 = fix issues listed. Score < 60 = redesign.

### Step 7 — Display + iterate

Read the PNG with the Read tool to show user. Offer fixes for any quality issues flagged.

---

## Workflow 2: Animation

### Frame counts (production-validated)

Pick from this table — do NOT improvise frame counts.

| Animation | Min | **Standard** ⭐ | Premium | FPS |
|---|---|---|---|---|
| Idle (breathing) | 2 | **4** | 6-8 | 6 |
| Walk | 4 (Celeste) | **6** (Shovel Knight) | 8-12 | 8 |
| Run | 6 | **8** | 10 | 10 |
| Attack | 3 | **5** | 6-8 | 10-12 |
| Death | 4 | **6-8** | 10+ | 8-10 |
| Hit reaction | 1 | **2-3** | — | 10 |

Cultural variations:
- **Western indie**: 8-12 fps standard
- **Chinese mobile RPG**: 4-frame walk @ 200ms (5 fps) is documented standard
- **Korean dot mobile**: 6 frames @ 8-12 fps; chibi 4-frame walk
- **Russian indie**: typically follows Western, sometimes "Punch Club rule" (draw 1×, render 2-3×)

### Animation principles (Disney → pixel art)

Only **3 of 12** translate without modification:
1. **Timing** — wind-up frames longer, action shortest, recovery eases
2. **Anticipation** — crouch before jump, wind-up before attack
3. **Squash & stretch** — even **1 pixel** of compression on landing is effective

For walk cycles: 4-frame minimum is `[contact, recoil, passing, high-point]` and back. Don't add frames just to "smooth" — add anticipation/follow-through instead.

For attacks: `[anticipation (slow), strike (1 frame, fast), recovery (eases back)]`. Slowing down anticipation + speeding up action ≫ adding frames.

### Smear frames (Korean Skul-style)

For fast attacks/throws, insert 1-2 stretched intermediate frames (smear). Heavy in Skul, less in Sanabi. See `references/04-animation.md`.

### JSON schema for animations

```json
{
  "width": 32,
  "height": 32,
  "background": "transparent",
  "palette_ref": "endesga-32",
  "frames": [
    {"id": 0, "duration_ms": 120, "pixels": [...]},
    {"id": 1, "duration_ms": 120, "pixels": [...]},
    {"id": 2, "duration_ms": 120, "pixels": [...]},
    {"id": 3, "duration_ms": 120, "pixels": [...]}
  ],
  "tags": [
    {"name": "walk", "from": 0, "to": 3, "direction": "forward"}
  ]
}
```

`direction` ∈ `forward | reverse | pingpong` (Aseprite convention).

### Render animation

```bash
# Animated GIF
python "${CLAUDE_SKILL_DIR}/scripts/animate.py" walk.json --format gif -o walk.gif

# APNG (better, supports semi-transparency)
python "${CLAUDE_SKILL_DIR}/scripts/animate.py" walk.json --format apng -o walk.apng

# Sprite sheet (for game engines)
python "${CLAUDE_SKILL_DIR}/scripts/animate.py" walk.json --format spritesheet -o walk_sheet.png --layout horizontal
```

### Animation quality check

```bash
python "${CLAUDE_SKILL_DIR}/scripts/quality_check.py" --animation walk.json
```

Checks: palette stability across frames (no off-palette colors), pixel rate consistency (sub-pixel-AA matches), total mass conservation (8-pixel torso stays 8 pixels across frames), per-frame quality scores.

---

## Workflow 3: Image-to-pixel-art preprocessing

When user provides a real photo / hi-res illustration and asks for pixel art version.

**Pipeline** (in `scripts/preprocess.py`):

1. **Downsample to target grid** via `Image.NEAREST` (NOT bicubic — that introduces fractional pixels = AI-slop signal)
2. **Extract palette** via k-means or median cut (configurable colors: 8/16/32/64)
3. **Quantize** to extracted or chosen palette
4. **Optional dithering** to soften gradients (Floyd-Steinberg/Atkinson for photos; Bayer for halftone style)
5. **Manual cleanup pass** — agent reviews output and lists orphans, doublies for edits

Usage:
```bash
python "${CLAUDE_SKILL_DIR}/scripts/preprocess.py" photo.jpg --target-size 64x64 --palette aap-64 --dither floyd-steinberg -o pixel.png
```

Important: **AI-generated art (Stable Diffusion, Midjourney) is NOT pixel art** even if it looks pixelated. It usually has fractional pixel widths and noise instead of dithering. Always run preprocess pipeline + quality check on AI output before treating it as pixel art.

---

## Workflow 4: Sprite sheet

For game engines (Unity, Godot, Unreal) wanting a single PNG with all frames.

```bash
# Layout: rows = animation type, cols = frames (canonical convention)
python "${CLAUDE_SKILL_DIR}/scripts/animate.py" character.json --format spritesheet \
  --layout grid --rows 4 --cols 8 -o character_sheet.png
```

Conventions:
- 1-2 px transparent padding between cells (configurable)
- Power-of-2 final dimensions when possible (engine-friendly)
- Optional `.json` metadata file alongside (Aseprite-compatible format)

---

## Workflow 5: Quality review

When user asks "review this pixel art" or "is this good":

```bash
python "${CLAUDE_SKILL_DIR}/scripts/quality_check.py" existing_sprite.png --verbose
```

Returns JSON with:
- **per-pixel hygiene**: orphan count, doublies count, banding bands
- **palette analysis**: unique color count, ramp hue rotation, banding score
- **silhouette readability**: solid-fill recognizability (heuristic)
- **anti-AI-slop signals**: blurry edges count, fractional widths, gradient-over-flat detection
- **overall score**: 0-100

For Generator-Evaluator review (independent agent), invoke the **pixel-art-reviewer** agent (see `agents/pixel-art-reviewer.md`). It runs quality_check.py + reads the image with fresh context and writes a verdict.

---

## Palette management

### List bundled palettes

```bash
python "${CLAUDE_SKILL_DIR}/scripts/palette.py" --list
```

Returns 30+ palettes grouped by category:
- **Hardware-authentic**: nes, gameboy-dmg, pico-8, ega
- **Lospec community**: db16, db32, aap-64, endesga-32, endesga-64, sweetie-16, resurrect-64, apollo, steam-lords, slso8
- **Cultural**: obangsaek (KR), gugong-red-wall (CN), qinghua (CN), wuxing (CN), stoneshard-inspired (RU dark fantasy)

### Extract palette from image

```bash
python "${CLAUDE_SKILL_DIR}/scripts/palette.py" --extract photo.jpg --colors 16 --method median-cut
```

Methods: `kmeans` (slow, high quality), `median-cut` (default, balanced), `octree` (fast).

### Generate hue-shifted ramp

```bash
python "${CLAUDE_SKILL_DIR}/scripts/palette.py" --ramp "#5b3a3a" --steps 5 --hue-shift 40
```

Generates a 5-step ramp from dark→bright with proper hue rotation (Endesga rule). Use this when you need a fresh material color (skin tone, metal, leather) without a full palette.

---

## Cultural style guides (when relevant)

The skill respects multiple cultural canons. Match the user's stated style:

| User mentions | Read this |
|---|---|
| 武侠 / 仙侠 / wuxia / xianxia | `references/07-cultural-styles.md#chinese-xianxia` |
| 故宫 / palace / red wall | Use `gugong-red-wall` palette |
| 道袍 / robe animation | Add sleeve secondary animation channel |
| 도트 / dot graphic / Korean | `references/07-cultural-styles.md#korean-dot` |
| 산나비 / Sanabi / Skul | "Hand-drawn dot" quality discriminator |
| MapleStory / 메이플스토리풍 | High-detail 64-128px portraits, costume-friendly |
| Punch Club / Stoneshard | Mandatory contour darker than darkest pixel |
| Loop Hero | Multi-tier sprite consistency mode |
| Celeste | 320×180 base resolution, 4-frame animations |
| Hyper Light Drifter | 480×270, "pixel impressionism", no outlines |

---

## Mandatory rules (will be quality-checked)

1. **No orphan pixels** unless intentional texture (sparkle, stippling). Default cap: 5% of total pixels.
2. **No doublies** — parallel double-thickness lines from accidental brush. Hard rule.
3. **No pillow shading** — dark-border-light-center regardless of light source. Hard rule.
4. **Palette ≤ stated cap** — if palette is `endesga-32`, output must use ≤32 unique colors.
5. **Hue rotation ≥ 30°** across any luminance ramp ≥ 4 colors. Soft warning, not hard error.
6. **Selective AA** — never on 45° lines, never on perfectly straight lines.
7. **Outline (when present) darker than darkest object pixel** (Punch Club / Stoneshard rule).

---

## Gotchas

- **Pillow `Image.quantize` defaults to median cut**. For better quality on photos use `method=Image.Quantize.LIBIMAGEQUANT` if pyImageQuant is installed; otherwise `MEDIANCUT` is fine.
- **GIF format limits**: ≤256 colors, no semi-transparency. For semi-transparent animations use **APNG** (better) or **WebP** (modern but inconsistent compatibility).
- **Sub-pixel "anti-aliasing" trick**: animate the AA values between frames to suggest motion smaller than a pixel. Looks pro but doubles the AA pixel budget.
- **CN walking timing**: Chinese mobile games sometimes use 5fps (200ms/frame) walks — looks slow to Western eye but is documented standard. Don't "fix" it.
- **45° lines never get AA** — common newbie mistake. AA on staircase patterns longer than 1×1 only.
- **Indexed PNG vs RGBA PNG**: indexed is smaller, faster, game-engine-friendly; RGBA preserves alpha. Default to RGBA in render.py; offer `--indexed` flag when palette is fixed.
- **Aseprite source files (`.aseprite`)** preserve tags, layers, palette in original form. If user has Aseprite installed, offer to export `.aseprite` alongside PNG.
- **Background-color confusion**: `"background": "transparent"` ≠ `"#FFFFFF"`. Default to `transparent` for game sprites; use solid color only for non-cutout art.
- **AI pixel art is not pixel art**: SD/Midjourney outputs need `preprocess.py` pipeline. Don't trust their pixel grid alignment.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Pillow not installed" | Missing dependency | `pip install Pillow` |
| Garbled output | Pixel coordinates outside grid | Check `0 ≤ x < width`, `0 ≤ y < height` |
| Colors look wrong | Hex shorthand or named color mismatch | Use full `#RRGGBB` hex |
| Image looks blurry | Pillow used `BILINEAR` resize | Use `Image.NEAREST` for pixel art |
| Quality score < 60 | Multiple quality issues | Read full JSON output; common fixes: reduce palette to ≤32 colors, remove orphan pixels, redo with single light source |
| GIF has color bands | Limited 256-palette quantization | Switch to APNG or use `--no-quantize` |
| Animation jitters | Inconsistent pixel positions across frames | Run `quality_check.py --animation` to identify frame with mass deviation |
| Pillow shading detected | Anti-pattern shading | Re-shade with explicit light source (top-left), darkest pixels in shadow side only |
| Doublies detected | Two parallel 1-px lines | Merge into single 2-px line OR remove the redundant line |

## Reference index

| Topic | File |
|---|---|
| Drawing techniques (cluster, AA, jaggies, doublies, outlining) | `references/01-techniques.md` |
| Palette theory, dithering, banding | `references/02-palette-theory.md` |
| Shading, light, materials | `references/03-shading-materials.md` |
| Animation principles, frame counts, smear, sub-pixel | `references/04-animation.md` |
| Quality rubric + anti-AI-slop checklist | `references/05-quality-rubric.md` |
| Tools and libraries (Aseprite, Pillow, pyxelate, etc.) | `references/06-tools-and-libraries.md` |
| Cultural styles (CN/KR/RU/Western) | `references/07-cultural-styles.md` |
| Extended JSON schema spec | `references/08-json-schema.md` |

## Companion agent

For independent quality review (Generator-Evaluator pattern): invoke **pixel-art-reviewer** agent. It runs the quality scripts + reads the rendered image with fresh context, returning PASS/HOLD/REJECT verdict — see `agents/pixel-art-reviewer.md` for invocation pattern.

# Palette Theory: Limited Palettes, Hue Shifting, Dithering, Banding

The single biggest discriminator between pro and amateur pixel art is **palette discipline**. Russian pixel art canon: "палитра составляет 50% качества" (palette is 50% of quality).

---

## 1. Why limited palettes

Hard caps historically forced quality:

| System | Cap | Year |
|---|---|---|
| Game Boy DMG | 4 shades of green | 1989 |
| NES (Famicom) | 4 colors per 8×8 tile, 25-color global | 1983 |
| EGA | 16 from 64-color master | 1984 |
| Sega Master System | 32 from 64 | 1985 |
| Mega Drive / Genesis | 64 from 512 | 1988 |
| PICO-8 (modern) | 16 fixed | 2014 |

A constrained palette **forces meaningful color decisions** instead of gradient soup. Modern Lospec community caps: 1, 2, 4, 8, 16, 32, 64, 128.

### Rule of thumb

| Sprite scale | Recommended palette cap |
|---|---|
| 8×8 - 16×16 | **4-8** colors total |
| 32×32 (standard) | **8-16** colors |
| 48×48 - 64×64 | **16-32** colors |
| 96×96+ hi-bit | **32-64** colors |

Beyond ~64 unique colors, the result usually stops looking pixel-art and starts looking pixelated-photo.

CN beginner discipline: start with **2-3 colors**, expand to 4-6 per cluster as skill grows.

---

## 2. Famous palettes (production-grade, all on Lospec)

### Hardware-authentic

| Palette | Size | Hex sample | Use |
|---|---|---|---|
| **NES** | 54 | `#7C7C7C, #0000FC, #0000BC...` | 8-bit retro authentic |
| **GameBoy DMG** | 4 | `#0F380F, #306230, #8BAC0F, #9BBC0F` | Classic mono retro |
| **GameBoy Pocket** | 4 | `#000000, #555555, #AAAAAA, #FFFFFF` | Greyscale GB |
| **PICO-8** | 16 | `#000000, #1D2B53, #7E2553, #008751...` | Fantasy console |
| **EGA** | 16 | Standard EGA | Early PC retro |
| **CGA** | 4 | Cyan/Magenta/White/Black | Older PC retro |

### Lospec community (modern)

| Palette | Size | Best for | Notes |
|---|---|---|---|
| **DawnBringer 16 (DB16)** | 16 | General | Classic balanced |
| **DawnBringer 32 (DB32)** | 32 | General | Most popular medium |
| **AAP-64** | 64 | Hi-bit general | Very wide hue coverage |
| **Endesga 32** ⭐ | 32 | **Modern indie default** | Originally for NYKRA |
| **Endesga 64** | 64 | Modern indie hi-bit | Endesga's hue-shifted ramp method |
| **Sweetie 16** | 16 | Soft pastel, cute | Pastel palette, kid-friendly |
| **Resurrect 64** | 64 | Vibrant general | Saturation-heavy |
| **Apollo** | 46 | Cinematic | Atmospheric |
| **Steam Lords** | 24 | Industrial cool | Cool blue/grey-dominant |
| **Slso8** | 8 | Tiny atmospheric | Minimalist |
| **Nyx8** | 8 | Russian Nyx | Compact narrative palette |

When in doubt: **Endesga 32**. It's the modern indie default for sprites, and it has good hue-shifted ramps built in.

### Cultural palettes (bundled with this skill)

| Palette | Size | Source | Use |
|---|---|---|---|
| **obangsaek (오방색)** | 5 | Korean five-element tradition | KS A 0062 KATS standard |
| **gugong-red-wall** | 3-12 | Chinese Forbidden City | Palace/heritage scenes |
| **qinghua** | 4-8 | Chinese blue-white porcelain | Water/porcelain themes |
| **wuxing (五行)** | 5 | Chinese five-elements | Skill effects (wood/fire/earth/metal/water) |
| **stoneshard-inspired** | ~24 | Russian dark fantasy | Muted, atmospheric, dungeon |

### Browse the catalog

```bash
python "${CLAUDE_SKILL_DIR}/scripts/palette.py" --list
python scripts/palette.py --show endesga-32  # preview as image
```

---

## 3. Color ramps and hue shifting

### What's a "ramp"?

A **ramp** = ordered sequence of colors going from dark to light (typically 3-7 steps), used to shade a single material/region.

Example skin ramp (5 steps):
```
shadow      mid-shadow  base       highlight   spec-highlight
#5b3a3a  →  #b86161  →  #f88c46  →  #ffc97a  →  #fff0c0
hue 0°       hue 0°       hue 25°      hue 50°      hue 60°
sat 100%     sat 80%      sat 75%      sat 50%      sat 25%
val 35%      val 70%      val 95%      val 100%     val 100%
```

Notice: **hue rotates from 0° (red) → 60° (yellow)** across the ramp. Saturation peaks in mid-range. Value rises monotonically.

### Endesga rule: hue shift

**Linear value-only ramps look "dull and muddy".** The fix is hue shifting:

- **Shadows** trend **cooler + desaturated** (toward blue-violet, hue +180-270°)
- **Highlights** trend **warmer + saturated** (toward yellow-orange, hue 30-60°)
- Hue rotation across a 5-step ramp ≥ **30°**, ideally 30-60°

Generation script: `scripts/palette.py --ramp "#5b3a3a" --steps 5 --hue-shift 40`

**Source**: Endesga's Lospec tutorial — *Pixel Art Quicktip: Hue Shifting*

### CN-specific: 冷暖对比 (warm/cool contrast) — **strict rule**

Chinese beginner tutorials enforce hue-shift **as a hard rule, not a tip**:
- Highlights MUST shift warm
- Shadows MUST shift cool
- No exceptions

This is stricter than the Endesga / Saint11 framing (which presents it as guidance). For the skill's quality check, score warm-highlight + cool-shadow as **mandatory** for Chinese-style sprites, **soft-warning** otherwise.

**Source**: zhuanlan.zhihu.com/p/47540319 — *笨办法学像素画：颜色选择搭配指南*

---

## 4. Dithering

### What dithering is

Dithering = **alternating pixels of two colors** in a pattern (checkerboard, halftone, error-diffusion) to simulate intermediate shades that aren't in the palette.

Used historically because hardware had limited colors (NES 25 colors, 4 per tile). Used today for **gradient softening** in limited-palette art and **retro halftone aesthetic**.

### Algorithm comparison

| Algorithm | Pattern | Best for | Pixel-art suitability |
|---|---|---|---|
| **Bayer 2×2** | Smallest threshold matrix | Subtle gradients | High |
| **Bayer 4×4** | Medium | Standard halftone | Highest — most common |
| **Bayer 8×8** | Large threshold matrix | Smooth gradients | High |
| **Floyd-Steinberg** | Error to 4 neighbors (R, DL, D, DR) | Photo→limited palette | Medium — fine but can scatter |
| **Atkinson** | Only 6/8 of error to 6 neighbors; lighter | Iconic Macintosh look | High — clean retro |
| **Ordered (clustered-dot)** | Halftone newspaper | Print-style aesthetic | High — authentic |
| **Blue noise** | Void-and-cluster, low-frequency | Modern smooth gradients | High — looks closest to error diffusion without artifacts |
| **Random** | Pure noise | Never | LOW — noise ≠ dithering |

When user says "dither this":
- Style "halftone / retro" → **Bayer 4×4**
- Style "Macintosh / Mac classic" → **Atkinson**
- Style "photo to pixel art" → **Floyd-Steinberg**
- Style "smooth / modern" → **Blue noise**

If unspecified: **Bayer 4×4** is the safest default for pixel art aesthetic.

### CN-specific: dithering as nostalgia signal

Chinese tutorials emphasize dithering as a **deliberate retro signal** for FC (Famicom/红白机) 25-color era. Western tutorials more often frame it as gradient-smoothing. Both framings are valid; pick based on user intent.

### Dithering script

```bash
python scripts/dither.py input.png --algorithm bayer4 --palette endesga-32 -o output.png
```

**Source**:
- Surma's *Ditherpunk* (canonical reference): surma.dev/things/ditherpunk/
- Wikipedia *Floyd-Steinberg dithering*
- Turbo Dither *Floyd-Steinberg vs Atkinson*
- Moments in Graphics *Free Blue Noise Textures*

---

## 5. Banding detection

### What banding is

Banding = visible **bands of color along a gradient** where palette steps are uneven. The eye gets drawn to the borders between bands rather than seeing a smooth transition.

```
Bad (banded):           Good (even ramp):
. # # . . . . . . .     . # # . . . . . . .
. # # # . . . . . .     . # # @ . . . . . .
. # # # # # # # # .     . # # @ % . . . . .
. # # # # . . . . .     . # @ % $ . . . . .
. # # . . . . . . .     . @ % $ * . . . . .
^^^^                    \                /
huge cluster of one    \  even progression  /
color, then jumps to    \                  /
next                     \________________/
```

### Detection heuristic

Along any value ramp:
1. Get the perpendicular slice of pixel widths between transitions
2. Compute the variance of band widths
3. If `max(width) > 2× min(width)` → banding warning

Histogram analysis: count pixels per unique color along the ramp; large discrepancies = banding.

In `quality_check.py`:
```python
def detect_banding(image, ramp_axis="vertical", threshold=2.0):
    bands = group_consecutive_same_color(image, ramp_axis)
    widths = [b.width for b in bands]
    return max(widths) / max(min(widths), 1) > threshold
```

### CN-specific banding awareness

CN tutorials more aggressively warn against banding: "rotate gradient direction to break banding" — appears in multiple sources. If banding detected, recommend rotating gradient angle by 15-30° to break the visible bands.

**Source**:
- Pixel Parmesan banding tutorial
- Derek Yu pixel art mistakes article

---

## 6. Indexed mode vs RGBA

### Indexed PNG

A PNG where each pixel is a **palette index** rather than full RGB. Resulting file is dramatically smaller, and the palette is intrinsic to the file.

**Use when**:
- Game engine target (Unity/Godot/Unreal) and palette is fixed
- File size matters
- Palette swaps are needed (recolor by changing palette without touching pixels)

**Don't use when**:
- Sprite has anti-aliasing with semi-transparency (complex alpha)
- You need maximum color flexibility

### Palette swap technique

Indexed mode enables this trick: same sprite, different palette = different "skin" (recolor). NES/SNES used this heavily for character variations. Modern indie still uses it for tinting (poison: green palette; fire: red palette; ice: blue palette).

In our skill: rendered indexed PNGs include the bundled palette. Engineering re-imports palette swap as palette-only modification.

**Source**: Aseprite docs on indexed mode and palette swaps; Korean Namu Wiki article on 팔레트 스왑

---

## 7. Palette extraction from image (k-means / median cut / octree)

When user provides a reference image and asks "make a palette from this":

| Algorithm | Speed | Quality | Notes |
|---|---|---|---|
| **K-means** | Slow | Highest | Iterative cluster reassignment |
| **Median cut** | Fast | Balanced | Heckbert 1979 — PIL default |
| **Octree** | Fastest | Lower | Hierarchical RGB cube merging |
| **MMCQ** (Modified Median Cut) | Fast | High | Used in Color Thief |
| **Bayesian GMM** | Slow | Highest for soft color regions | pyxelate uses this |

In `palette.py`:
```bash
python scripts/palette.py --extract photo.jpg --colors 16 --method median-cut
python scripts/palette.py --extract photo.jpg --colors 32 --method kmeans
```

**Source**:
- Wikipedia *Color quantization*
- Heckbert 1979 paper (median cut)
- Cubic.org *Octree color quantization*

---

## 8. Five-element / cultural palette anchors

### CN: 五行色 (Five Elements)

Used as semantic color mapping for skill effects in Chinese games:

| Element | Color | Hex | Use |
|---|---|---|---|
| 金 metal | white | `#FFFFFE` | shine, holy effects |
| 木 wood | green | `#4F8A57` | nature, healing |
| 水 water | black | `#1A1A1A` | shadow, void |
| 火 fire | red | `#C7372F` | combat, damage |
| 土 earth | yellow | `#D4B254` | terrain, defense |

When generating skill-effect art for a CN-themed game, use the matching element color.

### KR: 오방색 (Five Directions)

Korean traditional 5-color system — KS A 0062 KATS standard:

| Direction | Element | Color | Hex (approx) |
|---|---|---|---|
| 청 east | wood | blue | `#175A7C` |
| 적 south | fire | red | `#C53A3A` |
| 황 center | earth | yellow | `#E6CD32` |
| 백 west | metal | white | `#FFFFFE` |
| 흑 north | water | black | `#1A1A1A` |

**Source**:
- Chinese: *中国传统色：故宫里的色彩美学* book; figma.com/community/file/932547561953107053
- Korean: kats.go.kr KS A 0062; assets.clip-studio.com/ko-kr/detail?id=1908146

---

## 9. Validation rubric

When checking a palette:

1. **Count unique colors** — must be ≤ stated cap
2. **Compute ramp hue rotation** — for any ramp ≥ 4 colors, hue rotation should be ≥ 30°
3. **Detect banding** — perpendicular slice widths within 2× of each other
4. **Check warm-highlight rule** — top 25% of ramp by luminance should have warmer hue than bottom 25%
5. **Check perceptual contrast** — adjacent ramp colors should differ by ≥ 5 in CIELAB ΔE; if too close, ramp looks mushy

These all live in `scripts/palette.py --analyze`.

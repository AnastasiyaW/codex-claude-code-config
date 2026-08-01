# Element Library Scaling Architecture (10,000+ elements)

How to store, organize, search, and compose pixel-art elements at scale where a small agent can build beautiful animated scenes from text prompts. This goes beyond the v3.15 single-file approach (`elements.js`, 9 elements) to a tier-based growth path: 10 → 100 → 1,000 → 10,000+.

---

## 1. The fundamental tension at scale

| Concern | At 10 elements | At 100 | At 1,000 | At 10,000 |
|---|---|---|---|---|
| **Storage** | One file (10 KB JS) | One file (100 KB) | Bundle (~1 MB) | Bundle infeasible — split |
| **Lookup** | Linear scan OK | Linear scan OK (10 ms) | O(n) too slow (100 ms) | Need ANN search (1 ms) |
| **Loading** | Eager load all | Eager OK | Lazy by category | Lazy + warm cache |
| **Search by intent** | Visual scroll | Tag filter | Tag + palette filter | **Embedding-based semantic search** |
| **Composition** | Hand-pick element names | Filter then pick | Tag-based recipes | Agent-driven retrieval-augmented generation |
| **Versioning** | Just one version | Per-file semver | Per-file semver + supersedes | Full content-addressable storage |
| **Quality control** | Manual eyeballing | Manual review queue | Agent-reviewer (existing 4-tier system) | Sampled review + automated metrics |

**Pivotal moments**:
- **>50 elements**: split into category folders, manifest required
- **>500 elements**: lazy loading mandatory (browser performance)
- **>2,000 elements**: embedding search becomes valuable (tag-based filter alone too coarse)
- **>10,000 elements**: full retrieval-augmented architecture, server-side index optional

---

## 2. Storage tier (file system layout)

### Per-element files in category folders

Recommendation: **1 file = 1 element variant** for full versions; **1 file = 1 generator** for parametric families.

```
elements/
├── _manifest.json              ← see Section 3
├── _embeddings.bin             ← see Section 5 (binary float32 array)
├── _registry.js                ← lazy loader (see Section 4)
│
├── architecture/
│   ├── tower-stone.v1.js
│   ├── tower-stone.v1.preview.png    (auto-generated, 64×96)
│   ├── tower-stone.v2.js             ← improved variant, additive
│   ├── tower-stone.v2.preview.png
│   ├── tower-runic.v1.js
│   ├── tower-runic.v1.preview.png
│   ├── tower-ruined.v1.js
│   ├── castle-keep.v1.js
│   ├── ...
│   └── _category_index.json          ← list of files in category, fast load
│
├── nature/
│   ├── pine.v1.js                    ← parametric: drawPine(ctx, x, y, {variant: small|medium|large, depth: fg|mg|bg})
│   ├── oak-summer.v1.js
│   ├── willow.v1.js
│   ├── mountain-range.v1.js          ← parametric: variant: far|mid|near
│   ├── river-flowing.v1.js           ← animated
│   └── ...
│
├── characters/
│   ├── hooded-figure.v1.js
│   ├── knight-armored.v1.js
│   └── ...
│
├── celestial/
│   ├── moon-phases.v1.js             ← parametric: variant: full|gibbous|crescent|eclipse
│   ├── stars.v1.js
│   └── ...
│
├── weather/
│   ├── snow.v1.js
│   ├── rain.v1.js
│   ├── lightning.v1.js
│   ├── fog-band.v1.js
│   └── ...
│
└── vfx/
    ├── glow-volumetric.v1.js
    ├── ember-drift.v1.js
    ├── sparkle-magic.v1.js
    └── ...
```

### File format per element

```javascript
// elements/architecture/tower-stone.v1.js
export const meta = {
  id: "tower-stone",
  version: "1.0.0",
  category: "architecture",
  tags: ["fortress", "medieval", "vertical", "stone"],
  palettes: ["dusk-cool", "dawn-warm", "midnight"],
  anchor: "top-center",
  size_hint: { min_w: 8, max_w: 32, min_h: 40, max_h: 200 },
  options: {
    height: { type: "int", min: 40, max: 200, default: 150 },
    width: { type: "int", min: 8, max: 32, default: 14 },
    flag: { type: "bool", default: true },
    flagColor: { type: "color", default: "#a82838" },
  },
  description: "Stone tower with brick texture, crenellations, optional flag with sin-wave wave.",
  added: "2026-05-10",
  // For RAG: short caption used in embedding generation
  caption: "stone fortress tower vertical medieval brick texture crenellations flag warm window glow"
};

export default function drawTowerStone(ctx, x, y, opts = {}) {
  // ... drawing code (50-150 lines)
}
```

Each element exports a `meta` object (machine-readable) and a default function (the drawer).

---

## 3. Manifest (`_manifest.json`)

Aggregated index of all elements. Auto-generated from per-file `meta` exports via build script.

```json
{
  "schema_version": "1.0",
  "library_version": "2026.05.15",
  "total_elements": 10247,
  "total_categories": 6,
  "build_timestamp": "2026-05-15T10:00:00Z",
  "categories": {
    "architecture": { "count": 3210, "file": "architecture/_category_index.json" },
    "nature": { "count": 2840, "file": "nature/_category_index.json" },
    "characters": { "count": 1420, "file": "characters/_category_index.json" },
    "celestial": { "count": 380, "file": "celestial/_category_index.json" },
    "weather": { "count": 240, "file": "weather/_category_index.json" },
    "vfx": { "count": 2157, "file": "vfx/_category_index.json" }
  },
  "tag_index": {
    "fortress":     ["tower-stone", "castle-keep", "watchtower", "fortified-wall", ...300 more],
    "medieval":     [...],
    "snow":         [...],
    ...
  },
  "palette_index": {
    "dusk-cool":   [...all elements compatible],
    "dawn-warm":   [...],
    ...
  }
}
```

Load: ~2-5 MB JSON. Parsed once on app init, then cached. **At 10K elements, manifest stays under 10 MB** (estimated 1KB metadata per element).

---

## 4. Lazy loader pattern (`_registry.js`)

```javascript
// _registry.js
class ElementRegistry {
  constructor() {
    this.manifest = null;
    this.categoryIndexes = new Map();
    this.elementCache = new Map();    // name → { meta, drawFn, version }
    this.embeddings = null;            // Float32Array, see Section 5
  }

  async init({ baseUrl = '/elements' } = {}) {
    this.baseUrl = baseUrl;
    this.manifest = await fetch(`${baseUrl}/_manifest.json`).then(r => r.json());
    // Eagerly load embeddings (small binary file, ~10 MB at 10K × 256-dim float32)
    const buf = await fetch(`${baseUrl}/_embeddings.bin`).then(r => r.arrayBuffer());
    this.embeddings = new Float32Array(buf);
  }

  async loadCategory(cat) {
    if (this.categoryIndexes.has(cat)) return this.categoryIndexes.get(cat);
    const idx = await fetch(`${this.baseUrl}/${cat}/_category_index.json`).then(r => r.json());
    this.categoryIndexes.set(cat, idx);
    return idx;
  }

  /** Load a single element by name, parsing version like "tower-stone@1.0.0" */
  async load(spec) {
    const cached = this.elementCache.get(spec);
    if (cached) return cached;

    const [name, version] = spec.includes('@') ? spec.split('@') : [spec, null];
    const allMeta = this.manifest.tag_index;  // OR resolve via category index lookup
    // Find the element's category
    let category = null;
    for (const [cat, idx] of this.categoryIndexes) {
      if (idx[name]) { category = cat; break; }
    }
    if (!category) {
      // Lazy-load category from manifest hint
      const candidate = await this._findCategory(name);
      category = candidate;
    }
    const elementMeta = (await this.loadCategory(category))[name];
    const fileName = version
      ? `${name}.v${version.split('.')[0]}.js`
      : `${name}.v${elementMeta.latest_version.split('.')[0]}.js`;

    const module = await import(`${this.baseUrl}/${category}/${fileName}`);
    const entry = { meta: module.meta, drawFn: module.default };
    this.elementCache.set(spec, entry);
    return entry;
  }

  /** Pre-load all elements a scene needs, in parallel */
  async preloadScene(scene) {
    const uniqueSpecs = [...new Set(scene.map(s => s.el))];
    await Promise.all(uniqueSpecs.map(s => this.load(s)));
  }

  /** Render a scene using the registry */
  async renderScene(ctx, W, H, scene, t) {
    await this.preloadScene(scene);
    for (const item of scene) {
      const { drawFn } = this.elementCache.get(item.el);
      drawFn(ctx, item.x, item.y, { ...item, t });
    }
  }
}

window.PixelArtRegistry = new ElementRegistry();
```

### Caching layers

1. **Element JS modules** — browser cache via HTTP (long max-age, fingerprinted filenames `tower-stone.v1.js`)
2. **In-memory cache** — `elementCache` map persists across scenes in same session
3. **CDN cache** — at scale, host on CDN (Cloudflare R2 + Workers)

---

## 5. Semantic search (embeddings)

At 10K elements, **tag-based filter alone is too coarse**. Solution: **embedding vectors per element**.

### Computing embeddings (build-time)

Each element has:
- `meta.caption` — short text description ("stone fortress tower medieval brick crenellations")
- Auto-generated preview PNG

Embedding = concat of:
- **Text embedding** of caption via SigLIP / sentence-transformers (256-dim)
- **Image embedding** of preview via CLIP / SigLIP (256-dim)

Total: 512-dim vector per element. **At 10K × 512 × 4 bytes = 20 MB** binary file. Loadable in browser.

### Index format

```
_embeddings.bin: Float32Array, layout = element_id_index × 512
_embeddings_index.json: { "tower-stone": 0, "tower-runic": 1, ... }
```

### ANN search (in-browser)

For 10K elements, **brute-force cosine similarity** in JavaScript is fast enough (~5 ms with SIMD-friendly Float32Array operations). Above 100K, use HNSW via WASM.

```javascript
// Brute-force search (sufficient at 10K)
function searchByEmbedding(queryVec, topK = 20) {
  const N = manifest.total_elements;
  const D = 512;
  const scores = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let dot = 0;
    for (let d = 0; d < D; d++) {
      dot += queryVec[d] * embeddings[i * D + d];
    }
    scores[i] = dot;  // cosine similarity (assuming pre-normalized vectors)
  }
  return topKIndices(scores, topK).map(idx => indexToName[idx]);
}
```

### Query embedding (runtime)

User prompt: "snowy fortress on cliff with warm window light at dusk"

1. Encode prompt via same text embedder as captions (sentence-transformers MiniLM, ~80 MB WASM, ~50ms inference per query)
2. Pad to 512-dim (zero-fill image part)
3. ANN search → top-20 elements
4. Filter by category-grammar rules (Section 7) → curated final scene

---

## 6. Versioning per element (semver)

Each element has its own version trajectory:

| Change | Bump | Old still served? | Example |
|---|---|---|---|
| Bug fix (jaggies, off-by-one pixel) | patch | Yes (overwrite) | tower-stone.v1.js (fix line 87) |
| New optional parameter | minor | Yes (overwrite) | adds `flagShape` option, default = current |
| Default visual change (palette tweak) | minor | Yes (overwrite) | small color shift, scenes look ~same |
| Breaking visual change | **major** | **Yes — old kept in parallel** | tower-stone.v1.js + tower-stone.v2.js coexist |
| Element retired | deprecated | Yes (with warning) | meta.deprecated = true; meta.replaced_by = "tower-stone-classic" |

### Why this matters at 10K

When library has 10K elements, refactoring `tower-stone` would silently break thousands of scenes. Pinning per scene:

```json
{ "el": "tower-stone@1.0.0", "x": 96, "y": 90, ... }
```

Means scene reproducibility regardless of library evolution. Pinning to major version is enough: `@1` matches latest 1.x.

---

## 7. Scene grammar (composition rules)

At 10K elements, agent can't blindly pick. Grammar constrains valid composition:

```yaml
# elements/_grammar.yaml
scene:
  required_layers:
    - layer: sky
      from_category: [sky, atmosphere]
      count: 1
      z: 0

    - layer: stars  # optional for night scenes
      from_category: [celestial]
      count: 1
      condition: "palette.mood in [night, dusk, midnight]"
      z: 1

    - layer: far_depth  # optional
      from_category: [nature.mountain-range, architecture.distant-skyline]
      count: 1-2
      anchor: "y: 0.7-0.85 of canvas"
      z: 2

    - layer: mid_depth
      from_category: [nature, architecture]
      count: 0-3
      z: 3

    - layer: subject  # the focal point
      from_category: ["any"]
      count: 1
      anchor: "rule_of_thirds"
      z: 4

    - layer: foreground_motion  # optional
      from_category: [weather, vfx]
      count: 0-2
      z: 5

    - layer: atmospheric_overlay  # optional vignette/fog
      from_category: [weather.fog-band, vfx.vignette]
      count: 0-1
      z: 6
```

The agent (Section 8) uses grammar as a constraint solver: "I have a fortress (subject), now I need a sky (layer 0), maybe stars (layer 1) since palette is dusk-cool, mountains (layer 2-3), pines (layer 3), snow (layer 5)."

---

## 8. Agent workflow: text → scene

```
USER PROMPT: "snowy fortress on cliff with warm window light at dusk"

┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Intent extraction (LLM)                                 │
│   Subject: fortress (architectural, vertical)                   │
│   Setting: cliff, snowy, mountainous                            │
│   Time: dusk (palette family: dusk-cool)                        │
│   Mood: cozy (warm light contrast)                              │
│   Motion: implicit snow + window flicker                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Embedding query (in-browser ANN search)                 │
│   Encode prompt → query vector                                  │
│   Search top-20 elements per layer:                             │
│     - sky: ["sky-dusk-cool@1", "sky-stormy@1", ...]             │
│     - far_depth: ["mountain-range-snowcap@1", ...]              │
│     - subject: ["tower-stone@1", "fortress-cliff@1", ...]       │
│     - foreground: ["snow-light@1", "snow-heavy@1", ...]         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Apply grammar constraints                               │
│   - Pick 1 sky (top-ranked: sky-dusk-cool)                      │
│   - Add stars (since dusk mood) (top: stars-sparse)             │
│   - Pick 2 mountain ranges (far + near for atmospheric persp.)  │
│   - Pick 1 subject (top: tower-stone)                           │
│   - Add 4-6 pines (mix of fg/mg sizes)                          │
│   - Add fog band (atmospheric depth indicator)                  │
│   - Add snow particles (matches "snowy" prompt)                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Position via anchor rules                               │
│   - Sky/atm: full canvas                                        │
│   - Mountains: y at 70-85% canvas height                        │
│   - Subject: rule of thirds (x=33% or 66%, y=50-66%)            │
│   - Pines: front masks subject; depth determines size           │
│   - Snow: full canvas, deterministic seed                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Render scene → canvas → PNG                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Self-critique (vision LLM)                              │
│   "Show this PNG to Claude vision: does it match prompt?"       │
│   Possible issues: wrong palette, awkward anchor, missing detail│
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: Iterative refinement                                    │
│   IF critique flags issues:                                     │
│     - Replace element variant (tower-stone@1 → tower-stone@2)   │
│     - Adjust positions (move tower 5px left)                    │
│     - Add missing element ("warm light" → add window)           │
│   GOTO Step 5                                                   │
│   Max 3 iterations (cost cap)                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 8: Bake to animated WebP (existing bake_animation.py)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Storage backend options

| Approach | When | Cost | Complexity |
|---|---|---|---|
| **Static files** (current) | <500 elements | $0 (GitHub Pages) | Low |
| **Static + CDN** | <5K | $5/mo (Cloudflare R2) | Low |
| **SQLite (sql.js)** | <50K, browser-only | $0 | Medium (build pipeline) |
| **PostgreSQL + pgvector** | >100K, server-side | $20+/mo | Medium-high |
| **Pinecone / Weaviate** | When commercial RAG needed | $50+/mo | High but managed |

**Recommendation for 10K**: Static files + CDN + in-browser embeddings. **No backend needed.** Browser does the work.

---

## 10. Build pipeline

Generating manifests + embeddings + previews from per-element files:

```python
# scripts/build_library.py
import json, importlib, os
from pathlib import Path
from PIL import Image

ELEMENTS_DIR = Path("elements")

def collect_metadata():
    elements = {}
    for cat_dir in ELEMENTS_DIR.iterdir():
        if not cat_dir.is_dir() or cat_dir.name.startswith('_'): continue
        for js_file in cat_dir.glob("*.v[0-9]*.js"):
            # Parse meta export from JS (simple regex or proper JS parser)
            meta = parse_js_meta_export(js_file)
            elements[meta["id"]] = meta
    return elements

def generate_previews(elements):
    # Use playwright to render each element on a 64x96 canvas
    # Save as <name>.preview.png next to .js
    ...

def compute_embeddings(elements):
    # Load CLIP/SigLIP via transformers
    # For each element: text embedding (caption) + image embedding (preview)
    # Concat → 512-dim float32
    # Save as _embeddings.bin
    ...

def write_manifest(elements):
    manifest = {
        "schema_version": "1.0",
        "library_version": datetime.utcnow().strftime("%Y.%m.%d"),
        "total_elements": len(elements),
        "categories": group_by_category(elements),
        "tag_index": invert_tags(elements),
        "palette_index": invert_palettes(elements),
    }
    Path("elements/_manifest.json").write_text(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    elements = collect_metadata()
    generate_previews(elements)
    compute_embeddings(elements)
    write_manifest(elements)
```

Run on every release. CI/CD-friendly. Output is static files served as-is.

---

## 11. Quality control at scale

At 10K elements, manual review impossible. Solution:

1. **Automated quality check on add** — every new element goes through `quality_check.py` (orphan pixels, doublies, banding) before merge to library
2. **Sampled review** — 1% of elements reviewed manually per quarter
3. **Usage analytics** — track which elements scenes actually use; deprecate the unused 80%
4. **Style consistency check** — embedding outliers flagged for review (element that's far from category centroid in embedding space = visual inconsistency)
5. **The 4-tier reviewer system** (style/animation/composition/interaction) runs on every NEW element before publish

---

## 12. Migration path from v3.15 (9 elements) to v3.16 (10K-ready)

### Step 1: refactor v3.15
- Move each element from `elements.js` to per-file `elements/<category>/<name>.v1.js`
- Add `meta` export to each
- Build initial `_manifest.json` (manually for 9 elements)

### Step 2: add embedding infrastructure
- Set up `scripts/build_library.py`
- Compute embeddings for 9 elements (instant)
- Generate `_embeddings.bin` + `_embeddings_index.json`

### Step 3: implement registry + lazy loader
- Replace direct imports in catalog.html and library-demo with registry calls
- Verify behavior unchanged

### Step 4: scale up
- Add 10-20 new elements per category over next sessions
- Each commit auto-runs build_library.py via CI
- Library grows naturally

### Step 5 (when >500): introduce semantic search UI
- Catalog page gets search box
- Demo page accepts text prompts (basic agent flow)

---

## 13. References

- Embedding search: [SigLIP paper](https://arxiv.org/abs/2303.15343), [USE Lite WASM](https://github.com/tensorflow/tfjs-models/tree/master/universal-sentence-encoder)
- ANN search in browser: [hnswlib-wasm](https://github.com/yoshoku/hnswlib-wasm)
- Static + CDN: [Cloudflare R2 docs](https://developers.cloudflare.com/r2/)
- SQLite in browser: [sql.js](https://github.com/sql-js/sql.js)
- pgvector: [pgvector docs](https://github.com/pgvector/pgvector)
- Pinecone: [pinecone.io](https://www.pinecone.io/)
- Weaviate: [weaviate.io](https://weaviate.io/)
- DBS framework: [our principles/17-dbs-skill-creation.md](../../../../principles/17-dbs-skill-creation.md)

See also `image-collection-learning-2026.md` for how to build the initial 10K library by decomposing public pixel-art collections (Pinterest, Lospec gallery, OpenGameArt, Reddit r/PixelArt).

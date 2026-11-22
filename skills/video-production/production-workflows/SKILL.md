---
name: production-workflows
description: "Run 3D, VFX, editing, vector and grading jobs in desktop apps an agent drives (Blender, Premiere Pro, After Effects, Illustrator, Photoshop, DaVinci Resolve, TouchDesigner) without wrecking the project. Use when: 'destruction shot in Blender', 'разрушение в блендере', 'exploded view', 'взрыв-схема сборки', 'build a scene', 'toon shader', 'мультяшный шейдер', 'sort footage', 'разложи исходники по бинам', 'sync audio', 'composite this shot', 'remove the object from the shot', 'убери из кадра', 'vectorize', 'векторизуй', 'fix this generated image', 'color grade in Resolve', 'цветокор', 'TouchDesigner effect'. Covers the shared job contract (brief first, live-connection preflight, non-destructive edits, everything stays editable, preview and full-length review, flag what is uncertain) and per-app recipes from vendor docs. Do NOT use for FFmpeg-only finishing, captions and platform export (video-post-production), code-rendered video (remotion-production-guide) or formula-driven animation (procedural-animation)."
---

# Production workflows in desktop apps

Eleven jobs, one contract. The contract is what keeps an agent from flattening a client's project; the recipes say which
app feature does the work. Recipes cite vendor docs (`references/sources.md`); a step marked **unverified** was not found
in the docs and must be checked in the app before you rely on it.

## The contract (every job)

1. **Brief before edits.** Ask for what is missing, in one message: source assets and project file, the target look or a
   reference, duration / output format, and the job's own questions (table below). Do not start on guesses.
2. **Preflight.** Confirm the app is reachable through the tool you have (Blender MCP, an Adobe connector, Resolve
   scripting, TouchDesigner Python) and its version. Unreachable → say so and stop; do not simulate the result.
3. **Never touch the original.** Work on a copy or a new version: save-as `<name>_v002`, a new Resolve version, a
   duplicated sequence, new layers. Originals and existing edits stay as they were.
4. **Keep it editable.** Masks instead of erased pixels, adjustment layers and nodes instead of baked pixels, modifiers left
   live, simulations baked to keys only on a copy. The person must be able to change your work.
5. **Preview, then review the whole length.** A still for looks; for motion, the full shot at speed. Cleanup and composites
   also get `scripts/flicker_check.py` (below).
6. **Flag, do not guess.** Clips that would not sync, pieces that would not fracture cleanly, areas the fill could not
   rebuild: list them for a person instead of forcing them.
7. **Report:** what changed, where the new version is saved, what is flagged, what you could not verify.

## The jobs

| Job | App | Ask for | Recipe |
|---|---|---|---|
| Destruction shot | Blender | what breaks, what triggers it, shot length | `references/blender.md` §1 |
| Exploded view | Blender | the assembly, order of parts, camera | `references/blender.md` §2 |
| Scene layout | Blender | setting, main action, style reference | `references/blender.md` §3 |
| Toon / cartoon look | Blender | style reference, which objects | `references/blender.md` §4 |
| Sort and sync footage | Premiere Pro | shoot days, sound recorder files, naming | `references/adobe.md` §1 |
| Composite a shot | After Effects | plates, layers, target look | `references/adobe.md` §2 |
| Remove an element | After Effects | what to remove, frame range | `references/adobe.md` §3 |
| Vectorize artwork | Illustrator | which details must stay exact | `references/adobe.md` §4 |
| Fix a generated image | Photoshop | what to remove/repair, lighting | `references/adobe.md` §5 |
| Colour grade | DaVinci Resolve | references, hero shot, delivery | `references/resolve-touchdesigner.md` §1 |
| Visual effect | TouchDesigner | style reference, output format, length | `references/resolve-touchdesigner.md` §2 |

## Checking motion: scripts/flicker_check.py

`python "${CLAUDE_SKILL_DIR}/scripts/flicker_check.py" <video> [--region x,y,w,h] [--k 6]` reads per-frame luma with FFmpeg `signalstats` and
flags frames whose brightness jump is far above the shot's own typical jump (a patch popping, a fill flickering).
Exit 0 none flagged, 1 frames flagged (listed with time), 2 not checked (no FFmpeg, unreadable file). Point `--region` at
the cleaned area. It finds sudden jumps, not slow drift or wrong texture: still watch the shot. `--self-test` builds a
steady clip and one with a flash and must flag only the second.

## Gotchas

- Cell Fracture is an Extension since Blender 4.2, not a bundled add-on: install it from Get Extensions first.
- A keyframed passive rigid body needs **Animated** ticked, or the simulation treats it as still.
- Premiere's Merge Clips cannot be re-synced after merging: make a new merged clip instead.
- Illustrator's Expand ends the trace: keep an unexpanded copy until the person approves.
- After Effects Match Grain only adds noise; on a plate noisier than the insert, Remove Grain first.
- TouchDesigner H.264/H.265 export needs a Commercial or Pro licence; on the free licence export another codec.
- Resolve: a qualifier keyed after later nodes shifts when those nodes change; key skin from a balanced node.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Fracture pieces leave gaps | Cell Fracture settings too coarse or non-manifold mesh | fewer, larger cells first; fix the mesh; keep the original hidden |
| Debris explodes at frame 1 | pieces overlap at rest | add a small margin / scale pieces down slightly, re-bake |
| Patch visible for a few frames | fill reference frame drifts | new reference frame at that range; re-run; `flicker_check.py` on the region |
| Sync failed on some clips | no shared audio or timecode | leave unsynced, list them; never align by guess |
| Trace has thousands of anchors | Paths/Noise too high for the image | lower Paths, raise Noise, simplify before Expand |
| Grade differs shot to shot | matched by eye on uncalibrated view | Shot Match to the hero, then fine-tune on scopes |

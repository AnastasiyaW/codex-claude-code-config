# Adobe recipes (Premiere Pro, After Effects, Illustrator, Photoshop)

Doc pages: `sources.md`. Work through the Adobe connector or the app's scripting (ExtendScript/UXP) the session has; if
neither is reachable, stop at the preflight (contract step 2).

## 1. Premiere Pro: sort and sync footage

1. Duplicate the project file first (`<name>_sorted.prproj`).
2. Bins: `Day_01/Video`, `Day_01/Audio`, `Day_01/Stills`… by shoot day and media type. Shoot date is not a built-in column:
   take it from file metadata (or name) and add a custom Text column via Metadata Display if you need it visible.
3. Labels for status (Edit › Preferences › Labels): e.g. one colour for "flagged".
4. Sync camera to recorder audio: **Merge Clips** (one video + up to 16 audio) or **Synchronize** in a sequence. The options
   in the docs read are Clip Start, Clip End, Timecode, Clip Marker plus an audio-channel reference; use timecode or slate
   markers when present. A merged clip cannot be re-synced: make a new one.
5. Clips with no reliable timecode/marker/shared audio: do not align by eye; label them flagged and list them.
6. One sequence per scene or day, named `Day01_Scene03_sync`.

## 2. After Effects: composite a shot

1. New comp at the plate's size, rate and length; plates and layers precomposed by role (BG, FG, FX).
2. Keying on green screen (Keylight or the key the project uses); **Roto Brush** (Effect menu now "Object Matte & Refine
   Edge") for edges and hair.
3. Moving camera: **3D Camera Tracker** (Animation › Track Camera); delete points on moving objects before solving.
4. Match: colour and exposure with adjustment layers, depth of field and motion blur from the plate, then grain last with
   **Match Grain** sampled from the plate (Remove Grain first if the insert is already noisier).
5. Generate missing layers only when the brief needs them, and say which ones are generated.

## 3. After Effects: remove an element

1. Mask the element per frame range: **Mask Tracking** for rigid shapes (correct drift at the frame it appears and re-track
   from there), Roto Brush for organic ones.
2. **Content-Aware Fill** panel: method **Object** (moving camera/objects), **Surface** (flat static surfaces),
   **Edge Blend** (static on plain surfaces, fast). Hard cases: **Create Reference Frame** → paint a clean plate in
   Photoshop → Generate Fill Layer.
3. The fill is a new layer; the plate is never painted on.
4. Review the full shot at speed and run `scripts/flicker_check.py --region` on the cleaned area.

## 4. Illustrator: vectorize

1. Ask which details must stay exact (logo letters, faces, outlines); keep the raster on a locked layer below.
2. **Image Trace**: Mode (Color / Grayscale / Black and White); Palette (Color only: Automatic, Limited, Full Tone);
   Paths (higher = tighter), Corners, Noise (Adobe: 20–50 for high-res, 1–10 for low-res).
3. Trace a duplicate; **Expand** only after the look is approved (after Expand the trace options are gone).
4. After Expand: group by colour/part, name layers (Background, Shapes, Linework, Text), delete stray tiny paths, simplify
   paths that have far more anchors than the shape needs. (Simplify command **unverified** in docs read.)
5. Rebuild text as live type when the font is known rather than tracing letters.

## 5. Photoshop: fix a generated image

1. Work in a PSD; the original as a locked bottom layer.
2. Remove objects: selection → **Content-Aware Fill** workspace (sampling Auto/Rectangular/Custom, output to a new layer),
   or **Generative Fill** (new layer, optional prompt), or the Remove tool.
3. Repair textures on new layers; blend with **layer masks** (white shows, black hides).
4. Lighting and colour with **adjustment layers**, masked to the area.
5. Save PSD with all layers; flatten only an export copy.

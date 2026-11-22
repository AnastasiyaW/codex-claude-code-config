# DaVinci Resolve and TouchDesigner recipes

Doc pages: `sources.md`. The Resolve sources read are colorist guides for versions 15–18; check names in your build.

## 1. Resolve: colour grade

1. Keep the existing grade: a new **Local Version** per clip (or Remote Version when every use of the source clip must
   follow). Grab a Gallery still of the original for comparison.
2. Node tree, one job per node, serial: (1) balance — Lift/Gamma/Gain/Offset for exposure and white balance on scopes;
   (2) contrast and saturation; (3) skin — qualifier on skin, keyed from the balanced node; (4) look; (5) shot match.
   Parallel nodes for independent adjustments, a layer node when one must sit on top.
3. Skin: Vectorscope with the skin-tone indicator on; keep skin near that line.
4. Across a sequence: pick a hero shot, **Shot Match to This Clip** on a separate node, then fine-tune by scopes.
5. Review the whole timeline before render; deliver from a copy of the render preset the brief names.
6. Scripting: the official README is inside Resolve (Help › Documentation › Developer › Scripting); entry
   `DaVinciResolveScript.scriptapp("Resolve")`. Whether external scripting needs Studio differs between sources: read your
   build's README and the Preferences setting before planning automation.

## 2. TouchDesigner: visual effect

1. Network: **Movie File In TOP** (source) → effect TOPs (**Level** for contrast/gamma, Blur, **Feedback** for trails,
   **Composite** to combine with an Operation) → **Movie File Out TOP**.
2. Expose the controls the person will tweak as custom parameters on a container; set them in Python with
   `op('name').par.<param> = value`, read with `.eval()` (`.par` is an object, not a value).
3. Level TOP rebuilds its lookup on the CPU: animate it sparingly.
4. Export: Movie File Out codec by licence — H.264/H.265/AV1 need Commercial or Pro (and NVIDIA on Windows); otherwise
   Hap Q, NotchLC, ProRes or Animation. Audio needs a Time Sliced CHOP.
5. Preview with the source media before export; save the `.toe` next to the export.

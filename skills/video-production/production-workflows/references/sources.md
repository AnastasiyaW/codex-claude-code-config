# Sources and provenance (2026-11-22)

## Where the idea came from

The job list and the shared contract (ask for assets first, check the live connection, preserve existing work, keep results
editable, preview before finishing, flag what is uncertain) follow the public descriptions of a vendor's "Production skills
bundle" (https://higgsfield.ai/mcp/bundles/production-skills and its 11 preset pages, read 2026-11-22). Those pages describe
outcomes, not app features. No file of that vendor's skills was used: a repack scraped from its server and passed around with
an installer was deliberately not downloaded (no licence, unknown provenance). The recipes here are written from the vendor
documentation below.

## Vendor documentation

Status: **read** = official page read; **summary** = official page found, content from its search summary;
**unverified** = not found.

| Topic | Page | Status |
|---|---|---|
| Cell Fracture extension | https://extensions.blender.org/add-ons/cell-fracture/ ; https://docs.blender.org/manual/en/4.1/addons/object/cell_fracture.html | summary |
| Rigid body tips, Bake To Keyframes, Animated passive | https://docs.blender.org/manual/en/latest/physics/rigid_body/tips.html | read |
| Rigid body constraints, Breakable, Threshold, Connect | https://docs.blender.org/manual/en/latest/physics/rigid_body/constraints/introduction.html | read/summary |
| Rigid Body World | https://docs.blender.org/manual/en/latest/physics/rigid_body/world.html | summary |
| Quick effects (smoke) | https://docs.blender.org/manual/en/5.0/physics/fluid/introduction.html | summary |
| Delta transforms | https://docs.blender.org/manual/en/latest/scene_layout/object/properties/transforms.html | summary |
| Dope Sheet editing (no stagger operator found) | https://docs.blender.org/manual/en/latest/editors/dope_sheet/editing.html | summary |
| Track To / Damped Track | https://docs.blender.org/manual/en/dev/animation/constraints/tracking/track_to.html | read |
| Shader to RGB | https://docs.blender.org/manual/en/latest/render/shader_nodes/color/shader_to_rgb.html | read |
| Line Art modifier | https://docs.blender.org/manual/en/latest/grease_pencil/modifiers/generate/line_art.html | read |
| Freestyle | https://docs.blender.org/manual/en/latest/render/freestyle/view_layer/freestyle.html | summary |
| Solidify | https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/solidify.html | read |
| Color Ramp Constant interpolation | — | unverified |
| Premiere bins | https://helpx.adobe.com/premiere/desktop/organize-media/file-organization/bins-overview.html | summary |
| Premiere synchronize | https://helpx.adobe.com/premiere/desktop/add-audio-effects/basic-audio-editing/synchronize-audio-and-video.html | summary |
| Premiere merge clips and limits | https://helpx.adobe.com/premiere/desktop/add-audio-effects/basic-audio-editing/merge-clips-in-the-project-panel.html ; .../limitations-of-merged-clips.html | summary |
| Premiere labels, metadata columns | https://helpx.adobe.com/premiere/desktop/get-started/preferences-and-settings/labels-preferences.html ; https://helpx.adobe.com/premiere/desktop/get-started/customize-the-project-panel/list-view-columns.html | summary |
| AE Content-Aware Fill | https://helpx.adobe.com/after-effects/using/content-aware-fill.html | summary |
| AE Roto Brush | https://helpx.adobe.com/after-effects/desktop/roto-brush-and-refine-matte/roto-brush/roto-brush-refine-matte.html | summary |
| AE mask tracking | https://helpx.adobe.com/after-effects/using/rigid-mask-tracking.html | summary |
| AE 3D Camera Tracker | https://helpx.adobe.com/after-effects/desktop/work-with-3d-composition/3d-camera-tracker-effect/tracking-3d-camera-movement.html | summary |
| AE grain effects | https://helpx.adobe.com/after-effects/desktop/apply-effects-and-animation-presets/list-of-effects/noise-grain-effects.html | summary |
| Illustrator Image Trace options, presets | https://helpx.adobe.com/illustrator/desktop/manage-objects/traces-mockups-symbols/image-trace-panel-options.html ; https://helpx.adobe.com/illustrator/using/image-trace-presets.html | summary |
| Illustrator Simplify | — | unverified |
| Photoshop Content-Aware Fill, Generative Fill, masks, adjustment layers | https://helpx.adobe.com/photoshop/desktop/repair-retouch/remove-objects-fill-space/remove-objects-with-content-aware-fill.html ; https://helpx.adobe.com/photoshop/desktop/create-open-import-images/create-images/edit-images-with-generative-fill.html ; https://helpx.adobe.com/photoshop/using/editing-layer-masks.html ; https://helpx.adobe.com/photoshop/using/adjustment-fill-layers.html | summary |
| Resolve nodes, primaries, qualifier, vectorscope, Shot Match, versions | https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-18-Colorist-Guide.pdf | summary (v18 guide) |
| TouchDesigner Level, Feedback, Composite, Movie File Out TOPs | https://docs.derivative.ca/Level_TOP ; https://docs.derivative.ca/Feedback_TOP ; https://docs.derivative.ca/Composite_TOP ; https://docs.derivative.ca/Movie_File_Out_TOP | summary |
| TouchDesigner Python (op, Par) | https://docs.derivative.ca/Working_with_OPs_in_Python ; https://docs.derivative.ca/Par_Class | summary |
| FFmpeg signalstats (flicker_check.py) | https://ffmpeg.org/ffmpeg-filters.html#signalstats | used and run |

## Not verified in an app

None of the app recipes was run in the app when this skill was written: no Blender, Premiere, After Effects, Illustrator,
Resolve or TouchDesigner session was available. `flicker_check.py` was run (self-test). Treat a recipe step as a plan to
check against the open app, and update this file when a step is confirmed or corrected.

Refresh: re-read the Blender pages on each LTS, the Adobe pages on each major release, and the Resolve manual of the
installed version.

# Blender recipes

Doc pages: `sources.md`. **Unverified** = not found in the vendor docs; check in the app first.
Drive Blender through its MCP (`execute_blender_code`) or `blender -b file.blend --python script.py`; save to a new file
(`bpy.ops.wm.save_as_mainfile(filepath=..._v002.blend, copy=True)`) before any destructive step.

## 1. Destruction shot

1. Duplicate the object to break; hide the original (keep it for re-runs).
2. **Cell Fracture** (Extension since 4.2: Get Extensions → "Cell Fracture"; menu Object › Quick Effects › Cell Fracture).
   Start with few cells: high counts are slow and can leave gaps.
3. Pieces: Object › Rigid Body › **Add Active**. Ground and static set: **Add Passive** (a keyframed passive needs
   **Animated** ticked).
4. Bonds so it breaks on impact, not at frame 1: select neighbours, Object › Rigid Body › **Connect**, constraint type Fixed,
   **Breakable** on, **Threshold** = impulse needed to break (default 10; raise until it holds still before the trigger).
5. Trigger: an active projectile or an animated passive body; set the Rigid Body World frame range to the shot.
6. Dust: Object › Quick Effects › **Quick Smoke** on debris emitters, or a particle system. (No dedicated "dust" tool.)
7. Preview by playing the cache; when approved, Object › Rigid Body › **Bake To Keyframes** on a copy (it replaces the
   simulation with keys).
8. Pieces jumping at frame 1 usually means they overlap at rest: shrink pieces slightly or lower collision margin.
   (**unverified**: not in the docs read.)

## 2. Exploded view

1. One object per part, origins at each part's assembled position; apply transforms to deltas
   (Object › Apply › *to Deltas*) so animation is relative to the assembled pose.
2. Key each part at assembled (frame A) and exploded (frame B) positions along its assembly axis.
3. Stagger: shift each part's keys in the Dope Sheet by a few frames (G); there is no stagger operator in the docs read.
4. Camera: **Track To** an empty at the assembly centre (camera looks down its −Z; use **Damped Track** if the camera
   passes over the target, Track To rolls there).
5. Keep geometry, materials and lights untouched: only object transforms change.

## 3. Scene layout

1. Ask for setting, action, style references; list the assets you will use and where they come from (the person's files or a
   licensed library). No assets → blockout primitives named for what they stand for.
2. Collections per role (Set, Characters, Props, Lights, Cameras); everything linked or appended, not joined.
3. Pose rigged characters in Pose Mode on their armature; never apply the armature modifier.
4. Two or three camera options as separate cameras with markers; render a still from each for the person to pick.

## 4. Toon / cartoon look

1. EEVEE: Diffuse BSDF → **Shader to RGB** → Color Ramp with Constant interpolation (bands) → Emission/output.
   Shader to RGB is EEVEE-only and drops SSR/SSS of upstream BSDFs. (Color Ramp "Constant" **unverified** in docs read.)
2. Outlines, one of:
   - **Line Art** Grease Pencil modifier (Contour, Crease, Intersections, Material Borders…); per-object crease overrides win;
   - **Solidify** modifier with **Flip Normals** and a back-face-culled black material (apply or clear scale first: non-uniform
     scale makes the outline uneven);
   - **Freestyle** at render (view-layer line sets).
3. Keep object colours: put the ramp's colours in a node group with exposed inputs, one material per original colour.
4. Verify with a render, not the viewport: Shader to RGB only works in the Combined pass.

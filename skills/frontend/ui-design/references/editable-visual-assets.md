# Editable visual assets in product UI

Use for an image-led hero, banner, product infographic, or visual-reference
reconstruction inside an interface. This is an adaptation of selected Editable
Design ideas, not an installation of its poster/editor/PPTX runtime.

## Decide what remains editable

Start from the requested user action and the existing product components.
Keep headings, prices, dates, labels, captions, controls, and live metrics as
native text/data/components. A generated composition may guide visual hierarchy
but must not become the shipped interface screenshot. Do not turn a photograph's
incidental lettering or a supplied logo into a blanket ban on raster images.

Choose assets by what must change independently:

- A continuous scene can remain one illustration when shared lighting and
  perspective make it coherent; overlay real text and real controls.
- A comparison or product grid uses independently replaceable images with
  consistent crop/style; the component owns geometry, labels, and data.
- A foreground subject that must move independently needs a separate cutout
  with verified alpha edges. Keep its stacking order explicit.
- A chart or procedural diagram uses the project's data/chart/vector primitives
  when values, labels, accessibility, or interactions must remain editable.
  A generated illustration cannot stand in for measured results.

Split only at useful editing boundaries, not into a maximal number of layers.
Reuse supplied approved product imagery for exact branded goods; generation
must not invent packaging, credentials, numerical claims, or product variants.

## Build and inspect

1. Inspect the supplied reference when present. Record only decisions needed
   for this change: hierarchy, composition, typography roles, asset boundaries,
   and the factual copy. Use the existing task/design notes rather than creating
   a new manifest for a single asset. Do not generate a reference image by
   default when existing assets and components satisfy the request.
2. Generate or obtain only the selected imagery through the available approved
   tool. Use shared visual anchors for a series where continuity matters.
   Keep text-bearing regions calm and inspect unwanted lettering, cropping,
   alpha edges, light direction, and scale. Preserve successful assets when
   retrying a failed one. Image-tool availability is not a dependency of a
   typography-only UI task.
3. Assemble in the existing component hierarchy with product tokens and
   platform layout. Responsive web UI uses its normal flow/grid/breakpoints,
   not a poster's fixed absolute coordinates. Native UI retains native layout.
   Do not add an editor, replay viewer, dependencies, or a parallel design system
   merely to implement a visual block.
4. Inspect the actual render at the affected supported sizes. Read the required
   copy; check clipping, overlaps, contrast over imagery, asset seams, and
   meaningful differences from the requested reference. Exercise the real
   action and keyboard path where changed. Fix concrete defects and recheck;
   do not iterate on taste after the requested result is sufficient.
5. Prove the intended editing boundary with one local change: change the
   headline or replace an asset in the existing source, then verify that the
   other elements remain intact and the text reflows correctly. For a requested
   visual editor, additionally exercise edit -> export -> reopen and check the
   saved text, positions, and assets. A DOM-layer count alone proves neither.

Deliver the existing source/components and required assets, with the requested
preview. Store them in the project structure; keep temporary renders and
private generation traces out of published assets. Do not claim that a PNG is
editable source or that source inspection proves runtime usability.

## Optional PowerPoint boundary

Only a request for PowerPoint export activates conversion work. Editable Design's
separate converter maps some DOM elements to editable text/shapes, some to
independent raster images, and unsupported portions to a background. "Selectable"
does not mean vector-editable or semantically editable. Inspect the resulting
objects and a rendered export; report any rasterized portions. This reference
does not install or promise that converter. Discover and review an available
conversion capability at that point; do not delay the requested UI for it.
Do not execute an unreviewed converter's setup/run/install entry point: these
may install dependencies or modify an environment. The agent owns that review
and safe preparation within the requested export task, using existing runtime
and dependency policy. Missing tooling is not automatically an external blocker
or a demand for the user to install it; record an actual unresolved boundary
only if review/preparation cannot safely satisfy the requested export.

## Provenance and update contract

Reviewed 2026-09-08 against upstream commit
`a7ff67e57e5d3a9033e531c4f0d1c6b51038dbcb` (Apache-2.0).
Owner: maintainers of this repository's `ui-design` skill. Version: the Git
revision and generated skills lock. This text is a local synthesis; no upstream
runtime, fonts, gallery, or dependency bundle is vendored.

Primary sources, accessed 2026-09-08:

- [Editable Design workflow](https://github.com/yejy53/Editable-Design/blob/a7ff67e57e5d3a9033e531c4f0d1c6b51038dbcb/skills/editable-design/SKILL.md)
  — native text, independent imagery, composition versus shipped pixels,
  concrete render review. Upstream explicitly excludes websites.
- [Asset architecture](https://github.com/yejy53/Editable-Design/blob/a7ff67e57e5d3a9033e531c4f0d1c6b51038dbcb/skills/editable-design/references/asset-architecture.md)
  — coherent grids, cutouts, layer ordering, and seam inspection.
- [HTML to PPTX contract](https://github.com/yejy53/Editable-Design/blob/a7ff67e57e5d3a9033e531c4f0d1c6b51038dbcb/skills/html-to-pptx/SKILL.md)
  — object conversion and rasterization limits, optional export.

Accepted: editable semantic content, deliberate asset boundaries, visual plus
edit/reopen proof when applicable. These extend the shared UI loop; they do not
replace its accessibility, platform, or user-flow checks.

Not adopted: mandatory image-reference generation, absolute fixed-pixel
single-file UI, a universal SVG ban, forced model choice, ten-generation batches,
mandatory editor/layer/replay outputs, automatic installers, and fixed English
handoff labels. These are poster-specific, host-specific, or unnecessary for
the UI outcome. No model-quality comparison or Windows runtime compatibility
claim was established by this source review.

Refresh when upstream changes the relevant contract or a local regression
appears. Diff these pinned sources and reassess the accepted subset; never
automatically replace the local entry point with upstream. Recheck an existing
CSS-only edit, an editable illustrated hero, native UI, and an explicitly
requested export. Roll back the local change through Git and redeploy the same
tracked files, not by installing a second skill under a new name.

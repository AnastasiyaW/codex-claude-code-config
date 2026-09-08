---
name: ui-design
description: Unify product UI design, frontend implementation, and verification. Use when asked to design, redesign, build, or fix a web, desktop, or mobile interface; a page, dashboard, form, component, design system, responsive layout, accessibility, interface animation, or editable hero/banner/infographic within a product surface. Combine visual decisions with implementation. Do not use for backend-only work, generic architecture, standalone artwork or slide decks, or browser-test-only requests.
---

# UI Design

Use one product-surface loop. Preserve existing brand tokens and component
conventions as the authority; do not replace them with a generic style guide.

This is the shared entry point for interface design. Supporting skills below
are implementation details, not alternative design workflows. Read the shared
contract once; a link back from a supporting skill is not a recursive reload.

## Editable visual blocks

For an illustrated hero, promotional banner, product infographic, or a supplied
visual to rebuild as editable UI, read
[Editable visual assets](references/editable-visual-assets.md). Keep text,
controls, data, and layout native to the product; generate only the imagery
that the requested composition needs. A screenshot is a preview, not editable
source or interaction proof. Ordinary forms and small CSS fixes skip this mode.
Standalone posters and PowerPoint conversion are separate deliverables, not
mandatory stages of UI work.

## Select the smallest supporting skill set

1. Read `../ui-ux-pro-max/SKILL.md` for a new surface, substantial redesign, or
   a visual/UX decision that needs evidence. Use its local search scripts with
   a short, specific query. Treat a zero-result search as zero evidence; do
   not invent a recommendation. Do not persist a generated design-system file
   unless the task explicitly asks for it.
2. Read `../frontend-design/SKILL.md` while changing an HTML, browser, or UXP
   frontend. Keep the implementation native to the detected stack and existing
   component system. Do not apply its browser CSS/ARIA recipes to a native
   Qt/QML surface.
3. Read `../motion-framer/SKILL.md` only when the changed surface is React/JS
   and the project already uses `motion`/`framer-motion`, or the user has
   explicitly authorized adding it. Otherwise use the platform's native
   primitives; never add the package merely to animate a control.
4. For a running surface, use the inspection tool that matches the surface:
   browser screenshot, interaction, accessibility-tree, and visual-diff tools
   are for browser/UXP/HTML. For native Qt/QML, use available native desktop
   and accessibility inspection instead. Never require a browser tool to prove
   a native application.
5. For native Qt/QML, keep existing Qt Quick Controls and theme components as
   the authority. When custom controls or focus behavior change, consult the
   Qt Quick [input-focus](https://doc.qt.io/qt-6/qtquick-input-focus.html) and
   [accessibility](https://doc.qt.io/qt-6/accessible-qtquick.html) guidance;
   verify native accessible semantics and keyboard behavior rather than
   substituting ARIA or CSS rules.

Do not load all four by default. A focused CSS fix normally needs only the
implementation guidance and a focused proof.

## Work in one loop

1. Inspect the target surface, real stack, existing tokens/components, changed
   user flow, supported widths, and any current visual evidence.
2. State a compact design contract before editing: primary user action,
   information hierarchy, reuse/new tokens, keyboard/contrast behavior, and
   platform-appropriate sizing and motion behavior. Browser breakpoints and
   `prefers-reduced-motion` are conditional, not universal desktop
   requirements. For a tiny local fix, keep this contract proportional to that
   fix.
3. Implement the visual and interaction changes together. Prefer semantic
   structure, stable component boundaries, and design tokens over one-off
   pixel overrides. Do not add animation that obscures feedback, delays an
   action, or ignores reduced-motion preferences.
4. Verify the changed flow at the narrowest real boundary: project checks
   first, then live behavior appropriate to the target when runnable and the
   risk warrants it. Use browser/UXP screenshot and accessibility-tree evidence
   for web surfaces; use native Qt/QML keyboard and accessibility inspection for
   desktop surfaces. Check the affected platform sizing, keyboard path, visible
   focus, contrast, overflow, and motion behavior rather than declaring a page
   "polished" from source code alone. A source read or screenshot without an
   identified running build is never runtime PASS.

## Decision boundaries

- Keep an established design system unless the task is explicitly a redesign.
- Keep UI Pro Max as retrieval evidence, not as an authority over the product's
  brand, accessibility contract, or existing UX research.
- Treat motion as progressive enhancement. The same action and information
  must remain clear with reduced motion and without animation support.
- Do not broaden a UI request into unrelated product copy, backend, analytics,
  or global restyling without evidence that the requested flow requires it.

## Interaction-specific proof

Apply only the slice that the changed surface contains; this is not a demand to
add a modal, custom validation, or extra animation to an otherwise simple UI.
Browser-specific ARIA, CSS, and WCAG-pixel checks do not prove a native QML
implementation; source inspection alone does not prove any runtime behavior.

- **Native Qt/QML custom control:** verify actual `Tab`/focus-scope traversal,
  visible focus, documented keyboard activation, and Qt Quick accessible
  role/name/state with a native accessibility inspector where available. Keep
  a runtime receipt tied to the build identity.
- **Native Qt/QML modal/dialog:** verify initial focus, keyboard operation,
  modal containment when applicable, and focus return to the invoking control
  after close.
- **Native Qt/QML form/error:** verify keyboard reachability and that
  error/status text is exposed through the native accessibility path; do not
  infer it from a property declaration.
- **End-to-end retouch workflow:** verify the real user path (for example,
  import, adjust, apply/save) in the running native app before calling the
  surface usable; code or a static screenshot is only source/visual evidence.

- **Modal dialog:** verify that opening moves focus into the dialog, `Tab` and
  `Shift+Tab` stay in its sequence, `Escape` closes it when the product supports
  dismissal, and closing restores focus to the invoking control (or a documented
  logical successor). Do not claim `aria-modal` unless the background is actually
  inert. [WAI-ARIA APG modal-dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
- **HTML/UXP form error:** verify a detected invalid field is identified and
  its error is described in text. An inline message, summary, alert, or native
  validation can be appropriate only when the real browser/assistive-technology
  behavior supports the chosen path; color alone is not an error description.
  [WCAG 2.2 SC 3.3.1](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html)
- **HTML/UXP dense pointer controls:** for adjacent compact controls, assess the WCAG
  2.5.8 boundary: a 24 by 24 CSS-pixel target or its spacing/equivalent/inline
  exception. Do not blindly enlarge an inline link or an essential dense control.
  [WCAG 2.2 SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- **Web motion:** when motion changes, exercise the reduced-motion branch rather
  than assuming that a static source review proves it. `prefers-reduced-motion`
  communicates the user's request to reduce, remove, or replace non-essential
  motion. [MDN reference](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
- **Native motion:** verify the product's documented OS/app motion accommodation
  if it exists. Do not invent a CSS media-query requirement for QML.

## Local UI Pro Max validation boundary

The vendored `ui-ux-pro-max` folder is a distributed skill, not its complete
upstream repository. Its local acceptance checks are the data validation and a
real, scoped retrieval query, for example:

```powershell
python skills/frontend/ui-ux-pro-max/scripts/validate_data.py
python skills/frontend/ui-ux-pro-max/scripts/search.py "keyboard focus modal" --domain ux
```

Do not run or report `test_catalog_refresh.py` or `test_relevance_evaluator.py`
as local PASS criteria: each imports an upstream-root script absent from the
distributed skill. Preserve that boundary as `NOT_RUN_UPSTREAM_DEPENDENCY`, not
as a failure repaired with stubs or as a passing test.

## Gotchas

- A fixed-canvas poster can look excellent while being unsuitable for a
  responsive interface. Do not import its absolute-pixel, single-file layout
  policy into a product.
- A selectable raster layer is not editable text, a working control, or a
  data-bound chart. Name the actual editability boundary.

## Troubleshooting

- The agent found only `frontend-design`: follow its shared-entry link here
  once, then load only the reference needed for the changed surface.
- A copy change requires regenerating the hero: extract the copy into native
  text and keep the illustration separate; verify wrapping and contrast.
- The render is correct but an action cannot be used: inspect the running
  control, focus, and hit area. More screenshot polishing does not fix it.

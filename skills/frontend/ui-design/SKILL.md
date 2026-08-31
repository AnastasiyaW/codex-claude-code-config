---
name: ui-design
description: Unify product UI design, frontend implementation, and verification. Use when asked to design, redesign, build, or fix a web, desktop, or mobile interface; a page, dashboard, form, component, design system, responsive layout, accessibility, or interface animation. Combine visual decisions with the implementation rather than treating design as a separate later task. Do not use for backend-only work, generic system architecture, non-product artwork, or browser-test-only requests.
---

# UI Design

Use one product-surface loop. Preserve existing brand tokens and component
conventions as the authority; do not replace them with a generic style guide.

## Select the smallest supporting skill set

1. Read `../ui-ux-pro-max/SKILL.md` for a new surface, substantial redesign, or
   a visual/UX decision that needs evidence. Use its local search scripts with
   a short, specific query. Treat a zero-result search as zero evidence; do
   not invent a recommendation. Do not persist a generated design-system file
   unless the task explicitly asks for it.
2. Read `../frontend-design/SKILL.md` while changing the actual frontend. Keep
   the implementation native to the detected stack and existing component
   system.
3. Read `../motion-framer/SKILL.md` only when the changed surface is React/JS
   and the project already uses `motion`/`framer-motion`, or the user has
   explicitly authorized adding it. Otherwise use native CSS/stack primitives;
   never add the package merely to animate a control.
4. Read `../../development/control-ui/SKILL.md` when a running browser/desktop surface needs
   screenshot, interaction, accessibility-tree, or visual-diff evidence.

Do not load all four by default. A focused CSS fix normally needs only the
implementation guidance and a focused proof.

## Work in one loop

1. Inspect the target surface, real stack, existing tokens/components, changed
   user flow, supported widths, and any current visual evidence.
2. State a compact design contract before editing: primary user action,
   information hierarchy, reuse/new tokens, responsive behavior, and relevant
   keyboard, contrast, and reduced-motion requirements. For a tiny local fix,
   keep this contract proportional to that fix.
3. Implement the visual and interaction changes together. Prefer semantic
   structure, stable component boundaries, and design tokens over one-off
   pixel overrides. Do not add animation that obscures feedback, delays an
   action, or ignores reduced-motion preferences.
4. Verify the changed flow at the narrowest real boundary: project checks
   first, then a live UI interaction/screenshot when the surface is runnable
   and the visual or interaction risk warrants it. Check the affected
   breakpoint(s), keyboard path, visible focus, contrast, overflow, and motion
   behavior rather than declaring a page "polished" from source code alone.

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

- **Modal dialog:** verify that opening moves focus into the dialog, `Tab` and
  `Shift+Tab` stay in its sequence, `Escape` closes it when the product supports
  dismissal, and closing restores focus to the invoking control (or a documented
  logical successor). Do not claim `aria-modal` unless the background is actually
  inert. [WAI-ARIA APG modal-dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
- **Form error:** verify a detected invalid field is identified and its error is
  described in text. An inline message, summary, alert, or native validation can
  be appropriate only when the real browser/assistive-technology behavior supports
  the chosen path; color alone is not an error description. [WCAG 2.2 SC 3.3.1](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html)
- **Dense pointer controls:** for adjacent compact controls, assess the WCAG
  2.5.8 boundary: a 24 by 24 CSS-pixel target or its spacing/equivalent/inline
  exception. Do not blindly enlarge an inline link or an essential dense control.
  [WCAG 2.2 SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- **Motion:** when motion changes, exercise the reduced-motion branch rather
  than assuming that a static source review proves it. `prefers-reduced-motion`
  communicates the user's request to reduce, remove, or replace non-essential
  motion. [MDN reference](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)

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

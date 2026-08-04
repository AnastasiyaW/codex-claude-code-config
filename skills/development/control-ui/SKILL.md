---
name: control-ui
description: Drive and inspect a local web, IDE, or Electron UI with browser or CDP automation and evidence. Use for UI regressions, screenshots, accessibility snapshots, visual diffs, focus, keyboard, scrolling, resize, console, network, performance, or heap checks. Do not use for backend-only changes or for a screenshot without a behavior claim.
---

# Control UI

Verify UI behavior at the real browser or Electron boundary. Reuse the
project's Playwright, Cypress, browser, or Electron harness before creating a
probe. Keep the data local and disposable.

## Workflow

1. Read the project's documented start command and identify the local URL or
   debug port.
2. Discover existing browser tests and stable app markers.
3. Select the target page by a positive root marker, role, label, or stable
   `data-*` attribute, not tab order or coordinates.
4. Capture the initial DOM/accessibility snapshot, screenshot, console state,
   or network baseline relevant to the claim.
5. Perform one structural action: click, type, keypress, drag, scroll, navigate,
   or resize.
6. Capture the new state and assert the expected change.
7. Clean up the dev server, debug session, temporary profile, and artifacts.

Use `verify-this` for before/after claims. Use raw CDP only when higher-level
APIs cannot provide the required CPU, heap, trace, network, or rendering signal.
Do not install Playwright just for a one-off probe when an existing browser tool
or dependency is available.

## Evidence and privacy

Screenshots, traces, network bodies, and heap snapshots may contain private code
or user data. Keep them outside public Git unless they are explicitly sanitized
and approved. A public report should contain the command, revision, safe metric,
and artifact hash or private location, not the payload.

## Gotchas

- A screenshot without an assertion proves that rendering occurred, not that the
  workflow is correct.
- Coordinates and stale locators are fragile after navigation or layout change;
  select from the latest structure.
- A successful page load does not prove console, network, accessibility, or
  keyboard behavior.
- A visual diff can be caused by viewport, font, locale, or reduced-motion
  differences; record those inputs before interpreting it.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Wrong tab or window | Selector relied on tab order | Enumerate pages and choose a positive app marker |
| Click changes nothing | Stale locator or wrong state | Capture a fresh snapshot and wait for the state marker |
| Screenshot differs only on one machine | Fonts, viewport, scale, or locale drift | Pin the test inputs and classify as `INCONCLUSIVE` until comparable |
| Browser remains after the run | Cleanup path missed an exception | Use a bounded cleanup step and verify the process/profile is gone |

## Source

Adapted from Cursor Team Kit's MIT-licensed `control-ui` workflow:
https://github.com/cursor/plugins/tree/main/cursor-team-kit/skills/control-ui

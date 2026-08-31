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
4. Read `../control-ui/SKILL.md` when a running browser/desktop surface needs
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

[TODO: Choose the structure that best fits this skill's purpose. Common patterns:

**1. Workflow-Based** (best for sequential processes)
- Works well when there are clear step-by-step procedures
- Example: DOCX skill with "Workflow Decision Tree" -> "Reading" -> "Creating" -> "Editing"
- Structure: ## Overview -> ## Workflow Decision Tree -> ## Step 1 -> ## Step 2...

**2. Task-Based** (best for tool collections)
- Works well when the skill offers different operations/capabilities
- Example: PDF skill with "Quick Start" -> "Merge PDFs" -> "Split PDFs" -> "Extract Text"
- Structure: ## Overview -> ## Quick Start -> ## Task Category 1 -> ## Task Category 2...

**3. Reference/Guidelines** (best for standards or specifications)
- Works well for brand guidelines, coding standards, or requirements
- Example: Brand styling with "Brand Guidelines" -> "Colors" -> "Typography" -> "Features"
- Structure: ## Overview -> ## Guidelines -> ## Specifications -> ## Usage...

**4. Capabilities-Based** (best for integrated systems)
- Works well when the skill provides multiple interrelated features
- Example: Product Management with "Core Capabilities" -> numbered capability list
- Structure: ## Overview -> ## Core Capabilities -> ### 1. Feature -> ### 2. Feature...

Patterns can be mixed and matched as needed. Most skills combine patterns (e.g., start with task-based, add workflow for complex operations).

Delete this entire "Structuring This Skill" section when done - it's just guidance.]

## [TODO: Replace with the first main section based on chosen structure]

[TODO: Add content here. See examples in existing skills:
- Code samples for technical skills
- Decision trees for complex workflows
- Concrete examples with realistic user requests
- References to scripts/templates/references as needed]

## Resources (optional)

Create only the resource directories this skill actually needs. Delete this section if no resources are required.

### scripts/
Executable code (Python/Bash/etc.) that can be run directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, data processing, or specific operations.

**Note:** Scripts may be executed without loading into context, but can still be read by Codex for patching or environment adjustments.

### references/
Documentation and reference material intended to be loaded into context to inform Codex's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**

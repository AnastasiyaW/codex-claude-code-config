---
name: product-meaning-extractor
description: "Deep product analysis before creating videos, presentations, or ads. Use when: 'analyze product', 'extract value', 'product brief', 'what makes this product special', 'prepare brief', 'understand the product', 'video brief'. Takes a URL or product description and outputs a structured brief with core insight, enemy, transformation, proof, mechanism, and emotional hooks. Based on JTBD, StoryBrand, Obviously Awesome (April Dunford), and Value Proposition Canvas frameworks. Do NOT use for writing the script or scene timing (use video-narrative-arc), scoring an existing script (use script-evaluator), or rendering video (use remotion-production-guide); this is the upstream brief-only step before any script is written."
---

# Product Meaning Extractor

Extract the REAL value from a product before writing a single line of video/presentation code. Without this step, content is a flat list of features. With it, content tells a story.

## Why This Exists

A feature list alone may not explain why the product matters to this audience. Product analysis connects capabilities to a relevant, supportable customer outcome; it does not guarantee engagement.

This skill forces you to find what actually matters: the enemy, the transformation, the mechanism, and the emotional hook. Everything else flows from these.

## Process

### Step 1: Gather Raw Material

**From the product URL:**
1. Visit the site, extract ALL text (hero, features, pricing, about, FAQ)
2. Screenshot key visuals (hero, before/after, product shots)
3. Extract brand colors from CSS (`--primary`, `--accent`, meta `theme-color`)
4. Note the tone: formal/casual, technical/simple, premium/accessible

**From reviews/testimonials (if available):**
1. Find testimonials on the site itself
2. Check App Store / Product Hunt / G2 / Trustpilot / Reddit mentions
3. Extract relevant VERBATIM customer phrases with their source, author/context, and date. Do not turn a paraphrase or invented phrase into a customer quotation.

**Evidence travels with the brief:** For each factual number, capability, comparison,
customer name, or testimonial, retain the source URL/file and relevant scope/date.
Separate verified observations, attributed vendor claims, and hypotheses. Examples
below illustrate a structure, not facts about the current product. If evidence is
missing, use `[needs data]`, omit the claim, or write a clearly labelled hypothesis;
continue the useful brief without inventing proof to fill a field.

### Step 2: The "So What?" Test

For EVERY feature on the site, ask "So what?" until you reach the real value. Most features need 3-4 "so what?" iterations:

```
Feature: "Outputs .PSD with layers"
So what? → "You can edit individual elements"
So what? → "You don't redo the whole job if one thing is wrong"
So what? → "It saves hours of re-work and frustration"
REAL VALUE: "Never redo work from scratch again"
```

```
Feature: "AI-powered analysis"
So what? → "It finds patterns humans miss"
So what? → "Decisions are based on data, not gut feeling"
So what? → "You stop guessing and start knowing"
REAL VALUE: "Confidence in every decision"
```

Do this for every feature. Most products have 3-4 real values buried under 10+ feature bullets.

### Step 3: Fill the Product Brief

Output this structured brief (fill EVERY field, mark unknowns as `[needs data]`):

```markdown
# Product Brief: [Product Name]

## Core Insight
[One sentence: WHY does this product exist? Not what it does - why the world needs it.
Test: remove the product name. If the sentence still makes sense, it's good.
BAD: "ProductX uses AI to optimize workflows" (about the product)
GOOD: "Creative teams shouldn't choose between speed and quality" (about the world)]

## Enemy
[What is specifically bad without this product? Be concrete and visceral.
BAD: "Manual work is time-consuming"
GOOD: "Retouchers spend 45 minutes per photo removing scratches pixel by pixel.
       A 200-product catalog = 150 hours of mind-numbing work. Client wants changes? Start over."
The enemy should make the reader think: "yes, that's exactly my problem."]

## Transformation
**Before:** [A specific "day in the life" WITHOUT the product. What does the person DO, FEEL, WASTE?
            Write it as a mini-scene, not a bullet point.]
**After:**  [Same person WITH the product. What changed? Be specific about outcomes AND feelings.]

## Unique Mechanism
[HOW does it solve the problem? The specific approach that makes it different.
BAD: "Uses AI to improve results"
GOOD: "Pixel-level neural retouching that preserves original resolution and DPI,
       outputting editable .PSD with layers - not a flattened, compressed JPG"
The mechanism answers: "Why should I believe this works?"]

## Proof Points
1. [Measured result, if available: source + metric + sample/context + date; retain limitations]
2. [Social proof, if available: source + actual person/company + attributed experience]
3. [Comparison, if available: source + versions/conditions + supported specific advantage]
4. [If no hard data available: mark as [needs data] and suggest what to measure]

## Emotional Hooks (rank top 3)
Pick the strongest emotional transitions for this specific product:
- [ ] Frustration → Relief ("Stop spending hours on...")
- [ ] Fear → Safety ("Never lose quality when...")
- [ ] Chaos → Control ("Finally, one tool that...")
- [ ] Shame → Pride ("Deliver work that...")
- [ ] Scarcity → Abundance ("Unlimited [X] without...")
- [ ] Complexity → Simplicity ("Just upload and...")
- [ ] Slow → Fast ("[X] in seconds, not hours")
- [ ] Expensive → Affordable ("Premium results at...")
- [ ] Isolation → Belonging ("Join [X] teams who...")
- [ ] Ignorance → Insight ("Finally see what...")

## Customer Language Bank
### Pain phrases (how they describe the problem):
- "[verbatim from reviews/testimonials]"
- "[verbatim]" 
- [If no reviews found: optional hypotheses labelled [inferred, not a customer quote]; do not attribute them to a person or use them as testimonials]

### Desire phrases (how they describe the dream state):
- "[verbatim]"

### Objection phrases (what they worried about before buying):
- "[verbatim or inferred]"

## Target Audience (max 3, ranked)
1. [Primary: WHO + their specific context + why they care MOST]
2. [Secondary: ...]
3. [Tertiary: ...]

## Competitive Positioning (April Dunford framework)
- **Competitive alternatives:** [What would they use if product didn't exist?]
- **Unique attributes:** [What can ONLY this product do?]
- **Value:** [What does the unique attribute enable?]
- **Target customer:** [Who cares most about that value?]
- **Market category:** [What frame makes the value obvious?]

## Brand Signals
- **Colors:** [Primary, accent, bg - with hex codes]
- **Tone:** [formal/casual, technical/simple, premium/accessible]
- **Visual style:** [dark/light, minimal/rich, photo-heavy/text-heavy]

## Video Angle Recommendations
### Angle 1: [Name] (best for [15s/30s/60s])
**Hook:** "[Specific opening line using customer pain phrase]"
**Structure:** [Narrative arc: PAS / BAB / Apple Keynote / Before-After]
**Key scene:** [The single most powerful visual moment]
**CTA:** "[Specific call to action]"

### Angle 2: [Name]
...
```

### Step 4: Brief Validation Checklist

Run these checks before using the brief:
- [ ] Core insight doesn't mention the product name (it's about the WORLD, not the product)
- [ ] Enemy is specific enough to make someone say "that's me"
- [ ] Transformation includes FEELINGS, not just features
- [ ] Mechanism explains HOW, not just "AI-powered"
- [ ] Every factual proof point is source-bound; absent numbers remain absent or `[needs data]`
- [ ] Actual quotes retain provenance; inferred language is separate and never represented as testimony
- [ ] No more than 3 target audience segments (focus!)
- [ ] At least 2 video angles suggested with different hooks

## Anti-Patterns

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| Feature listing | "We have X, Y, Z" - nobody cares about features | Use "So What?" test to find real values |
| Jargon | "Leveraging proprietary algorithms" | Use customer words, test: would a friend say this? |
| Vague enemy | "Current solutions are inadequate" | Explain the observed problem; add numbers only when supported |
| Missing mechanism | "Better results" | HOW better? What's the secret sauce? |
| No tension | No enemy = flat content | The enemy must be REAL and FELT |
| Generic emotions | "Save time" | Time for WHAT? "Get home before kid's bedtime" |
| Company-first | "We are the leader in..." | Customer-first: "You deserve..." |

## Frameworks Reference

**JTBD (Jobs-to-be-Done):**
- Functional job: What task are they trying to accomplish?
- Emotional job: How do they want to feel?
- Social job: How do they want to be perceived?

**StoryBrand (Donald Miller):**
1. Hero (customer) has a Problem
2. Meets a Guide (your product) with Empathy + Authority
3. Who gives them a Plan
4. Calls them to Action
5. Helps them avoid Failure
6. And achieve Success

**Obviously Awesome (April Dunford):**
Competitive alternatives → Unique attributes → Value → Target customer → Market category

**Value Proposition Canvas (Strategyzer):**
Customer: Jobs + Pains + Gains ←→ Product: Products + Pain Relievers + Gain Creators

## Gotchas

- Don't skip the "So What?" test - it's where insights hide behind features
- Customer language > clever copywriting. Always.
- If you can't find the enemy, the product might not have a clear positioning - flag this
- Brief should take 10-15 minutes of real analysis. 2-minute briefs are too shallow
- Update the brief as you learn more during content creation
- The brief carries evidence into subsequent work (video, ads, slides); it does not outrank the underlying source or turn a hypothesis into a fact.

## Troubleshooting

- No numeric result or testimonial: continue with supported capabilities and explicit unknowns; do not manufacture a metric or speaker to pass the checklist.
- A later source contradicts the brief: correct the affected claim and downstream copy, retaining the source and scope of the correction.

## Source basis

- [Strategyzer: test value-proposition assumptions](https://www.strategyzer.com/library/roadmap-to-test-your-value-proposition) — customer jobs, pains, gains, and benefits are hypotheses to test, not facts supplied by the framework.
- [FTC: advertisement endorsements](https://www.ftc.gov/news-events/topics/truth-advertising/advertisement-endorsements) — testimony is not a substitute for supporting a claim. This supports claim provenance; it is not a universal legal-compliance verdict.

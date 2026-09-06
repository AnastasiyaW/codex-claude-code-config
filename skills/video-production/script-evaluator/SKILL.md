---
name: script-evaluator
description: "Evaluate video scripts and presentations for flatness, tension, and emotional impact. Use when: 'is this script good', 'review script', 'evaluate video', 'why is this boring', 'flatness check', 'script review', 'improve script', 'rate this video'. Scores 6 dimensions (tension, specificity, emotional arc, hook, customer voice, visual variety), identifies specific problems, and suggests concrete fixes with examples. Do NOT use to generate a new script or scene structure from scratch (use video-narrative-arc), to build the product brief (use product-meaning-extractor), or to render/finish the video (use remotion-production-guide or video-post-production); this only critiques an existing script/scene."
---

# Script Evaluator / Flatness Detector

Review a video script, presentation, or rendered scene code and identify exactly WHY it's boring and HOW to fix it. Works on scripts, storyboards, and Remotion/code-based video scenes.

## Preserve facts before scoring style

Check claims against the supplied brief and its sources. Keep factual numbers,
comparisons, product capabilities, and customer quotations tied to their evidence
and limitations. The examples below are illustrative, not reusable product facts.
Never invent a statistic, customer, testimonial, or guarantee to raise a score.
Without evidence, use a supported qualitative example or flag the exact claim as
unverified while continuing the rest of the review. A creative score is a heuristic,
not a measured engagement prediction, factual approval, or authority to publish.

## Evaluation: 6 Dimensions (score each 1-10)

### 1. TENSION - Does the viewer feel something?

| Score | Description |
|-------|-------------|
| 1-3 | No enemy/problem. Features listed without context. "We do X, Y, Z" tone |
| 4-6 | Problem mentioned but vague ("saves time"). Some contrast but generic |
| 7-10 | Specific visceral enemy. Clear before→after. Viewer thinks "that's me!" |

**Fix:** Name the specific, observed pain. Use attributed customer language or clearly identified paraphrases. Show the "before" state without exaggerating it; add a number only when its source supports the claim.

### 2. SPECIFICITY - Is it concrete or vague?

| Red Flag | Fix |
|----------|-----|
| "Saves time" | HOW MUCH? "Saves 45 minutes per photo" |
| "Better quality" | WHAT metric? "Original DPI, pixel-to-pixel" |
| "Innovative solution" | WHAT innovation? "Neural retouching with layer output" |
| "AI-powered" | What does the AI DO? "Detects and removes 12 types of artifacts" |
| "Trusted by thousands" | WHO? "Used by 500+ jewelry studios including [name]" |

**Rule:** Prefer a supported concrete example over a vague adjective. Numbers are optional; retain scope and uncertainty rather than forcing numerical specificity.

### 3. EMOTIONAL ARC - Does it go somewhere?

| Score | Description |
|-------|-------------|
| 1-3 | Same energy start to finish. Feels like a slideshow of facts |
| 4-6 | Some variation but no clear peak/valley |
| 7-10 | Identifiable beats. At least one DOWN (tension) and one UP (relief). Last scene feels different from first |

**Fix:** Map scenes to an emotional curve. Must have at least one DOWN (problem) and one UP (amazement/relief). The CTA should feel like resolution, not another slide.

### 4. HOOK STRENGTH - Will they keep watching?

| Score | Description |
|-------|-------------|
| 1-3 | Starts with logo, "We are [company]...", or decorative intro with no information |
| 4-6 | Has information but doesn't create urgency or curiosity |
| 7-10 | First frame has surprising information. Creates curiosity gap. Uses customer language. MUST see next scene |

**Fix:** The hook is your ad for your ad. Read the first 3 seconds aloud. If it sounds like a corporate intro, try a relevant question, supported fact, attributed customer quote, or clear visual contrast. A stronger hook must not strengthen a claim beyond its evidence.

### 5. CUSTOMER VOICE - Does it sound human?

| Score | Description |
|-------|-------------|
| 1-3 | "Leveraging cutting-edge technology." "Seamless integration." "World-class results." |
| 4-6 | Reasonable language but still "written by marketing" feeling |
| 7-10 | Actual customer phrases. Sounds like describing to a friend. Simple, direct, concrete |

**Fix:** Use relevant available customer reviews with source, attribution, date/context, and faithful wording. No fixed quote quota. If no reviews are available, use plain explanatory copy; never fabricate or present inferred language as a testimonial.

### 6. VISUAL VARIETY - Is it visually dynamic?

| Score | Description |
|-------|-------------|
| 1-3 | Same layout every scene. All text, no imagery. Same animation everywhere |
| 4-6 | Some variation but key moment doesn't stand out visually |
| 7-10 | 2+ visual styles. Pacing matches emotion. Most important scene looks DIFFERENT |

**Fix:** Alternate scene types. After text-heavy scenes, do a visual scene. The most important scene should have a unique visual treatment.

## Scoring

```
TENSION:        _/10
SPECIFICITY:    _/10
EMOTIONAL ARC:  _/10
HOOK:           _/10
CUSTOMER VOICE: _/10
VISUAL VARIETY: _/10
────────────────────
TOTAL:          _/60

VERDICT:
  50-60: Strong on this creative rubric; check factual and task acceptance separately
  40-49: Good, minor tweaks needed  
  30-39: Needs work on weakest dimensions
  20-29: Major rewrite - go back to Product Brief
  <20:   Start over with Product Meaning Extractor
```

## 5 Common Flatness Patterns

### 1. "Feature Parade"
**Symptom:** Scene 1: Feature A. Scene 2: Feature B. Scene 3: Feature C. CTA.
**Why flat:** No narrative tension. It's a list, not a story.
**Fix:** Add a problem scene BEFORE features. Features answer a question - ask the question first.

### 2. "Logo-First"
**Symptom:** Opens with 3-5 seconds of logo animation.
**Why flat:** Nobody cares about your logo yet. They care about their problem.
**Fix:** Move logo to the END. Open with the hook.

### 3. "Generic Superlatives"
**Symptom:** "The best solution." "Revolutionary technology." "World-class results."
**Why flat:** Every product says this. These words carry zero information.
**Fix:** Replace with supported specifics. A measured speed comparison needs its source and conditions; otherwise explain the actual workflow improvement without a made-up multiplier.

### 4. "Missing Middle"
**Symptom:** Good hook, good CTA, flat middle that walks through features.
**Why flat:** No emotional peak. The demo section needs a WOW moment.
**Fix:** Find the single most impressive thing the product does. Build to it. Make it visually different from everything else.

### 5. "Uniform Energy"
**Symptom:** Every scene has same pacing, animation speed, text size.
**Why flat:** No rhythm. Like music at one volume.
**Fix:** Vary tempo: fast cuts → slow hero shot → medium features → fast proof → slow CTA.

## Usage

After writing a script or coding scenes:
```
"Evaluate this script/video using the script-evaluator skill.
Score each dimension 1-10 and give specific fixes for anything below 7."
```

Also useful for comparing versions:
```
"Evaluate V1 and V2 side by side. Which is stronger and why?"
```

## Gotchas

- A high total with one dimension at 2 = video still feels broken. Fix the weakest link first.
- Choose the weakest relevant dimension from the brief and observed evidence; tension is not a universally established top predictor of engagement.
- Don't optimize "interesting" at the expense of truth or clarity. A confusing or exaggerated script is not an improvement.
- This evaluator works on: scripts, storyboards, Remotion TSX code, and even finished videos (describe what you see).

## Troubleshooting

- High creative score but unsupported claim: keep the score separate, identify the exact unsupported claim, and revise or remove that claim before calling the content ready for its requested use.
- No testimonials or numeric proof: do not penalize truthful copy into fabrication; evaluate supported examples and the intended audience instead.

## Source basis

- [FTC: advertisement endorsements](https://www.ftc.gov/news-events/topics/truth-advertising/advertisement-endorsements) — a testimonial cannot supply experience or substantiation that does not exist. Applied here as an evidence-preservation rule, not a legal-compliance certification.

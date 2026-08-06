# Starting from what you remember

Ask an agent to set up a project and it will write a dependency file. That file is the first
artifact of the work and the one nobody reviews, because it looks like boilerplate. It is not
boilerplate. It is a snapshot of what the model recalls, and recall has a date on it.

This note records what was measured on one machine, what follows from it, and what the fix
does not cover.

## Two failures that look identical at the terminal

A dependency line can be wrong in two unrelated ways, and `pip install` reports both the same
way — silently, with a success.

**The package is real and years behind.** `torch==1.7.1` installs. It resolves, it imports, the
first script runs. Measured against the current release it is 16 minor versions behind;
`transformers==4.5.0` is 19. Nothing in the workflow objects, because nothing in the workflow
knows what year it is. The pin came from the training window and inherited its date.

This one has a second-order cost that is worse than the version itself. An old pin drags the
rest of the environment backwards: a CUDA build that matches it, a Python that still supports
it, a set of APIs that the current documentation no longer describes. By the time someone
notices, the fix is not a version bump but an afternoon.

**The package is not real.** The model invents a plausible name. This used to be the harmless
failure — a 404, an error, done. It stopped being harmless when the invented names turned out
to be *predictable*: run the same prompt repeatedly and roughly 43% of hallucinated package
names recur. A recurring name is a target list. Register it, and the next agent that invents it
installs your code instead of failing.

That is not a thought experiment. `react-codeshift` reached 237 repositories, carried there
largely by AI-generated skill and setup files that named it confidently.

## Why "it installed fine" is not evidence

The two failures collapse into one lesson: **existence is not authenticity.** A package
resolving proves that something with that name is published. It does not prove the name was
chosen by a human who knew what they were asking for.

This is why an install-time check comes too late even when it runs. By the time the resolver
speaks, the name is already in the file, already in the commit, already in the pull request
that a reviewer will skim because dependency diffs look like boilerplate. The check has to sit
where the name is *written*, not where it is fetched.

## What the check actually looks at

Five questions, asked of the registry, at the moment a manifest is edited:

| Question | Catches | Threshold used here |
|---|---|---|
| Does this name exist at all? | pure hallucination | absent from the registry → block |
| How old is the *name*? | slopsquat | younger than 120 days → block |
| Does anyone use it? | slopsquat, typosquat | below 500 weekly downloads → block |
| How old is this *release*? | supply-chain window | younger than 7 days → block |
| For fast-moving packages: how far behind? | stale recall | 12+ minor versions → block |

The age question is the one that does the work, and it is worth being explicit about why. A
model cannot legitimately know a package registered after its training data was collected. So a
name the model produced confidently, which appeared in the registry last month, is not a lucky
guess about a new library — it is the shape of a name that was invented and then claimed.

The download floor covers the same ground from the other side: a squatted package has the name
but not the adoption, because adoption takes people, and people do not arrive on schedule.

## Three details that decide whether it survives contact

**404 is an answer, not silence.** The first version of this guard treated a registry 404 the
same as a timeout — "no information, allow." That made it quiet in exactly the case it exists
for: a package that does not exist returns 404. The distinction between *absent* and *unknown*
has to be explicit in the code, because it is invisible in the control flow. It was caught by
the guard's own self-test, which is the argument for writing one.

**Registry outage is not verification.** A registry that is unreachable cannot confirm a
new name, version, or digest. Manifest edits and new installs therefore block. The install
guard may continue only when it has a recent (24-hour) previously verified canonical record,
or when an already reviewed lockfile supplies integrity evidence. Otherwise it points the
agent to the verified-alternative search tool instead of silently allowing an unchecked
package.

**Cache.** A guard that adds seconds to every edit also gets removed. Six hours of caching
makes the cost invisible without making the answer stale in any way that matters — packages do
not become fraudulent on an hourly cycle.

The cache keeps a short outage from stopping a known-good repeat install without turning
network silence into trust. A cache is not a defense against a compromised host; it is only
bounded continuity evidence.

## What this does not do

Stated plainly, because a guard that is trusted beyond its range is worse than none.

- **It does not detect a compromised legitimate package.** An established name with a hijacked
  maintainer account passes every check here. Age, adoption and existence all look right,
  because they *are* right. That is a different control (lockfiles, hash pinning, provenance).
- **It does not know whether the version is right for you.** "Current" is not the same as
  "correct". A pin held back deliberately for a driver, a CUDA build, or a downstream
  constraint is good engineering, and this check will complain about it. That is a false
  positive by design; the override exists for it.
- **The thresholds are heuristics, not findings.** 120 days, 500 downloads, 12 minors — these
  are calibrated to be quiet on real projects, not derived from a study. A genuinely new
  package by a known author will be blocked, and the answer is to override, not to loosen the
  rule for everyone.
- **Private and internal registries are out of scope.** They have no public age or adoption
  signal, so every question above returns nothing.

## The general shape

The specific fix is a dependency check. The general one is older than package managers: **an
agent's default is to answer from memory, and memory is dated.** Anywhere the work starts from
recall rather than from a lookup — a version, an API signature, a config key, a model name, a
CLI flag — the same failure is available, and it presents as confidence.

The countermeasure is not to instruct the agent to be current. Instructions decay under task
pressure, which is the whole reason mechanical gates exist. The countermeasure is to make the
lookup happen at the moment the value is written, and to make the answer *block* rather than
advise, in the narrow set of cases where being wrong is not recoverable by the next person who
reads the diff.

## The second boundary: the file is not the download

The manifest check is still too early to protect a wheel by itself. A later shell command can
fetch a direct `.whl`, switch to an extra index, or install without binding the bytes to a lock
or hash file. The paired `dependency-provenance-guard.py` therefore runs on install commands and
enforces the package-manager proof that the command can actually provide:

- PyPI installs use `--require-hashes`, so the selected wheel is checked against a reviewed hash.
- `uv sync --locked` uses the committed lock rather than silently resolving a new graph.
- npm uses `npm ci --ignore-scripts` for a lockfile install, or an exact package version with
  `--ignore-scripts` when adding one dependency.
- Direct wheels, archives, Git URLs, extra indexes, and non-canonical registries are blocked.

When the requested exact version is older than the registry's latest stable release, the
guard reports the newer version. The default action is to test the latest version; an older
pin is retained or restored only when a compatibility test, supported-runtime constraint,
or ABI/CUDA requirement proves that the latest version does not work here.

The guard does not claim that a real package is benevolent. Registry existence plus a digest is
artifact identity, not maintainer trust; vulnerability, provenance, and upstream review remain
separate controls. Network silence blocks unless bounded cached or lockfile evidence applies.

## Finding a verified alternative

When a requested package name is misspelled, absent, or cannot be verified, use the standard-
library helper rather than guessing another library:

```text
python scripts/dependency-alternatives.py --ecosystem pypi --name reqeusts
python scripts/dependency-alternatives.py --ecosystem npm --name image-reszie
```

It searches official PyPI/npm metadata, rechecks each candidate's exact package record, and
returns only stable releases older than seven days with an artifact digest (npm candidates
also need a download floor). It never edits a manifest or installs a candidate. Compatibility
tests, security review, and the normal hooks remain mandatory.

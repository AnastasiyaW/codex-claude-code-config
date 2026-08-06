# 09 - Supply Chain Defense: Protect Against Malicious Package Updates

## Overview

Supply chain attacks on open-source packages are increasing in frequency. The attack pattern is simple: compromise a maintainer's account, push a malicious update to a popular package, profit from the window before detection. Most poisoned packages get caught within days - but if you install them in that window, the damage is done.

The defense is equally simple: **never install packages published less than 7 days ago.** This single rule eliminates the vast majority of supply chain attacks with almost zero cost.

---

## Package Manager Configs

### npm / Node.js

```ini
# ~/.npmrc
min-release-age=7
```

This tells npm to refuse any package version published less than 7 days ago. If a legitimate package has a brand-new release, you wait a week. If it was a supply chain attack, it's been caught and yanked by then.

### uv / Python

```toml
# ~/.config/uv/uv.toml
exclude-newer = "7 days"
```

Same principle for Python's uv package manager. Packages newer than 7 days are excluded from resolution.

### pip / Python (alternative)

No native equivalent - use uv instead. For pip-only environments, pin exact versions in `requirements.txt` and review diffs on updates manually.

### cargo / Rust

No native `min-release-age` flag yet. Use `cargo-audit` + `cargo-deny` for known vulnerability detection. Pin versions in `Cargo.lock`.

### Go modules

Go's module proxy (proxy.golang.org) caches modules immutably - once fetched, the content can't change. This provides integrity but not freshness gating. Use `go mod verify` and review `go.sum` diffs.

## What Is Enforced At Runtime

The age settings above are necessary but not sufficient. The shared harness wires two
separate `PreToolUse` guards:

1. `hooks/dependency-currency-guard.py` runs when a dependency manifest is written. It
   distinguishes a definitive registry 404 from an unavailable registry. It blocks
   names with the slopsquat profile, releases younger than seven days, selected stale
   fast-moving pins, and any dependency edit that cannot be verified because the
   canonical registry did not answer.
2. `hooks/dependency-provenance-guard.py` runs before an install or download command. It
   rejects direct `.whl`/archive/Git sources, `--extra-index-url`/`--find-links`, and
   non-canonical registries. Explicit package versions must exist in the canonical
   registry and have an artifact digest. `pip` requires `--require-hashes`, `uv sync`
   requires `--locked`, and npm installs require `--ignore-scripts` plus either
   `npm ci` or an exact package version. `uv.lock` and npm lockfiles must contain
   artifact-integrity evidence for lock-only installs.

Registry silence is a block, not a warning. The install guard first asks the live
canonical registry. During a temporary outage it may use only a previously verified
record from `~/.claude/state/dependency-provenance-cache.json`, and only for 24 hours;
otherwise the install is stopped. This cache is convenience evidence, not protection
against a compromised workstation. A package-lock/uv.lock hash is an independent
offline proof for an already reviewed lock, not permission to invent a new package.

When a requested name is probably mistyped or unavailable, search for candidates with:

```text
python scripts/dependency-alternatives.py --ecosystem pypi --name reqeusts
python scripts/dependency-alternatives.py --ecosystem npm --name image-reszie
```

The command searches only the official PyPI/npm surfaces, re-fetches each candidate's
canonical metadata, and returns a candidate only when its stable release is at least
seven days old and has an artifact digest (npm also needs a meaningful download floor).
The candidate still requires project compatibility tests and normal manifest/install
guards; a search result is not an automatic substitution.

This is an artifact-integrity boundary, not a claim that a legitimate package name can
never be compromised. The digest binds the downloaded wheel/tarball to the registry
metadata; the lockfile binds future installs; `pip-audit`, `npm audit`, `cargo audit`,
and upstream/provenance review cover the remaining questions. For npm projects, run
`npm audit signatures` where registry signatures are available; npm documents this as
an explicit verification of registry signatures and attestations.

## Version Selection Policy

For a new dependency, choose the newest stable version that the canonical registry
offers and test it against the actual project. A deliberately older pin is an exception,
not a default: keep it only when compatibility evidence explains the constraint (for
example, the supported Python/Node version, a CUDA/ABI boundary, or a failing project
test). If an upgrade breaks the system, record the failing test and roll back to the
last known-good pin; do not preserve an old version merely because it is familiar.

The guards report a stale exact pin and the latest stable version. They do not perform
an unverified automatic upgrade or rollback, because that would trade one supply-chain
risk for an untested compatibility change.

---

## When to Apply

**Always.** Set these configs globally on every development machine and CI runner. The one-week delay is almost never a problem in practice - you rarely need a package published hours ago.

**Exception:** If you need a critical security patch released today, temporarily override:
```bash
# npm: install with explicit flag
npm install package@version --min-release-age=0

# uv: override for one install
uv pip install package==version --exclude-newer "0 days"
```

---

## Why 7 Days

- Most malicious packages are detected within 24-72 hours
- 7 days provides comfortable margin
- Shorter (e.g. 1 day) still catches most attacks but leaves less buffer
- Longer (e.g. 30 days) creates friction with legitimate updates

---

## Defense in Depth

Package age gating is one layer. Combine with:

1. **Lock files** - Always commit `package-lock.json`, `uv.lock`, `Cargo.lock`. Review diffs.
2. **Pinned versions** - Use exact versions, not ranges (`1.2.3` not `^1.2.3`).
3. **Audit tools** - `npm audit`, `cargo audit`, `pip-audit`. Run in CI.
4. **Minimal dependencies** - Every dependency is attack surface. Fewer = safer.
5. **Scope verification** - Check package scope/author before installing. Typosquatting is real.

The automated checks deliberately do not infer that a project URL or publisher is safe
from a string alone. If an install needs a private mirror, a direct artifact, or a Git
revision, use the explicit `# claude-bypass: deps` marker only after recording and
reviewing that source independently.

---

## Real-World Case: axios@1.14.1 (March 31, 2026)

The `axios` npm package (~100M weekly downloads) was compromised via maintainer account hijack. Attributed to **UNC1069** by Google Threat Intelligence, and tracked independently as **Sapphire Sleet** by Microsoft Threat Intelligence - both refer to the same DPRK-nexus actor.

**Timeline (UTC):**
- **Mar 30 05:57** - Attacker publishes `plain-crypto-js@4.2.0` (clean decoy, establishes npm history)
- **Mar 30 23:59** - `plain-crypto-js@4.2.1` published with malicious postinstall hook
- **Mar 31 00:21** - `axios@1.14.1` published (tagged `latest`) - adds `plain-crypto-js` dependency
- **Mar 31 01:00** - `axios@0.30.4` published (tagged `legacy`) - same payload
- **Mar 31 03:29** - Both malicious versions yanked from npm

**Exposure window: ~3 hours.** `min-release-age=7` would have blocked it completely.

**Attack chain:**
1. Stolen npm token -> manual publish (no GitHub Actions OIDC provenance, unlike legitimate releases)
2. `plain-crypto-js` postinstall hook (`setup.js`) deobfuscates and runs a dropper
3. Dropper uses XOR cipher + dynamic `require()` to bypass static analysis
4. Downloads platform-native RAT (WAVESHAPER.V2) from `sfrclak[.]com:8000`
5. RAT beacons every 60s - full remote access: file exfiltration, arbitrary code execution, persistence
6. Dropper self-destructs after deployment - **inspecting `node_modules` after infection shows nothing**

**What would have helped:**

| Defense | Effective? |
|---------|-----------|
| `min-release-age=7` | **Yes** - `plain-crypto-js` was <24h old |
| `npm ci` (lockfile) | **Yes** - lockfile pinned to 1.14.0 |
| `--ignore-scripts` in CI | **Yes** - blocks postinstall hook |
| SLSA provenance check | **Yes** - malicious versions lacked GitHub OIDC attestation |
| `npm audit` | Partial - detected ~6min after publish, but only if you check before install |

**Key takeaway:** The decoy package was pre-staged 18 hours before the attack to build npm history. Even a 24-hour age gate might not be enough if attackers plan ahead. **7 days is the right buffer.**

**Claude Code users:** If you installed Claude Code via npm (`@anthropic-ai/claude-code`) during the exposure window, verify your machine is clean. Anthropic recommends the native installer (`curl -fsSL https://claude.ai/install.sh | bash`) which is a standalone binary and does not pull transitive npm dependencies - eliminating this attack vector entirely.

Sources: Elastic Security Labs, Snyk, Wiz, Google Cloud Blog (GTIG attribution), Microsoft Threat Intelligence (Sapphire Sleet attribution), GitHub Advisory GHSA-fw8c-xr5c-95f9.

---

## Gotchas

- **CI caches may bypass age gating** - If your CI caches `node_modules`, the config only applies on cache miss. Ensure clean installs periodically.
- **Monorepo lockfile drift** - In monorepos, one dev's `npm install` without the config can pull fresh packages. Enforce the config at repo level (`.npmrc` in repo root).
- **Transitive dependencies** - The config applies to transitive deps too (good), but you might not notice when a deep dependency is being held back (check `npm outdated`).
- **Private registries** - If you use a private npm/PyPI registry that mirrors public, ensure the mirror also respects age gating, or the freshness check happens client-side.
- **Self-destructing malware** - Modern supply chain payloads clean up after execution. Post-infection inspection of `node_modules` may reveal nothing. Check for RAT artifacts on disk and network IOCs.
- **Account hijack vs typosquat** - Age gating protects against both, but account hijacks of legitimate packages are harder to detect because the package name is correct.

## See Also

- [npm min-release-age docs](https://docs.npmjs.com/cli/using-npm/config#min-release-age)
- [PyPA Simple Repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/) - canonical package files and hashes
- [npm registry docs](https://docs.npmjs.com/misc/registry/) - official registry metadata surface
- [npm registry signature verification](https://docs.npmjs.com/verifying-registry-signatures/) - `npm audit signatures`
- [npm package search guidance](https://docs.npmjs.com/searching-for-and-choosing-packages-to-download/) - search and selection considerations
- [uv configuration reference](https://docs.astral.sh/uv/reference/settings/)
- [Elastic Security Labs - axios supply chain analysis](https://www.elastic.co/security-labs/axios-one-rat-to-rule-them-all)
- [StepSecurity Safe Chain](https://www.stepsecurity.io/) - enforces package age + SLSA provenance

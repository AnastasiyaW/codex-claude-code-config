# No junk in git — one rule for Claude AND Codex (mechanical)

## Принцип (2026-07-15, user directive)

Git-репо (особенно text/config/meta-index hub) хранит **durable человекочитаемое
состояние**: код, доки, handoffs, chronicles, knowledge, rules, skills, конфиги.
Тяжёлое/регенерируемое/scratch — **НАРУЖУ**. Правило должно быть **очевидным и
ЕДИНЫМ** для всех агентов (Claude И Codex), а не жить в голове одного harness.

Повод: codex-сессии закоммитили в hub чужой мусор (LingoSparta-материалы, `*.pt`/
`*.safetensors`, датасетные PNG), и `.gitignore` hub'а был снесён до 3 строк
(инцидент 2026-07-02). Prompt-advice тут недостаточно — **механический инвариант**.

## Что НЕ коммитим
Веса/тензоры (`*.pt *.pth *.ckpt *.safetensors *.onnx *.pkl *.bin *.gguf`), архивы/
медиа (`*.zip *.tar *.gz *.mp4 *.mov *.psd *.tiff`), нативные бинарники (`*.exe *.dll
*.so *.dylib *.o *.a`), scratch/cache/deps (`node_modules/ .venv/ __pycache__/
.cache/ *.pytest_cache/ dist/ build/ .next/ .turbo/`), worktrees (`worktrees/
.claude/worktrees/ .claude/tmp/`), датасеты/тяжёлые сэмплы (`datasets/ denoise-lab/
ois-psd-dataset/ juliebelanska-dataset/ metka_review*/ exports/`), любой файл
**>5 MB**, и всё, что уже в `.gitignore` (не обходить `git add -f`). Тяжёлое —
на Drive/S3/Volume + ссылка в репо (в git-историю — необратимый bloat).

## Механически (едино для обоих, git-уровень)
- **Хук:** `~/.claude/scripts/git-hooks/pre-commit` → `pre_commit_no_junk.py`
  (blocked-типы/дир, размер >5MB, force-staged .gitignore'd). `--self-test`.
- **Scope:** git `core.hooksPath = ~/.claude/scripts/git-hooks` — срабатывает у
  Claude Code, локального Codex и ручного `git commit` одинаково. Один хук — оба агента.
- **Fail-open** (баг в хуке не блокирует коммиты). Override: `ALLOW_COMMIT_JUNK=1 git commit ...`.
- **Belt & suspenders:** хук дублирует корректный `.gitignore` — держим оба.
- **Cloud Codex** machine-хук не видит → там правило держат committed `.gitignore` + документ ниже.

## Единый источник правды (obvious для обоих)
- Канон: [`~/.claude/scripts/git-hooks/COMMIT-HYGIENE.md`](../scripts/git-hooks/COMMIT-HYGIENE.md)
- Codex видит то же в `~/.codex/AGENTS.md` → раздел «Commit Hygiene» (тот же текст + ссылка на канон).

## Related
- `git-source-of-truth.md` — что коммитим (почти всё) vs 4 класса наружу; этот rule = механический энфорсмент «наружу».
- `secrets-as-data.md` + `pre_push_public_repo_scan.py` — выходная граница для секретов (pre-push); этот rule — для мусора (pre-commit).
- `cross-harness-agents-md.md` — почему требования дублируются в AGENTS.md (Codex) и rules (Claude), но из одного канона.
- `safety-hooks.md` — свод mechanical-enforcement хуков.

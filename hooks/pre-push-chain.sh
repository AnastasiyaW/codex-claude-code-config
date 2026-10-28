#!/bin/sh
# core.hooksPath=.githooks in this repo replaces the global hooks folder, so the
# global pre-push secret/PII scan would never run for this PUBLIC repo. Chain to it,
# and refuse the push when it is absent: an unscanned push to a public repo is the
# one leak that cannot be taken back.
GLOBAL_HOOKS=$(git config --global core.hooksPath)
if [ -n "$GLOBAL_HOOKS" ] && [ -x "$GLOBAL_HOOKS/pre-push" ]; then
    exec "$GLOBAL_HOOKS/pre-push" "$@"
fi
echo "[pre-push] global pre-push scan not found (git config --global core.hooksPath); push refused." >&2
exit 1

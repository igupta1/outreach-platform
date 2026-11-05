#!/bin/zsh
# The nightly batch (system_b/nightly.py), from the last pushed commit whose
# tests pass, never the working tree: another session's half-finished edit
# broke the morning command more than once. launchd runs this at 02:00, and
# again at 04:00 and 06:00 as retries that exit at once when tonight's batch is
# already built (ops/com.outreach.nightly.plist). By hand: ops/nightly.sh
# [--dry-run]; any argument skips the already-built check.
set -u
HOME_REPO="${OUTREACH_HOME:-$HOME/Developer/outreach-platform}"
CODE="${OUTREACH_NIGHTLY_CODE:-$HOME/Developer/outreach-nightly}"
PY="$HOME_REPO/system_b/.venv/bin/python"
LOGS="$HOME_REPO/logs"; mkdir -p "$LOGS"
LOG="$LOGS/nightly.log"; GOOD="$LOGS/nightly-last-good"
LOCK="$LOGS/.nightly.lock"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') nightly start"
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  echo "another nightly run is going (pid $(cat "$LOCK")); exiting"; exit 0
fi
echo $$ >"$LOCK"; trap 'rm -f "$LOCK"' EXIT
# Whole night awake, at full speed. launchd starts the job on the first wake
# after 02:00, often a screen-off "dark wake" (the Mac idle-sleeps after a
# minute even on the charger): 2026-11-05 the run sat there 02:12-06:44 and
# a one-minute publish took 4.5 hours. -u declares the user active, which
# turns that into a full wake; -i -s -w then hold it until this script ends.
caffeinate -u -t 10 &
caffeinate -i -s -w $$ &

git -C "$HOME_REPO" fetch -q origin lead-inventory || echo "fetch failed: using the last fetched commit"
TARGET=$(git -C "$HOME_REPO" rev-parse origin/lead-inventory)
if [ ! -d "$CODE/.git" ] && [ ! -f "$CODE/.git" ]; then
  git -C "$HOME_REPO" worktree add -q --detach "$CODE" "$TARGET"
fi
git -C "$CODE" checkout -q --detach "$TARGET"
# The code's own gitignored files (the key, the name-fix cache, local data)
# are the main checkout's; link each one the checkout lacks.
ln -sf "$HOME_REPO/system_b/.env" "$CODE/system_b/.env"
for f in "$HOME_REPO"/system_b/data/*(N); do
  b=$(basename "$f"); [ -e "$CODE/system_b/data/$b" ] || ln -s "$f" "$CODE/system_b/data/$b"
done

cd "$CODE"
if [ $# -eq 0 ] && "$PY" -m system_b.nightly --home "$HOME_REPO" --built-tonight; then
  echo "tonight's batch is already built; nothing to do"; exit 0
fi
if "$PY" -m pytest -q -x system_b/tests >"$LOGS/nightly-tests.log" 2>&1; then
  echo "$TARGET" >"$GOOD"; echo "tests pass at $TARGET"
else
  LAST=$(cat "$GOOD" 2>/dev/null || true)
  echo "tests FAIL at $TARGET (logs/nightly-tests.log)"
  if [ -z "$LAST" ]; then
    printf 'nightly batch %s\nNOT RUN: tests fail on the latest code and no earlier commit has passed.\nSee logs/nightly-tests.log\n' "$(date '+%Y-%m-%d')" >"$LOGS/nightly-latest.txt"
    printf '{"state": "failed", "night": "%s", "started": "%s", "finished": "%s", "reason": "the code tests fail and no earlier version has passed; see logs/nightly-tests.log"}\n' \
      "$(date '+%Y-%m-%d')" "$(date '+%Y-%m-%dT%H:%M:%S')" "$(date '+%Y-%m-%dT%H:%M:%S')" >"$LOGS/nightly-status.json"
    exit 1
  fi
  git -C "$CODE" checkout -q --detach "$LAST"; echo "using the last good commit $LAST"
fi
"$PY" -u -m system_b.nightly --home "$HOME_REPO" "$@"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') nightly end (exit $?)"

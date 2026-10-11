#!/bin/bash
# Republish the public static site when the index has actually grown.
# Deterministic on purpose: no model decides whether this ran.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${SPIN_REPO:-$HERE}                 # the git checkout that GitHub Pages serves docs/ from
INDEX_DIR=${SPIN_DATA:-$REPO/data}       # where spin.py keeps the growing index
DOMAIN=${SPIN_DOMAIN:-}                  # custom Pages domain; empty = no CNAME, no link in the notice
NOTIFY=${SPIN_NOTIFY:-}                  # optional command, called with one message argument

cd "$REPO"
# Someone else may have pushed (docs, README). Catch up first or the push below is rejected.
git pull -q --rebase --autostash origin main
before=$(python3 -c "
import json,sys
try: d=json.load(open('docs/index.json'))
except Exception: print(0); sys.exit()
print(sum(len(v) for v in d['cats'].values()))")

SPIN_DATA="$INDEX_DIR" SPIN_DOMAIN="$DOMAIN" python3 export.py "$REPO/docs" >/dev/null

after=$(python3 -c "
import json
d=json.load(open('docs/index.json'))
print(sum(len(v) for v in d['cats'].values()))")
ready=$(python3 -c "
import json
d=json.load(open('docs/index.json'))
print(sum(1 for v in d['cats'].values() if v), len(d['cats']))")

# export.py always stamps a fresh "built" time, so the file differs even when the
# music does not. Compare the tracks themselves, not the timestamp.
if python3 - <<'PY'; then
import json, subprocess, sys
new = json.load(open("docs/index.json"))["cats"]
try:
    old = json.loads(subprocess.run(["git", "show", "HEAD:docs/index.json"],
                                    capture_output=True, text=True, check=True).stdout)["cats"]
except Exception:
    sys.exit(1)                      # no previous version -> publish
sys.exit(0 if old == new else 1)     # 0 = identical = nothing to do
PY
  git checkout -- docs/index.json
  echo "no change ($after tracks) - nothing to publish"
  exit 0
fi

git add docs
git -c user.name=casareanderson -c user.email=51646180+casareanderson@users.noreply.github.com \
  commit -q -m "Republish crate: $after tracks, $ready categories populated"
git push -q origin main
echo "published: $before -> $after tracks, $ready categories"

# say so if asked to, but never let a failed notification hide a successful publish
if [ -n "$NOTIFY" ]; then
  # shellcheck disable=SC2086  # NOTIFY is a command line, word-splitting is intended
  $NOTIFY "spin-that-dice republished: $after tracks, $ready categories${DOMAIN:+ - https://$DOMAIN}" \
    >/dev/null 2>&1 || echo "(notify failed, publish still succeeded)"
fi

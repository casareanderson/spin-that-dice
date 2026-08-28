#!/bin/bash
# Republish the public static site when the index has actually grown.
# Deterministic on purpose: no model decides whether this ran.
set -euo pipefail

INDEX_DIR=${SPIN_DATA:-/opt/spin-that-dice/data}
REPO=${SPIN_REPO:-/root/spin-that-dice}
DOMAIN=${SPIN_DOMAIN:-spin-that-dice.cn1-lab.uk}

cd "$REPO"
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
git -c user.name=casareanderson -c user.email=christian.asare-anderson@writer.com \
  commit -q -m "Republish crate: $after tracks, $ready categories populated"
git push -q origin main
echo "published: $before -> $after tracks, $ready categories"

# tell the estate, but never let a failed notification hide a successful publish
if [ -x /opt/hermes-agent/notify.py ] || [ -f /opt/hermes-agent/notify.py ]; then
  python3 /opt/hermes-agent/notify.py \
    "spin-that-dice republished: $after tracks, $ready categories - https://$DOMAIN" \
    >/dev/null 2>&1 || echo "(notify failed, publish still succeeded)"
fi

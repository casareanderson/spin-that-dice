#!/usr/bin/env bash
# Runs the steps in docs/SETUP.md that need no Spotify app and no music server.
# Used by .github/workflows/setup-check.yml. Run it locally from the repo root too.
set -euo pipefail
step() { printf '\n== %s\n' "$*"; }
PORT=${PORT:-18770}

step "1. install"
python3 -m pip install -q requests

step "1. offline tests"
python3 -m unittest discover -s tests 2>&1 | tail -3

step "1. first run, no credentials"
log=$(mktemp)
env -u SPOTIFY_CLIENT_ID -u SPOTIFY_CLIENT_SECRET HOME="$(mktemp -d)" SPIN_PORT=$PORT \
  python3 spin.py 2>"$log" &
pid=$!
trap 'kill $pid 2>/dev/null || true' EXIT
for i in $(seq 1 30); do curl -sf "localhost:$PORT/api/categories" >/dev/null && break; sleep 0.5; done
head -1 "$log"
grep -q "spin-that-dice on 127.0.0.1:$PORT - spotify, 43 categories, 305 tracks indexed" "$log"

step "1. the API answers"
curl -sf "localhost:$PORT/api/categories" | python3 -c "import json,sys;d=json.load(sys.stdin);assert len(d['cats'])==43,d;print(len(d['cats']),'categories')"
curl -sf "localhost:$PORT/api/roll?cat=Soul" | python3 -c "import json,sys;d=json.load(sys.stdin);assert d['track']['id'],d;print('rolled:',d['track']['a'],'-',d['track']['n'])"
curl -sf "localhost:$PORT/api/roll?cat=any" | python3 -c "import json,sys;d=json.load(sys.stdin);assert d['track']['id'],d;print('any ok')"
code=$(curl -s -o /dev/null -w '%{http_code}' "localhost:$PORT/api/roll?cat=Nope"); [ "$code" = 404 ] || { echo "FAIL unknown cat -> $code"; exit 1; }
curl -sf "localhost:$PORT/" | grep -qi "<html" && echo "page served"
code=$(curl -s -o /dev/null -w '%{http_code}' --path-as-is "localhost:$PORT/../spin.py"); [ "$code" = 404 ] || { echo "FAIL traversal -> $code"; exit 1; }
echo "unknown category and path traversal refused"
kill $pid; trap - EXIT

step "6. static export"
out=$(mktemp -d)
python3 export.py "$out" >/dev/null
test -s "$out/index.html" && test -s "$out/index.json"
python3 -c "import json,sys;d=json.load(open(sys.argv[1]));n=sum(len(v) for v in d['cats'].values());assert n>=305,n;print(n,'tracks exported')" "$out/index.json"

step "republish.sh is valid bash"
bash -n republish.sh

printf '\nSETUP CHECK PASSED\n'

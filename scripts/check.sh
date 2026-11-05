#!/usr/bin/env sh
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${GAMEPROMO_PYTHON:-$repo/.venv/bin/python}
cd "$repo"

"$python_bin" -m unittest discover -v
"$python_bin" verify_release.py
node --check static/app.js
node --check static/discovery.js
node --check static/releases.js
node --check static/motion.js
git diff --check
printf '%s\n' 'CHECKS OK'

#!/usr/bin/env sh
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${GAMEPROMO_PYTHON:-python3.12}

"$python_bin" -m venv "$repo/.venv"
"$repo/.venv/bin/python" -m pip install --require-hashes -r "$repo/requirements.lock"
printf '%s\n' "Ambiente pronto: $repo/.venv/bin/python"

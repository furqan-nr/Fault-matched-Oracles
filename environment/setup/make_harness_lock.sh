#!/usr/bin/env bash
# E1 — build the fixed HARNESS environment and generate the pinned lockfile.
# Run once on the laptop (Linux/macOS, or Windows via WSL recommended for Rust builds).
#
# Produces: environment/requirements.lock  (the harness lock — Qiskit is NOT here).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3.11}"   # locked harness Python (ENV.md)
VENV="${VENV:-.venv-harness}"

echo ">> Using $($PYTHON --version)"
"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade "pip>=19" "setuptools-rust>=1.9" wheel

echo ">> Installing harness deps (no Qiskit-under-test here)"
python -m pip install -r environment/requirements.harness.in

echo ">> Freezing lock"
python -m pip freeze --exclude-editable > environment/requirements.lock
sha256sum environment/requirements.lock | tee environment/requirements.lock.sha256

echo ">> Done. Record the sha256 and Benchpress revision in environment/ENV.md."

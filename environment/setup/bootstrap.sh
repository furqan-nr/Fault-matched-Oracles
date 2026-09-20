#!/usr/bin/env bash
# Turnkey E1-E4 + Phase 0 bootstrap (Linux/macOS).
# Prereqs (one-time): python3.11, build-essential, git, and a Rust toolchain. See SETUP.md.
# Usage:  bash environment/setup/bootstrap.sh [QISKIT_BUILD_TAG]   (default 2.4.2)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
BUILD_TAG="${1:-2.4.2}"
export PYTHON="${PYTHON:-python3.11}"

echo "==> Checking prerequisites"
command -v "$PYTHON" >/dev/null || { echo "MISSING: $PYTHON (see SETUP.md)"; exit 2; }
command -v cargo    >/dev/null || { echo "MISSING: Rust/cargo (see SETUP.md)"; exit 2; }
command -v git      >/dev/null || { echo "MISSING: git"; exit 2; }
"$PYTHON" --version; rustc --version; cargo --version

echo "==> E1: harness lock (.venv-harness, no Qiskit)"
bash environment/setup/make_harness_lock.sh

echo "==> E2: anchor/dev env (.venv-anchor = harness + Qiskit 2.4.2 wheel)"
"$PYTHON" -m venv .venv-anchor
# shellcheck disable=SC1091
source .venv-anchor/bin/activate
python -m pip install --upgrade "pip>=19" wheel
python -m pip install -r environment/requirements.anchor.in
python -m pip install -e .

echo "==> E3: from-source Qiskit build smoke ($BUILD_TAG) [isolated venv]"
bash environment/setup/build_qiskit_event.sh "$BUILD_TAG" "smoke-${BUILD_TAG//./_}"

echo "==> E4 + Phase 0 (in .venv-anchor)"
# shellcheck disable=SC1091
source .venv-anchor/bin/activate
python environment/setup/check_feasibility.py
python -m cart.cli manifest
python -m pytest -q

echo "==> Done. Fill machine-specific fields in environment/ENV.md."

#!/usr/bin/env bash
# E3 (and Phase 2) — build Qiskit-under-test FROM SOURCE for one revision.
# Usage:
#   environment/setup/build_qiskit_event.sh <git_sha_or_tag> <event_environment_id>
set -euo pipefail

SHA="${1:?usage: build_qiskit_event.sh <sha_or_tag> <event_environment_id>}"
EID="${2:?usage: build_qiskit_event.sh <sha_or_tag> <event_environment_id>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python3.11}"

WORK="environment/_builds/$EID"
LOCK="environment/events/$EID.lock"

if [ -f "$LOCK" ] && [ "${FORCE:-0}" != "1" ]; then
  echo ">> $LOCK already exists; skipping rebuild (set FORCE=1 to rebuild)."
  exit 0
fi

command -v cargo >/dev/null || { echo "ERROR: Rust toolchain (cargo) not found — required to build Qiskit from source." >&2; exit 2; }
mkdir -p "$WORK" environment/events

if [ ! -d "$WORK/qiskit/.git" ]; then
  rm -rf "$WORK/qiskit"
  # Blobless partial clone (full commit/tree history; file blobs fetched on demand at checkout) with
  # retries, so a flaky network doesn't drop the build. Much lighter than a full clone.
  ok=0
  for attempt in 1 2 3; do
    if git -c http.postBuffer=524288000 -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 \
         clone --filter=blob:none https://github.com/Qiskit/qiskit "$WORK/qiskit"; then
      ok=1; break
    fi
    echo "!! clone attempt $attempt/3 failed; cleaning up and retrying ..." >&2
    rm -rf "$WORK/qiskit"
  done
  [ "$ok" = "1" ] || { echo "clone failed after 3 attempts (network)." >&2; exit 3; }
fi
git -C "$WORK/qiskit" fetch --all --tags --quiet
git -C "$WORK/qiskit" checkout --quiet "$SHA"
RESOLVED_SHA="$(git -C "$WORK/qiskit" rev-parse HEAD)"

VENV="$WORK/venv"
"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade "pip>=19" "setuptools-rust>=1.9" wheel
echo ">> Building Qiskit @ $RESOLVED_SHA from source (Rust: $(rustc --version))"
python -m pip install "$WORK/qiskit"

python - "$EID" "$SHA" "$RESOLVED_SHA" > "$LOCK" << 'PY'
import json, sys, platform
import qiskit
eid, req, resolved = sys.argv[1:4]
print(json.dumps({
    "event_environment_id": eid,
    "requested": req,
    "resolved_sha": resolved,
    "qiskit_version": qiskit.__version__,
    "python": platform.python_version(),
    "platform": platform.platform(),
}, indent=2))
PY
echo ">> Recorded $LOCK"

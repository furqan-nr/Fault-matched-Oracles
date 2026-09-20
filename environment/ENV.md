# Environment Record

Decisions are locked; machine-specific fields are filled when E1–E4 run on the laptop.

## Locked decisions (publishing-driven)
- **Qiskit release window:** 2.x current line, band **2.1 → latest stable minor**.
- **Build/instrumentation anchor:** `2.4.2` (verified: instrumentation + oracles, 2026-06-25).
- **Harness Python:** **3.11** (supported across 2.1–2.4 and by qiskit-aer).
- **Topology feature:** connectivity pressure (METHODOLOGY §2.4).
- Rationale: early-2027 publication → current, maintained Qiskit line. See `RELEASE_WINDOW_DECISION.md`.

## Harness machine (fill in E1–E2)
- OS / version:
- CPU model / core count:
- Total RAM:
- Python version: # must be 3.11.x
- pip version: # >= 19 (PEP 517)
- Rust toolchain (rustc / cargo): # required for per-event Qiskit source builds; meet 2.x MSRV
- setuptools-rust: # >= 1.9

## Harness layer (fixed for the whole study)
- Benchpress revision (commit SHA):
- `requirements.lock` sha256:

## Qiskit-under-test layer (per event)
- Build recipe: `environment/setup/build_qiskit_event.sh` → `environment/events/<event_environment_id>.lock`

## Feasibility checks (E4)
- Statevector feasibility (sampled-SV tier, ≤20–22 qubits) on this machine: [ ] confirmed
  (`python environment/setup/check_feasibility.py`)
- From-source build of one event's baseline+candidate succeeds: [ ] confirmed
- Notes:

## Provenance
- Window/instrumentation/oracle evidence gathered on Linux, Python 3.10.12 sandbox
  (Qiskit 1.2.4 / 1.4.2 / 2.3.1 / 2.4.2). Anchor for this study: 2.4.2.

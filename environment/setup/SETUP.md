# Environment Setup (E1–E4), run on your laptop

I cannot install software on your machine from here (my shell is an isolated Linux sandbox, not
your laptop). These are the exact steps to do it yourself. **Recommended: WSL2 (Ubuntu) on
Windows**, building Qiskit from source needs a Rust + C toolchain, which is far smoother on
Linux/WSL than native Windows. Everything below assumes WSL2/Ubuntu; native-Windows notes are at
the end.

## 0. One-time prerequisites (Ubuntu / WSL2)

```bash
# Python 3.11 + build basics
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential git curl

# Rust toolchain (required to build Qiskit 2.x from source; meets the 2.x MSRV)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
rustc --version && cargo --version    # confirm
```

Open WSL in this project folder:
```bash
cd /mnt/c/Users/furqa/Desktop/Aspire/quantum-transpiler-regression-testing
```

## 1. E1, build the harness + lockfile

```bash
PYTHON=python3.11 bash environment/setup/make_harness_lock.sh
```
Produces `environment/requirements.lock` (+ `.sha256`). Qiskit is **not** in this lock.

## 2. E3, confirm the from-source Qiskit build (the one unverified gate)

Pick any in-window 2.x tag to smoke the build (e.g. `2.4.2`):
```bash
bash environment/setup/build_qiskit_event.sh 2.4.2 smoke-2_4_2
```
Success writes `environment/events/smoke-2_4_2.lock`. (In Phase 2 you run this per event with the
real `baseline_sha` / `candidate_sha`.)

## 3. E4, statevector feasibility

```bash
source .venv-harness/bin/activate
python environment/setup/check_feasibility.py
```
Pick a sampled-SV ceiling whose peak stays well under your RAM (reference: ~352 MB at 22 qubits).

## 4. Smoke the Phase 0 pipeline

```bash
pip install -e .
python -m cart.cli manifest        # writes data/manifest_static/ + results/<run>/smoke_profile/
pytest -q                          # 8 tests
```

## 5. Record results

Fill the blank fields in `environment/ENV.md` (OS, CPU, RAM, versions, Benchpress SHA, lock sha256,
feasibility checkbox).

---

### Native Windows (no WSL), fallback only
Harder; use only if you can't use WSL.
1. Install Python 3.11 (python.org), check "Add to PATH".
2. Install Rust via `rustup-init.exe` (https://rustup.rs), choose the MSVC toolchain.
3. Install "Visual Studio Build Tools" with the C++ workload (provides the MSVC compiler/linker).
4. Translate the `.sh` steps to PowerShell: create the venv (`py -3.11 -m venv .venv-harness`),
   `pip install -r environment/requirements.harness.in`, `pip freeze > environment/requirements.lock`,
   and `pip install <git checkout of qiskit at the chosen sha>` for the per-event build.
The Python/oracle/instrumentation code itself is OS-independent and runs the same on Windows.

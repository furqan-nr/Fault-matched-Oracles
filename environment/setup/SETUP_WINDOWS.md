# Environment Setup (E1–E4), native Windows / PowerShell

No WSL. Run everything in **PowerShell**. Building Qiskit 2.x from source on Windows needs
Python 3.11, the Rust **MSVC** toolchain, and the Visual C++ build tools (provides `link.exe`).

## 0. One-time prerequisites

Open **PowerShell as Administrator** and install with winget:

```powershell
winget install -e --id Python.Python.3.11
winget install -e --id Git.Git
winget install -e --id Rustlang.Rustup
winget install -e --id Microsoft.VisualStudio.2022.BuildTools `
  --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

Then set the Rust MSVC toolchain (new PowerShell window so PATH refreshes):

```powershell
rustup default stable-msvc
rustc --version ; cargo --version        # confirm both work
py -3.11 --version                       # confirm Python 3.11
```

If `winget` is missing, install "App Installer" from the Microsoft Store, or grab installers
directly: Python (python.org, tick "Add to PATH"), Rust (https://rustup.rs → `rustup-init.exe`,
choose MSVC), Build Tools (https://aka.ms/vs/17/release/vs_BuildTools.exe → C++ build tools).

## 1. Allow local scripts (once)

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 2. Run it all (one command)

```powershell
cd C:\Users\furqa\Desktop\Aspire\quantum-transpiler-regression-testing
.\environment\setup\bootstrap.ps1
```

This runs E1 (harness lock), E3 (builds Qiskit `2.4.2` from source to confirm your toolchain),
E4 (statevector feasibility), then installs the package, builds the Phase 0 manifest, and runs the
tests.

### Or step by step
```powershell
cd C:\Users\furqa\Desktop\Aspire\quantum-transpiler-regression-testing

# E1 - pinned harness lock (no Qiskit)
.\environment\setup\make_harness_lock.ps1

# E2 - anchor/dev env (harness + Qiskit 2.4.2 wheel) where Phase 0 + tests run
py -3.11 -m venv .venv-anchor
.\.venv-anchor\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=19" wheel
python -m pip install -r environment\requirements.anchor.in
python -m pip install -e .

# E3 - from-source Qiskit build (isolated venv); confirms your Rust toolchain
.\environment\setup\build_qiskit_event.ps1 -Sha 2.4.2 -EventEnvId smoke-2_4_2

# E4 + Phase 0 - in the anchor env
python environment\setup\check_feasibility.py
python -m cart.cli manifest      # writes data\manifest_static\ + results\<run>\smoke_profile\
python -m pytest -q              # 8 tests
```

> Note: Phase 0 and the tests run in **`.venv-anchor`** (it has Qiskit). The bare `.venv-harness`
> intentionally has no Qiskit (per-event builds supply it in Phase 2).

## 3. Record results
Fill the blank fields in `environment\ENV.md` (OS, CPU, RAM, versions, Benchpress SHA, lock
sha256, feasibility checkbox).

## Troubleshooting
- **`link.exe` not found / linker error during build** → VC++ Build Tools missing or not on PATH;
  reinstall step 0 (C++ workload) and use a fresh terminal.
- **`cargo` not found** → open a new terminal after installing Rust; ensure `%USERPROFILE%\.cargo\bin` is on PATH.
- **`py` not recognized** → reinstall Python with "Add to PATH", or use the full path to python3.11.
- **Long source build** → the from-source Qiskit build takes several minutes and high CPU; that is expected.
- If a step fails, paste the error and I'll debug it with you.

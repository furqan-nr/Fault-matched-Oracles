#!/usr/bin/env python3
"""P1 — Automated regression bisection over Qiskit history (build-cached binary search).

Given a KNOWN-GOOD revision (old release where the trigger behaved correctly) and a KNOWN-BAD
revision (the buggy commit just before a fix), this locates the FIRST commit that introduced the
regression, by binary-searching the first-parent history and, at each probe, building that revision
from source (reusing the existing, tested `build_qiskit_event` recipe) and running the trigger through
the channel-matched oracle.

This is functionally `git bisect run`, but implemented as an explicit binary search so that (a) each
build is cached by a per-revision event-id (the build script skips if the .lock exists), and (b) a
build failure is treated as SKIP rather than aborting the whole search.

Oracles (choose with --oracle), all layout/permutation-aware and consistent with the paper:
  semantic      output-equivalence modulo global phase + qubit permutation (the "black-box" oracle)
  contract      isolated-pass property differential on TranspileLayout / *_index_layout /
                routing_permutation / virtual_permutation_layout  (the H1 channel)
  determinism   same-seed transpile twice; structural+layout fingerprint must agree
  global_phase  circuit.global_phase must match the good reference (mod 2*pi)

A commit is BAD if its trigger result diverges from the GOOD reference under the chosen oracle.

Usage (PowerShell / bash — same args):
  python scripts/bisect_regression.py \
      --good  2.0.0 \
      --bad   7c3890da097c851876b86453a1da6ee7d3208048 \
      --oracle contract --isolated-pass ElidePermutations \
      --targeted trig-h1-elide-permutations --backend none --opt 3 \
      --pr 14603 --reference "Fix ElidePermutations pass in the presence of PermutationGates"

  # a determinism regression:
  python scripts/bisect_regression.py --good 2.3.0 --bad <buggy_sha> \
      --oracle determinism --family qft --n 8 --backend line --opt 1 --pr 14730

Output: the introducing commit SHA, a JSON trace under results/bisect-<pr>-<ts>/, and the exact
`add_forward_event.py` command to register the discovered forward-regression event.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

CACHE_CLONE = _REPO_ROOT / "environment" / "_builds" / "_bisect" / "qiskit"
IS_WIN = os.name == "nt"


# ------------------------------------------------------------------ git helpers
def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "--no-pager", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def ensure_clone() -> Path:
    d = CACHE_CLONE
    if not (d / ".git").exists():
        if d.exists():                       # clear a partial/failed clone
            shutil.rmtree(d, ignore_errors=True)
        d.parent.mkdir(parents=True, exist_ok=True)
        print(f">> cloning Qiskit into {d} (one-time, blobless partial clone) ...")
        # blobless clone: full commit+tree history for bisect, file blobs fetched on demand at
        # checkout. Much smaller than a full clone and far less likely to drop mid-transfer.
        base = ["git", "-c", "http.postBuffer=524288000", "-c", "http.lowSpeedLimit=1000",
                "-c", "http.lowSpeedTime=60", "clone", "--filter=blob:none",
                "https://github.com/Qiskit/qiskit", str(d)]
        for attempt in range(1, 4):
            rc = subprocess.run(base).returncode
            if rc == 0 and (d / ".git").exists():
                break
            print(f"!! clone attempt {attempt}/3 failed (rc={rc}); cleaning up and retrying ...")
            shutil.rmtree(d, ignore_errors=True)
        else:
            raise SystemExit(
                "clone failed after 3 attempts (network). Clone manually, then re-run:\n"
                f'  git clone --filter=blob:none https://github.com/Qiskit/qiskit "{d}"')
    _git(d, "fetch", "--all", "--tags", "--quiet")
    return d


def resolve(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref)


def first_parent_range(repo: Path, good: str, bad: str) -> list[str]:
    """Commits in (good, bad] along first-parent, OLDEST first."""
    out = _git(repo, "rev-list", "--first-parent", "--reverse", f"{good}..{bad}")
    return out.splitlines() if out else []


# ------------------------------------------------------------------ build + probe
def build_rev(sha: str) -> Path | None:
    """Build one revision via the existing build_qiskit_event recipe; return the venv python."""
    short = sha[:12]
    eid = f"_bisect-{short}"
    venv = _REPO_ROOT / "environment" / "_builds" / eid / "venv"
    py = venv / ("Scripts/python.exe" if IS_WIN else "bin/python")
    if py.exists():
        return py  # cached
    if IS_WIN:
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File",
               str(_REPO_ROOT / "environment/setup/build_qiskit_event.ps1"),
               "-Sha", sha, "-EventEnvId", eid]
    else:
        cmd = ["bash", str(_REPO_ROOT / "environment/setup/build_qiskit_event.sh"), sha, eid]
    print(f">> building {short} ...")
    r = subprocess.run(cmd, cwd=str(_REPO_ROOT))
    if r.returncode != 0 or not py.exists():
        print(f"!! build failed for {short} -> SKIP")
        return None
    return py


def run_trigger(py: Path, out_dir: Path, args, isolated: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(py), "-m", "cart.labels.historical_worker",
           "--backend", args.backend, "--opt", str(args.opt),
           "--basis", args.basis, "--seed", str(args.seed), "--out", str(out_dir)]
    if args.targeted:
        cmd += ["--targeted", args.targeted]
    else:
        cmd += ["--family", args.family, "--n", str(args.n)]
    if args.oracle == "determinism":
        cmd += ["--repeats", "1"]           # we call twice ourselves for a same-seed compare
    if isolated and args.isolated_pass:
        cmd += ["--isolated-pass", args.isolated_pass]
    if args.oracle in ("contract", "semantic", "global_phase"):
        cmd += ["--capture-layout"]
    env = dict(os.environ); env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True,
                   capture_output=True, timeout=1200)
    return json.loads((out_dir / "worker.json").read_text())


# ------------------------------------------------------------------ oracle verdicts
def load_qpy(path: Path):
    from qiskit import qpy
    with open(path, "rb") as fh:
        return qpy.load(fh)[0]


def reference_signature(py: Path, args, tmp: Path) -> dict:
    """Capture the GOOD build's trigger signature for the chosen oracle."""
    isolated = args.oracle == "contract"
    w = run_trigger(py, tmp / "good", args, isolated=isolated)
    sig = {"status": w.get("status")}
    if args.oracle == "contract":
        sig["property_set"] = w.get("property_set", {})
    elif args.oracle in ("semantic", "global_phase"):
        circ = load_qpy(tmp / "good" / "circuit.qpy")
        from cart.oracles.property_layout import extract_layout_props
        sig["layout_props"] = w.get("layout_props", extract_layout_props(circ))
        sig["global_phase"] = float(circ.global_phase)
        (tmp / "good_circuit.qpy").write_bytes((tmp / "good" / "circuit.qpy").read_bytes())
    return sig


def verdict(py: Path, args, ref: dict, tmp: Path, probe_dir: Path) -> str:
    """Return 'good' | 'bad' | 'skip' for the current probe revision."""
    from cart.oracles.property_layout import compare_layout_props
    try:
        if args.oracle == "determinism":
            r1 = run_trigger(py, probe_dir / "r1", args, isolated=False)
            r2 = run_trigger(py, probe_dir / "r2", args, isolated=False)
            if "error" in (r1.get("status"), r2.get("status")):
                return "skip"
            from cart.labels.historical_runner import _circuit_fingerprint
            o1 = load_qpy(probe_dir / "r1" / "circuit.qpy")
            o2 = load_qpy(probe_dir / "r2" / "circuit.qpy")
            return "good" if _circuit_fingerprint(o1) == _circuit_fingerprint(o2) else "bad"

        isolated = args.oracle == "contract"
        w = run_trigger(py, probe_dir, args, isolated=isolated)
        if w.get("status") == "error":
            # asymmetric error vs a good reference counts as a divergence (bad); build-time
            # incompatibilities are rarer here since we already built successfully.
            return "bad" if ref.get("status") == "ok" else "skip"

        if args.oracle == "contract":
            res = compare_layout_props(ref.get("property_set", {}), w.get("property_set", {}))
            return "bad" if res.equivalent is False else "good"

        # semantic / global_phase: compare against the good reference circuit
        cand = load_qpy(probe_dir / "circuit.qpy")
        if args.oracle == "global_phase":
            gp_ref = float(ref.get("global_phase", 0.0))
            d = abs((float(cand.global_phase) - gp_ref + math.pi) % (2 * math.pi) - math.pi)
            return "bad" if d > 1e-9 else "good"
        # semantic: layout-aware equivalence to the good reference output
        from cart.oracles.semantic import check_semantic
        from cart.manifest.backends import coupling_map_for
        good_circ = load_qpy(tmp / "good_circuit.qpy")
        cmap = None if args.backend == "none" else coupling_map_for(args.backend, good_circ.num_qubits)
        sem = check_semantic(good_circ, cand, coupling_map=cmap, basis_gates=args.basis.split(","))
        return "good" if sem.equivalent else "bad"
    except subprocess.CalledProcessError:
        return "skip"


# ------------------------------------------------------------------ search outcome
def classify_search(found_bad: bool, verdicts: list[str]) -> tuple[str, int]:
    """Decide the search outcome from the probe verdicts; returns (status, exit_code).

    A search that never observed a ``bad`` probe did NOT locate an introducing commit: it is
    inconclusive and MUST exit non-zero (never echo the input ``--bad`` endpoint as the answer, the
    silent failure this replaces). ``skip``-only means every probe was a build failure (no information,
    e.g. #14603); all-``good`` means the regression is not in the range under this oracle (e.g. #16215)."""
    if found_bad:
        return "converged", 0
    if verdicts and all(v == "skip" for v in verdicts):
        return "inconclusive_all_skip", 4
    return "inconclusive_no_bad", 4


# ------------------------------------------------------------------ driver
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Automated regression bisection (build-cached).")
    p.add_argument("--good", required=True, help="known-GOOD ref (tag or sha)")
    p.add_argument("--bad", required=True, help="known-BAD ref (buggy commit, e.g. fix^)")
    p.add_argument("--oracle", required=True,
                   choices=["semantic", "contract", "determinism", "global_phase"])
    p.add_argument("--isolated-pass", default=None, help="pass name for --oracle contract")
    # trigger spec
    p.add_argument("--targeted", default=None, help="targeted-trigger unit id (cart.manifest.targeted)")
    p.add_argument("--family", default="qft")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--backend", default="none")
    p.add_argument("--opt", type=int, default=3)
    p.add_argument("--basis", default="cx,rz,sx,x")
    p.add_argument("--seed", type=int, default=1234)
    # provenance
    p.add_argument("--pr", default="unknown")
    p.add_argument("--reference", default="")
    p.add_argument("--max-skip", type=int, default=6, help="give up after this many consecutive skips")
    args = p.parse_args(argv)

    if args.oracle == "contract" and not args.isolated_pass:
        raise SystemExit("--oracle contract requires --isolated-pass <PassName>")

    repo = ensure_clone()
    good_sha, bad_sha = resolve(repo, args.good), resolve(repo, args.bad)
    commits = first_parent_range(repo, good_sha, bad_sha)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_root = _REPO_ROOT / "results" / f"bisect-{args.pr}-{ts}"
    out_root.mkdir(parents=True, exist_ok=True)
    trace = {"pr": args.pr, "good": good_sha, "bad": bad_sha, "oracle": args.oracle,
             "n_candidates": len(commits), "probes": []}
    print(f">> {len(commits)} commits in ({good_sha[:12]} .. {bad_sha[:12]}]; "
          f"~{max(1, math.ceil(math.log2(len(commits) + 1)))} builds expected")

    if not commits:
        print("!! empty range — check --good/--bad ordering (good must be an ancestor of bad).")
        return 2

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        good_py = build_rev(good_sha)
        if not good_py:
            raise SystemExit("could not build the GOOD revision; cannot capture a reference.")
        ref = reference_signature(good_py, args, tmp)
        print(f">> good reference captured (status={ref.get('status')})")
        if args.oracle in ("contract", "semantic", "global_phase") and ref.get("status") != "ok":
            hint = ("For --oracle contract the fault typically shows as the isolated pass ERRORING on\n"
                    "buggy builds while running clean on good ones. Your --good already errors, so it is\n"
                    "inside the buggy region: choose an OLDER --good where the isolated pass runs clean,\n"
                    "or use scripts/find_introducing_commit.py (git pickaxe) for this event."
                    if args.oracle == "contract"
                    else "Pick a --good revision where the trigger transpiles cleanly.")
            raise SystemExit(
                f"GOOD reference {good_sha[:12]} is NOT clean under --oracle {args.oracle} "
                f"(status={ref.get('status')}). A bisection needs a clean good anchor.\n" + hint)

        # invariant: commits[lo-1] is good, commits[hi] is bad. find first bad in [0, len).
        lo, hi = 0, len(commits) - 1
        first_bad = bad_sha
        found_bad = False          # only a real 'bad' probe locates an introducing commit
        while lo <= hi:
            mid = (lo + hi) // 2
            sha = commits[mid]
            # skip-walk if a build fails
            v, skips, m = "skip", 0, mid
            while v == "skip" and skips < args.max_skip and lo <= m <= hi:
                py = build_rev(commits[m])
                v = verdict(py, args, ref, tmp, out_root / commits[m][:12]) if py else "skip"
                trace["probes"].append({"sha": commits[m], "verdict": v})
                print(f"   probe {commits[m][:12]} -> {v}")
                if v == "skip":
                    m += 1; skips += 1
            if v == "skip":
                print("!! too many consecutive build skips; stopping.")
                break
            if v == "bad":
                first_bad = commits[m]; hi = m - 1; found_bad = True
            else:  # good
                lo = m + 1

        verdicts = [pp["verdict"] for pp in trace["probes"]]
        status, exit_code = classify_search(found_bad, verdicts)
        trace["status"] = status
        trace["verdict_counts"] = {v: verdicts.count(v) for v in ("good", "bad", "skip")}
        trace["introducing_commit"] = first_bad if status == "converged" else None
        (out_root / "bisect_trace.json").write_text(json.dumps(trace, indent=2))

        if status != "converged":
            print("\n================ INCONCLUSIVE ================")
            if status == "inconclusive_all_skip":
                print("no bad probe found — every probe was a build failure (skip). The search produced no "
                      "information (this is what happened for #14603). Fix the builds (era/toolchain), or use "
                      "scripts/find_introducing_commit.py (git pickaxe).")
            else:
                print(f"no bad probe found — search inconclusive. The regression is not in "
                      f"({good_sha[:12]}..{bad_sha[:12]}] under --oracle {args.oracle}, or the good anchor is "
                      f"already bad. Do NOT treat --bad ({bad_sha[:12]}) as the introducing commit.")
            print(f"trace: {out_root / 'bisect_trace.json'}")
            return exit_code

        short = first_bad[:12]
        print("\n================ RESULT ================")
        print(f"introducing commit (first BAD): {first_bad}")
        print(f"trace: {out_root / 'bisect_trace.json'}")
        print("\nRegister the forward-regression event:")
        print(f'  python scripts/add_forward_event.py --event-id fwd-pr{args.pr} '
              f'--env-id fwd-pr{args.pr} --fault-type semantic --pr {args.pr} '
              f'--reference "{args.reference}" --introducing-sha {short}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

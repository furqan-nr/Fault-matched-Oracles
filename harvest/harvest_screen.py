#!/usr/bin/env python3
"""Paper 1B 'harvest' population screen (Protocol 1B-H v1). MECHANICAL: reads commit metadata and
changed-file NAMES only; it never opens a diff or a PR page.

  python harvest_screen.py --repo <bare-or-normal Qiskit clone> --out harvest_population_frozen.csv
Rules are frozen in PROTOCOL_1B_HARVEST.md; change them only by issuing a new protocol version.
"""
import argparse, csv, hashlib, re, subprocess, sys

START, END = "2025-06-18", "2026-10-08"   # Qiskit 2.1.0 release date (start of the study window, band 2.1 to latest) -> main as of 2026-10-08
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
S1_RE = re.compile(r"^\s*(\[[^\]]*\]\s*)?fix", re.I)                      # subject starts with 'fix'
TRANSPILER_PATHS = ("qiskit/transpiler/", "crates/accelerate/", "crates/transpiler/")
TEST_PREFIX = "test/"
# S5: keyword rule on ADDED LINES of changed test files (mechanical grep; no human reads the diff)
S5_RE = re.compile(r"global_phase|final_layout|initial_layout|final_index_layout|initial_index_layout|virtual_permutation|routing_permutation|structurally_equal|non-?determin|determinis|PYTHONHASHSEED", re.I)
S4_RE = re.compile(r"layout|permut|rout(e|ing)|swap|phase|determinis|non-?determin|ordering|reproducib|\bseed|virtual", re.I)


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--branch", default="main")
    ap.add_argument("--start", default=START); ap.add_argument("--end", default=END)
    ap.add_argument("--exclude", default="exclusion_1A_union.csv"); ap.add_argument("--out", default="harvest_population_frozen.csv")
    a = ap.parse_args()
    excl = {int(r["pr"]): r["found_in"] for r in csv.DictReader(open(a.exclude))}
    raw = git(a.repo, "log", a.branch, "--first-parent", f"--since={a.start} 00:00", f"--until={a.end} 23:59",
              "--name-only", "--format=%x1e%H|%cs|%s")
    rows, funnel = [], dict(commits=0, has_pr=0, backport=0, in_1A=0, S1=0, S2=0, S3=0, S4=0)
    for blk in raw.split("\x1e")[1:]:
        head, *files = blk.strip("\n").split("\n")
        files = [f for f in files if f.strip()]
        sha, date, subj = head.split("|", 2)
        funnel["commits"] += 1
        m = PR_RE.search(subj)
        if not m: continue
        funnel["has_pr"] += 1
        pr = int(m.group(1))
        if re.search(r"backport", subj, re.I): funnel["backport"] += 1; continue
        if pr in excl: funnel["in_1A"] += 1; continue
        s1 = bool(S1_RE.search(subj)); s2 = any(f.startswith(TRANSPILER_PATHS) for f in files)
        s3 = any(f.startswith(TEST_PREFIX) for f in files); s4 = bool(S4_RE.search(subj))
        if not s1: continue
        funnel["S1"] += 1
        if not s2: continue
        funnel["S2"] += 1
        if not s3: continue
        funnel["S3"] += 1
        if s4: funnel["S4"] += 1
        added = git(a.repo, "show", "--format=", "-U0", sha, "--", TEST_PREFIX)
        s5 = bool(S5_RE.search("\n".join(l for l in added.split("\n") if l.startswith("+") and not l.startswith("+++"))))
        if s5: funnel["S5"] = funnel.get("S5", 0) + 1
        rows.append(dict(pr=pr, sha=sha, date=date, subject=subj, n_files=len(files),
                         transpiler_files=sum(f.startswith(TRANSPILER_PATHS) for f in files),
                         test_files=sum(f.startswith(TEST_PREFIX) for f in files), S4_subject_kw=int(s4), S5_test_kw=int(s5),
                         role="1B-harvest" if (s4 or s5) else "screened-out"))
    rows.sort(key=lambda r: r["pr"])
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
    print("funnel:", funnel); print("sha256(", a.out, ")=", h)
    open(a.out + ".sha256", "w").write(h + "  " + a.out + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Draw Figures 1 and 2 of the Scientific Reports manuscript (added in v1.2.1).

Figure 1 is a three-stage overview. Its schematic parts are drawn with vector primitives (no image files). Its two small
data panels are computed from saved evidence: the phase-estimation distributions from the injected offsets in
results/consequence_demo.json (the closed-form distribution of a six-counting-qubit phase-estimation register) and the
readout count from the same file.
Figure 2 reads the measured cost from results/cost_scaling_eval.json (GHZ circuits, median CPU time per call).
Absolute milliseconds are machine dependent. The ordering and the exact-tier boundary (n <= 12) are the claim.

Run from the repository root:  python scripts/make_figures.py   (needs numpy and matplotlib)
Writes figures/fig1_channels and figures/fig2_cost as PNG (300 dpi) and vector PDF.
"""
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm, LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon, Circle, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "figures")
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Liberation Sans", "Helvetica", "DejaVu Sans"],
    "mathtext.fontset": "custom", "mathtext.rm": "sans", "mathtext.it": "sans:italic", "mathtext.bf": "sans:bold", "mathtext.cal": "sans:italic",
    "axes.linewidth": 0.7, "savefig.facecolor": "white", "pdf.fonttype": 42, "svg.fonttype": "none",
})

# One colour per property, reused in every panel (muted, distinguishable without colour via the labels and glyphs).
C_OUT = "#6f8fb3"      # compiled circuit / output
C_LAY = "#8b6fb3"      # layout record
C_PHA = "#d98a2b"      # global phase
C_RUN = "#3f9a8b"      # reproducibility
GOOD, BAD, WARN = "#2e8b57", "#c0392b", "#d98a2b"
PANEL_FILL, PANEL_EDGE = "#f4f1ea", "#7d7d7d"
INK = "#222222"


def light(c, f=0.82):
    c = np.array(matplotlib.colors.to_rgb(c))
    return tuple(c + (1 - c) * f)


# ------------------------------------------------------------------ drawing helpers (canvas units, y up)
def rbox(ax, x, y, w, h, fc="white", ec="#555", lw=0.8, ls="-", r=1.1, z=2):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)
    ax.add_patch(p)
    return p


def panel(ax, x, y, w, h, title, tag):
    rbox(ax, x, y, w, h, fc=PANEL_FILL, ec=PANEL_EDGE, lw=0.9, ls=(0, (4, 2.5)), r=2.2, z=0)
    ax.text(x + 1.6, y + h - 1.9, tag, fontsize=7.4, fontweight="bold", color="white", ha="center", va="center", zorder=4,
            bbox=dict(boxstyle="circle,pad=0.28", fc="#444", ec="none"))
    ax.text(x + 3.6, y + h - 1.9, title, fontsize=8.2, fontweight="bold", color=INK, ha="left", va="center", zorder=4)


def arrow(ax, p, q, c="#555", lw=1.0, ls="-", ms=8, rad=0.0, z=3):
    a = FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=ms, lw=lw, color=c, ls=ls, zorder=z,
                        connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0)
    ax.add_patch(a)


def check(ax, cx, cy, s=1.5, c=GOOD):
    ax.add_patch(Circle((cx, cy), s, fc=c, ec="none", zorder=5))
    ax.plot([cx - 0.55 * s, cx - 0.1 * s, cx + 0.6 * s], [cy + 0.05 * s, cy - 0.45 * s, cy + 0.5 * s], c="white", lw=1.5,
            solid_capstyle="round", zorder=6)


def cross(ax, cx, cy, s=1.5, c=BAD):
    ax.add_patch(Circle((cx, cy), s, fc=c, ec="none", zorder=5))
    d = 0.5 * s
    ax.plot([cx - d, cx + d], [cy - d, cy + d], c="white", lw=1.5, solid_capstyle="round", zorder=6)
    ax.plot([cx - d, cx + d], [cy + d, cy - d], c="white", lw=1.5, solid_capstyle="round", zorder=6)


def doc_icon(ax, x, y, w=6.0, h=8.0, c=C_OUT):
    f = 2.0
    pts = [(x, y), (x + w, y), (x + w, y + h - f), (x + w - f, y + h), (x, y + h)]
    ax.add_patch(Polygon(pts, closed=True, fc="white", ec=c, lw=1.1, zorder=3))
    ax.add_patch(Polygon([(x + w - f, y + h), (x + w - f, y + h - f), (x + w, y + h - f)], closed=True, fc=light(c, 0.55), ec=c, lw=0.8, zorder=4))
    for i in range(3):
        ax.plot([x + 1.0, x + w - 1.2], [y + 1.6 + i * 1.6, y + 1.6 + i * 1.6], c=c, lw=0.8, zorder=4)


def gear_icon(ax, cx, cy, r=4.0, c="#5a7d5a", teeth=8):
    ro, ri = r, 0.78 * r
    pts = []
    for k in range(teeth):
        a0 = 2 * math.pi * k / teeth
        for da, rr in ((-0.20, ri), (-0.12, ro), (0.12, ro), (0.20, ri)):
            a = a0 + da * 2 * math.pi / teeth * 1.9
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    ax.add_patch(Polygon(pts, closed=True, fc=light(c, 0.6), ec=c, lw=1.1, zorder=3))
    ax.add_patch(Circle((cx, cy), 0.38 * r, fc="white", ec=c, lw=1.1, zorder=4))


def txt(ax, x, y, s, fs=7.0, ha="left", va="center", c=INK, w="normal", st="normal", z=6, **kw):
    return ax.text(x, y, s, fontsize=fs, ha=ha, va=va, color=c, fontweight=w, fontstyle=st, zorder=z, **kw)


# ------------------------------------------------------------------ data helpers
def qpe_distribution(delta, t=6):
    """Outcome distribution of a t-counting-qubit phase-estimation register for the continuous phase 0.25 + delta/2pi."""
    n = 2 ** t
    phi = 0.25 + delta / (2 * math.pi)
    j = np.arange(n)
    return np.array([abs(np.sum(np.exp(2j * np.pi * (phi - k / n) * j)) / n) ** 2 for k in range(n)])


# ================================================================== FIGURE 1
def figure1():
    cons = json.load(open(os.path.join(REPO, "results", "consequence_demo.json")))
    pe = {r["case"].split(" (")[0]: r for r in cons["phase_estimation"]}
    ro = cons["readout"]
    W, H = 100.0, 106.0
    fig = plt.figure(figsize=(7.2, 7.2 * H / W), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # ---------------- Stage 1: a compilation run
    panel(ax, 0.8, 86.6, 98.4, 18.6, "A transpilation returns more than a circuit", "1")
    txt(ax, 98.0, 103.3, "$C(P,\\theta,s)=(P',L,\\varphi)$", fs=7.4, ha="right", c="#333", z=6)
    yc = 94.4
    doc_icon(ax, 5.0, yc - 4.0, c=C_OUT)
    txt(ax, 8.0, yc - 6.4, "Input circuit  $P$", fs=7.0, ha="center")
    rbox(ax, 14.0, yc - 4.1, 14.5, 8.2, fc="white", ec="#888", lw=0.7, ls=(0, (3, 2)))
    txt(ax, 21.25, yc + 1.5, "configuration  $\\theta$", fs=6.6, ha="center")
    txt(ax, 21.25, yc - 1.5, "seed  $s$", fs=6.6, ha="center")
    arrow(ax, (11.6, yc), (13.8, yc), ls=(0, (3, 2)), ms=6)
    arrow(ax, (28.8, yc), (35.0, yc), c="#555", lw=1.4, ms=9)
    gear_icon(ax, 41.0, yc, r=4.0)
    txt(ax, 41.0, yc - 6.4, "Transpiler", fs=7.0, ha="center", w="bold")
    arrow(ax, (45.6, yc), (48.4, yc), c="#555", lw=1.4, ms=8)
    rbox(ax, 48.4, yc - 6.0, 49.0, 12.0, fc="white", ec="#888", lw=0.7, ls=(0, (3, 2)), r=1.6, z=1)
    items = [("Compiled circuit  $P'$", "what executes", C_OUT), ("Layout record  $L$", "initial and final layout, routing permutation", C_LAY),
             ("Global phase  $\\varphi$", "stored scalar of the compiled operator", C_PHA), ("Repeated runs", "same library, circuit, seed", C_RUN)]
    xs, ys = [49.6, 49.6, 74.6, 74.6], [yc + 2.9, yc - 2.9, yc + 2.9, yc - 2.9]
    for (a_, b_, c), x, y in zip(items, xs, ys):
        rbox(ax, x, y - 2.4, 22.6, 4.8, fc=light(c, 0.78), ec=c, lw=0.9)
        txt(ax, x + 1.0, y + 0.85, a_, fs=6.7, w="bold")
        txt(ax, x + 1.0, y - 1.15, b_, fs=5.5, c="#444")
    arrow(ax, (50, 86.3), (50, 83.9), c=WARN, lw=2.6, ms=10)

    # ---------------- Stage 2: what each oracle can observe
    panel(ax, 0.8, 38.6, 98.4, 45.0, "What each oracle can observe", "2")
    cx = [3.2, 33.0, 66.0]; cw = [27.0, 30.0, 31.0]
    for x, w, s_ in zip(cx, cw, ["Property", "Output-equivalence oracle", "Matched oracle (this work)"]):
        txt(ax, x + w / 2, 77.2, s_, fs=7.2, w="bold", ha="center")
    ax.plot([3.2, 97.0], [75.2, 75.2], c="#888", lw=0.6, zorder=3)
    rows = [("Compiled circuit  $P'$", C_OUT, "ok", "compares operator, state or\ndistribution with the input", None, ""),
            ("Layout record  $L$", C_LAY, "blind", "may miss it: invisible if the\noperator does not depend on it", "match", "Contract checker (K0\u2013K2)\nMR-1 permutation consistency"),
            ("Global phase  $\\varphi$", C_PHA, "blind", "cannot observe: global phase is\nnormalized away by definition", "match", "Global-phase tracker\n(exact $n\\leq12$, sampled 13\u201322)"),
            ("Repeated runs", C_RUN, "blind", "cannot observe: judges each run\non its own", "match", "Determinism runner\n(raw and functional fingerprints)")]
    y0, dy = 70.0, 8.2
    for i, (a_, c, v, vt, m, mt) in enumerate(rows):
        y = y0 - i * dy
        rbox(ax, cx[0], y - 3.3, cw[0], 6.6, fc=light(c, 0.78), ec=c, lw=0.9)
        txt(ax, cx[0] + cw[0] / 2, y, a_, fs=7.0, w="bold", ha="center")
        rbox(ax, cx[1], y - 3.3, cw[1], 6.6, fc="white", ec=(GOOD if v == "ok" else BAD), lw=0.9, ls=("-" if v == "ok" else (0, (3, 2))))
        (check if v == "ok" else cross)(ax, cx[1] + 2.5, y, 1.35, GOOD if v == "ok" else BAD)
        txt(ax, cx[1] + 5.0, y, vt, fs=5.8, linespacing=1.15)
        if m:
            rbox(ax, cx[2], y - 3.3, cw[2], 6.6, fc="white", ec=GOOD, lw=1.2)
            check(ax, cx[2] + 2.5, y, 1.35, GOOD)
            txt(ax, cx[2] + 5.0, y, mt, fs=5.9, linespacing=1.15)
        else:
            rbox(ax, cx[2], y - 3.3, cw[2], 6.6, fc="#fafafa", ec="#bbb", lw=0.7, ls=(0, (2, 2)))
            txt(ax, cx[2] + cw[2] / 2, y, "output faults are the scope of the\noutput oracle", fs=5.8, ha="center", c="#666", linespacing=1.15)
        arrow(ax, (cx[0] + cw[0] + 0.1, y), (cx[1] - 0.1, y), c=c, lw=0.9, ms=6, ls=(0, (3, 2)))
        arrow(ax, (cx[1] + cw[1] + 0.1, y), (cx[2] - 0.1, y), c="#777", lw=0.9, ms=6, ls=(0, (3, 2)))

    arrow(ax, (50, 38.2), (50, 34.8), c=WARN, lw=2.6, ms=11)

    # ---------------- Stage 3: consequences
    panel(ax, 0.8, 0.8, 98.4, 33.4, "Consequence for a quantum computation when the property is corrupted", "3")
    sx = [2.6, 35.0, 67.4]; sw = 30.0; sy, sh = 2.2, 26.8
    heads = [("Layout record (readout test)", C_LAY), ("Global phase (phase estimation)", C_PHA), ("Reproducibility (schematic)", C_RUN)]
    for x, (h, c) in zip(sx, heads):
        rbox(ax, x, sy, sw, sh, fc="white", ec=c, lw=1.0)
        txt(ax, x + sw / 2, sy + sh - 2.0, h, fs=7.3, w="bold", ha="center", c=INK)
        ax.plot([x + 1.0, x + sw - 1.0], [sy + sh - 3.9, sy + sh - 3.9], c=light(c, 0.4), lw=0.8, zorder=3)

    # (i) layout: record decoded through a transposed permutation
    x = sx[0]
    txt(ax, x + sw / 2, sy + sh - 6.0, "measured bit \u2192 logical qubit", fs=5.8, ha="center", c="#444")
    bits = [1, 0, 1, 1, 0]
    top = sy + sh - 8.2
    step = 2.45
    for i, b_ in enumerate(bits):
        yy = top - i * step
        ax.add_patch(Rectangle((x + 4.0, yy - 1.1), 3.6, 2.2, fc=light(C_LAY, 0.7), ec=C_LAY, lw=0.8, zorder=3))
        txt(ax, x + 5.8, yy, str(b_), fs=6.3, ha="center", w="bold")
        txt(ax, x + 2.6, yy, f"p{i}", fs=5.6, ha="center", c="#444")
        ax.add_patch(Rectangle((x + sw - 8.0, yy - 1.1), 3.6, 2.2, fc="white", ec="#555", lw=0.8, zorder=3))
        txt(ax, x + sw - 6.2, yy, f"q{i}", fs=5.8, ha="center")
    for i in range(len(bits)):
        yy = top - i * step
        if i in (1, 2):
            continue
        ax.plot([x + 7.8, x + sw - 8.2], [yy, yy], c=GOOD, lw=1.0, zorder=2)
    y1, y2 = top - 1 * step, top - 2 * step
    ax.plot([x + 7.8, x + sw - 8.2], [y1, y2], c=BAD, lw=1.2, ls=(0, (3, 1.6)), zorder=3)
    ax.plot([x + 7.8, x + sw - 8.2], [y2, y1], c=BAD, lw=1.2, ls=(0, (3, 1.6)), zorder=3)
    txt(ax, x + sw / 2, sy + 6.2, "transposing two entries still gives a valid", fs=5.7, ha="center", c="#333")
    txt(ax, x + sw / 2, sy + 4.4, "permutation; circuit and outcome unchanged", fs=5.7, ha="center", c="#333")
    txt(ax, x + sw / 2, sy + 1.9, f"{ro['corrupted_record_wrong']} of {ro['trials']} random circuits decoded wrongly", fs=6.2, ha="center", w="bold", c=BAD)

    # (ii) global phase: phase-estimation distributions (inset axes)
    x = sx[1]
    ia = fig.add_axes([(x + 5.2) / W, (sy + 10.6) / H, (sw - 7.4) / W, 9.0 / H])
    ks = np.arange(10, 27)
    d0, d1, d2 = (qpe_distribution(pe[k]["delta"]) for k in ("correct", "offset 0.3 rad", "offset pi/7 rad"))
    for key, dd in (("offset 0.3 rad", d1), ("offset pi/7 rad", d2)):
        r_ = pe[key]
        assert abs(dd[r_["modal_outcome_index"]] - r_["P_modal_outcome"]) < 1e-6, key
        assert abs(dd[r_["second_outcome_index"]] - r_["P_second_outcome"]) < 1e-6, key
        assert abs(dd[pe["correct"]["modal_outcome_index"]] - r_["P_true_outcome"]) < 1e-6, key  # P of the unperturbed outcome 16/64
    ia.bar(ks - 0.28, d0[ks], 0.28, color="#8a8a8a", label="correct", lw=0)
    ia.bar(ks, d1[ks], 0.28, color=C_PHA, label="0.3 rad", lw=0)
    ia.bar(ks + 0.28, d2[ks], 0.28, color="#4c78a8", label="$\\pi/7$ rad", lw=0)
    ia.set_xlim(9.2, 26.8); ia.set_ylim(0, 1.08)
    ia.set_xticks([16, 20, 24]); ia.set_xticklabels(["16/64", "20/64", "24/64"], fontsize=5.4)
    ia.set_yticks([0, 0.5, 1]); ia.set_yticklabels(["0", ".5", "1"], fontsize=5.4)
    ia.tick_params(length=1.8, width=0.5, pad=1.0)
    for s_ in ("top", "right"):
        ia.spines[s_].set_visible(False)
    ia.patch.set_alpha(0)
    ia.legend(fontsize=5.3, frameon=False, loc="upper right", handlelength=0.9, borderpad=0.1, labelspacing=0.2, bbox_to_anchor=(1.05, 1.05))
    txt(ax, x + sw / 2, sy + sh - 6.0, "counting-register outcome (6 qubits, k/64)", fs=5.8, ha="center", c="#444")
    txt(ax, x + sw / 2, sy + 6.3, "output equivalence still passes", fs=5.7, ha="center", c="#333")
    p03, p7 = pe["offset 0.3 rad"]["P_true_outcome"], pe["offset pi/7 rad"]["P_true_outcome"]
    txt(ax, x + sw / 2, sy + 4.1, f"P(true outcome) 1.00 \u2192 {p03*1e4:.1f}\u00D710$^{{-4}}$ (0.3 rad)", fs=5.8, ha="center", w="bold", c=BAD)
    txt(ax, x + sw / 2, sy + 2.0, f"and {p7*1e3:.1f}\u00D710$^{{-3}}$ ($\\pi/7$ rad)", fs=5.8, ha="center", w="bold", c=BAD)

    # (iii) reproducibility: three runs, same seed
    x = sx[2]
    txt(ax, x + sw / 2, sy + sh - 6.0, "same circuit, library and seed", fs=5.8, ha="center", c="#444")
    cols = ["#6f8fb3", "#d98a2b", "#8b6fb3", "#3f9a8b"]
    orders = [[0, 1, 2, 3], [0, 1, 3, 2], [0, 1, 2, 3]]
    for r, od in enumerate(orders):
        yy = sy + sh - 9.6 - r * 3.7
        txt(ax, x + 2.2, yy, f"run {r + 1}", fs=5.8, c="#444")
        for k, g in enumerate(od):
            ax.add_patch(Rectangle((x + 8.0 + k * 4.0, yy - 1.4), 3.4, 2.8, fc=cols[g], ec="white", lw=0.5, zorder=3))
        if od != orders[0]:
            ax.add_patch(Rectangle((x + 8.0 + 2 * 4.0 - 0.3, yy - 1.8), 7.8 + 0.2, 3.6, fc="none", ec=BAD, lw=1.0, ls=(0, (2, 1.4)), zorder=4))
            txt(ax, x + 24.7, yy, "differs", fs=5.4, ha="left", c=BAD, st="italic")
    txt(ax, x + sw / 2, sy + 6.2, "two commuting instructions swap order,", fs=5.7, ha="center", c="#333")
    txt(ax, x + sw / 2, sy + 4.4, "the executed output is identical", fs=5.7, ha="center", c="#333")
    txt(ax, x + sw / 2, sy + 1.9, "replication and debugging suffer", fs=6.2, ha="center", w="bold", c=BAD)

    fig.savefig(os.path.join(OUT, "fig1_channels.png"), bbox_inches=None)
    fig.savefig(os.path.join(OUT, "fig1_channels.pdf"), bbox_inches=None)
    plt.close(fig)


# ================================================================== FIGURE 2
def figure2():
    rows = json.load(open(os.path.join(REPO, "results", "cost_scaling_eval.json")))["rows"]
    n = [r["n_qubits"] for r in rows]
    sem = np.array([r["semantic_ms"] for r in rows])
    con = np.array([r["contract_ms"] for r in rows])
    ph = np.array([r["global_phase_ms"] for r in rows])
    ex = [r for r in rows if r["exact_tier"]]
    mr1 = np.array([r["mr1_ms"] for r in ex])
    ne = len(ex)

    fig = plt.figure(figsize=(7.2, 3.9), dpi=300)
    a = fig.add_axes([0.075, 0.30, 0.50, 0.62])
    b = fig.add_axes([0.775, 0.40, 0.21, 0.40])

    # (a) cost against width
    a.axvspan(3.3, 12.7, color="#e9eff6", zorder=0)
    a.axvspan(12.7, 21.7, color=PANEL_FILL, zorder=0)
    a.text(8, 2.0e5, "exact tier  ($n\\leq12$)", ha="center", va="top", fontsize=7, color="#33475b", fontweight="bold")
    a.text(8, 5.5e4, "like-for-like comparison", ha="center", va="top", fontsize=6.2, color="#33475b", style="italic")
    a.text(17.2, 2.0e5, "sampled tier  ($n>12$)", ha="center", va="top", fontsize=7, color="#555", fontweight="bold")
    a.text(17.2, 5.5e4, "no like-for-like baseline", ha="center", va="top", fontsize=6.2, color="#555", style="italic")
    a.plot(n[:ne], sem[:ne], "-o", color="#b04a4a", lw=1.5, ms=4.2, label="check_semantic (exact operator)", zorder=4)
    a.plot(n[ne:], sem[ne:], "o", color="#b04a4a", mfc="white", ms=4.8, ls="none", label="check_semantic, structural stand-in", zorder=4)
    a.plot(n, con, "-s", color=GOOD, lw=1.5, ms=4.0, label="contract checker", zorder=4)
    a.plot(n[:ne], mr1, "-^", color="#7a58a8", lw=1.5, ms=4.4, label="MR-1 (assessable for $n\\leq12$)", zorder=4)
    a.plot(n[:ne], ph[:ne], "-D", color=C_PHA, lw=1.5, ms=3.8, label="global-phase tracker, exact", zorder=4)
    a.plot(n[ne:], ph[ne:], "--D", color=C_PHA, lw=1.1, ms=3.8, mfc="white", label="global-phase tracker, sampled ($k=5$)", zorder=3)
    a.set_yscale("log"); a.set_xlim(3.3, 21.7); a.set_ylim(2e-3, 3e5); a.set_xticks(n)
    a.set_xlabel("circuit width $n$ (qubits, GHZ circuits)", fontsize=7.4)
    a.set_ylabel("median CPU time per call (ms)", fontsize=7.4)
    a.tick_params(labelsize=6.8, width=0.6, length=2.5)
    a.grid(True, which="major", ls=":", lw=0.5, alpha=0.8, zorder=1)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)
    a.legend(fontsize=6.2, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False, columnspacing=1.4, handlelength=2.0)
    fig.text(0.012, 0.955, "a", fontsize=11, fontweight="bold")

    # (b) cost relative to output checking, exact tier only (heat map with printed values)
    names = ["contract checker", "global-phase tracker", "MR-1"]
    ratio = np.array([con[:ne] / sem[:ne], ph[:ne] / sem[:ne], mr1 / sem[:ne]])
    cmap = LinearSegmentedColormap.from_list("rel", [(0, "#2f6aa6"), (0.55, "#9db9d6"), (0.856, "#f4f1ea"), (1.0, "#d9822b")])
    im = b.imshow(ratio, cmap=cmap, norm=LogNorm(vmin=1e-7, vmax=1.5e1), aspect="auto")
    b.set_xticks(range(ne)); b.set_xticklabels([f"$n={r['n_qubits']}$" for r in ex], fontsize=6.8)
    b.xaxis.tick_top()
    b.set_yticks(range(3)); b.set_yticklabels(names, fontsize=6.8)
    b.tick_params(length=0, pad=3)
    for i in range(3):
        for j in range(ne):
            v = ratio[i, j]
            if v >= 0.1:
                s_ = f"{v:.2f}$\\times$"
            else:
                m, e = f"{v:.1e}".split("e")
                s_ = f"{float(m):.1f}$\\times10^{{{int(e)}}}$"
            dark = v < 1e-3
            b.text(j, i, s_, ha="center", va="center", fontsize=5.6, color="white" if dark else INK, fontweight="bold")
    for sp in b.spines.values():
        sp.set_visible(False)
    b.set_xticks(np.arange(-.5, ne, 1), minor=True); b.set_yticks(np.arange(-.5, 3, 1), minor=True)
    b.grid(which="minor", color="white", lw=2.0); b.tick_params(which="minor", length=0)
    fig.text(0.775 + 0.105, 0.935, "cost relative to output checking", fontsize=7.2, ha="center", va="center")
    fig.text(0.775 + 0.105, 0.895, "(exact tier; check_semantic = 1$\\times$)", fontsize=6.2, ha="center", va="center", color="#444")
    cax = fig.add_axes([0.775, 0.31, 0.21, 0.022])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_ticks([1e-7, 1e-5, 1e-3, 1, 10]); cb.ax.set_xticklabels(["$10^{-7}$", "$10^{-5}$", "$10^{-3}$", "1", "10"], fontsize=5.8)
    cb.outline.set_linewidth(0.5); cb.ax.tick_params(length=2, width=0.5)
    cb.minorticks_off()
    cb.set_label("ratio of median CPU time (log scale)", fontsize=6.2, labelpad=2)
    fig.text(0.60, 0.955, "b", fontsize=11, fontweight="bold")

    fig.savefig(os.path.join(OUT, "fig2_cost.png"), bbox_inches=None)
    fig.savefig(os.path.join(OUT, "fig2_cost.pdf"), bbox_inches=None)
    plt.close(fig)


if __name__ == "__main__":
    figure1()
    figure2()
    print("wrote PNG (300 dpi) and PDF (vector) versions of fig1_channels and fig2_cost in", OUT)

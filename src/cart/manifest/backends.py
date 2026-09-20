"""Backend (coupling-map) specifications for the manifest.

Built from CouplingMap factory methods to avoid heavy provider dependencies.
Each backend has a stable id and a builder that returns a CouplingMap of >= n qubits.
"""
from __future__ import annotations

from qiskit.transpiler import CouplingMap


def _line(n: int) -> CouplingMap:
    return CouplingMap.from_line(n)


def _ring(n: int) -> CouplingMap:
    return CouplingMap.from_ring(n)


def _grid(n: int) -> CouplingMap:
    # nearest square grid covering >= n qubits
    side = 1
    while side * side < n:
        side += 1
    return CouplingMap.from_grid(side, side)


def _heavy_hex(n: int) -> CouplingMap:
    # distance d must be odd; grow until the heavy-hex lattice covers >= n qubits.
    d = 3
    while True:
        cm = CouplingMap.from_heavy_hex(d)
        if cm.size() >= n:
            return cm
        d += 2


BACKENDS = {
    "line": _line,
    "ring": _ring,
    "grid": _grid,
    "heavy_hex": _heavy_hex,
}


def coupling_map_for(backend_id: str, n: int) -> CouplingMap:
    if backend_id not in BACKENDS:
        raise KeyError(f"unknown backend: {backend_id!r}")
    return BACKENDS[backend_id](n)

"""Deterministic circuit-family generators for the test manifest.

Built manually (not via qiskit.circuit.library) to stay robust across the 2.x band,
where some library constructors have been deprecated/relocated. Each builder is
deterministic given (n_qubits, seed).
"""
from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import random_clifford

CIRCUIT_FAMILIES = ("ghz", "qft", "qaoa_linear", "random_clifford")


def ghz(n: int, *, measured: bool = False, **_: object) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"ghz_{n}")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    if measured:
        qc.measure_all()
    return qc


def qft(n: int, *, measured: bool = False, **_: object) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"qft_{n}")
    for j in range(n):
        qc.h(j)
        for k in range(j + 1, n):
            qc.cp(np.pi / float(2 ** (k - j)), k, j)
    for i in range(n // 2):
        qc.swap(i, n - i - 1)
    if measured:
        qc.measure_all()
    return qc


def qaoa_linear(n: int, *, reps: int = 1, seed: int = 0, measured: bool = False, **_: object) -> QuantumCircuit:
    rng = np.random.default_rng(seed)
    qc = QuantumCircuit(n, name=f"qaoa_linear_{n}")
    qc.h(range(n))
    for _ in range(reps):
        gamma = float(rng.uniform(0, np.pi))
        beta = float(rng.uniform(0, np.pi))
        for i in range(n - 1):  # linear-chain ZZ interactions
            qc.rzz(gamma, i, i + 1)
        for i in range(n):
            qc.rx(2 * beta, i)
    if measured:
        qc.measure_all()
    return qc


def random_clifford_circuit(n: int, *, seed: int = 0, measured: bool = False, **_: object) -> QuantumCircuit:
    cliff = random_clifford(n, seed=seed)
    qc = cliff.to_circuit()
    qc.name = f"random_clifford_{n}"
    if measured:
        qc.measure_all()
    return qc


_BUILDERS = {
    "ghz": ghz,
    "qft": qft,
    "qaoa_linear": qaoa_linear,
    "random_clifford": random_clifford_circuit,
}


def build(family: str, n: int, *, seed: int = 0, measured: bool = False) -> QuantumCircuit:
    if family not in _BUILDERS:
        raise KeyError(f"unknown circuit family: {family!r}")
    return _BUILDERS[family](n, seed=seed, measured=measured)

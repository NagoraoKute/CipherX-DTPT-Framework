"""
oqrng.py — Simulated Optical Quantum Random Number Generator (Phase 2, Step 2.1)

Physical model
--------------
An optical QRNG counts photons from an attenuated laser in a fixed time
window. Photon counts from a coherent source are Poisson distributed, so
every raw sample here comes from `numpy.random.Generator.poisson(lam)`
(the modern Generator API behind `numpy.random.poisson`).

Why raw Poisson counts are NOT used directly as bases
-----------------------------------------------------
A Poisson count taken mod 6 is biased (some Pauli eigenstates would be
chosen more often than others). A biased basis choice leaks information to
a forger and weakens the GC security argument. We therefore run a
deterministic, exactly-unbiased extractor on the Poisson stream:

    1. Draw two independent Poisson counts (a, b).
    2. a < b -> bit 0,  a > b -> bit 1,  a == b -> discard.

Since a and b are i.i.d., P(a < b) == P(a > b) exactly, so each emitted bit
is perfectly unbiased. Uniform integers in [0, n) are then built from k bits
with rejection sampling (values >= n are discarded), which is also exact.

The raw Poisson samples remain available for Test 2.1 and for the
frontend's Poisson-distribution chart.

Note: this is a *simulation* of physical entropy. `numpy`'s generator is
seeded from OS entropy when `seed=None`; pass a seed only for reproducible
demos and tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.stats import poisson

from quantum_engine.teleportation import PauliEigenstate

DEFAULT_MEAN_PHOTON_COUNT: Final[float] = 10.0
PAULI_ALPHABET_SIZE: Final[int] = len(PauliEigenstate)


@dataclass(frozen=True)
class SignatureTokenBatch:
    """Uniformly selected Pauli eigenstates for one signature."""

    token_indices: np.ndarray  # int64 in [0, 6)

    @property
    def eigenstates(self) -> list[PauliEigenstate]:
        members = list(PauliEigenstate)
        return [members[int(i)] for i in self.token_indices]

    @property
    def basis_labels(self) -> list[str]:
        return [token.basis for token in self.eigenstates]

    def __len__(self) -> int:
        return int(self.token_indices.size)


@dataclass(frozen=True)
class PoissonStatistics:
    """Summary used to show the raw OQRNG stream is Poisson, not uniform."""

    sample_count: int
    mean_photon_count: float
    sample_mean: float
    sample_variance: float

    @property
    def dispersion_index(self) -> float:
        """Variance / mean. Equals 1 for a Poisson source (a uniform source would not)."""
        return self.sample_variance / self.sample_mean if self.sample_mean > 0 else float("nan")


class OpticalQRNG:
    """Simulated photon-counting QRNG with an exact unbiased bit extractor."""

    def __init__(self, mean_photon_count: float = DEFAULT_MEAN_PHOTON_COUNT, seed: int | None = None) -> None:
        if not math.isfinite(mean_photon_count) or mean_photon_count <= 0:
            raise ValueError("mean_photon_count (lambda) must be a positive finite number.")
        self.mean_photon_count: float = float(mean_photon_count)
        self._generator: np.random.Generator = np.random.default_rng(seed)
        self.raw_samples_drawn: int = 0

    # -- raw physical layer -------------------------------------------------

    def photon_counts(self, count: int) -> np.ndarray:
        """Raw Poisson photon counts (the simulated detector output)."""
        if count < 0:
            raise ValueError("count must be non-negative.")
        samples = self._generator.poisson(self.mean_photon_count, size=count)
        self.raw_samples_drawn += count
        return samples

    # -- extraction layer ---------------------------------------------------

    def random_bits(self, count: int) -> np.ndarray:
        """Exactly unbiased bits via pairwise comparison of Poisson counts."""
        if count < 0:
            raise ValueError("count must be non-negative.")
        chunks: list[np.ndarray] = []
        collected = 0
        while collected < count:
            needed = count - collected
            pair_count = int(needed * 1.25) + 16      # headroom for discarded ties
            first = self.photon_counts(pair_count)
            second = self.photon_counts(pair_count)
            distinct = first != second
            bits = (first[distinct] > second[distinct]).astype(np.uint8)
            chunks.append(bits)
            collected += bits.size
        return np.concatenate(chunks)[:count] if chunks else np.empty(0, dtype=np.uint8)

    def uniform_integers(self, count: int, upper: int) -> np.ndarray:
        """Exactly uniform integers in [0, upper) via bit-level rejection sampling."""
        if upper < 1:
            raise ValueError("upper must be >= 1.")
        if count < 0:
            raise ValueError("count must be non-negative.")
        if upper == 1:
            return np.zeros(count, dtype=np.int64)

        bits_per_value = (upper - 1).bit_length()
        place_values = 1 << np.arange(bits_per_value - 1, -1, -1, dtype=np.int64)
        acceptance = upper / (1 << bits_per_value)

        chunks: list[np.ndarray] = []
        collected = 0
        while collected < count:
            needed = count - collected
            candidate_count = int(needed / acceptance * 1.1) + 8
            bit_matrix = self.random_bits(candidate_count * bits_per_value).reshape(candidate_count, bits_per_value)
            candidates = bit_matrix.astype(np.int64) @ place_values
            accepted = candidates[candidates < upper]
            chunks.append(accepted)
            collected += accepted.size
        return np.concatenate(chunks)[:count] if chunks else np.empty(0, dtype=np.int64)

    def seeded_generator(self, seed_bits: int = 256) -> np.random.Generator:
        """
        Bulk-randomness generator whose seed is `seed_bits` of OQRNG entropy.

        Used for high-volume optical choices (e.g. modulating ~10^6 decoy
        pulses) where extracting every value from Poisson pairs would stall
        the demo. Pauli basis selection never uses this path.
        """
        if seed_bits < 128 or seed_bits % 32:
            raise ValueError("seed_bits must be a multiple of 32 and at least 128.")
        words = self.random_bits(seed_bits).reshape(-1, 32).astype(np.uint64)
        place_values = (np.uint64(1) << np.arange(31, -1, -1, dtype=np.uint64))
        seed_words = [int(w) for w in (words * place_values).sum(axis=1)]
        return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed_words)))

    # -- protocol layer -----------------------------------------------------

    def select_signature_tokens(self, token_count: int) -> SignatureTokenBatch:
        """Uniformly choose one of the six Pauli eigenstates per signature token."""
        return SignatureTokenBatch(token_indices=self.uniform_integers(token_count, PAULI_ALPHABET_SIZE))


# ---------------------------------------------------------------------------
# Diagnostics (Test 2.1 and frontend charts)
# ---------------------------------------------------------------------------


def poisson_statistics(samples: np.ndarray, mean_photon_count: float) -> PoissonStatistics:
    """O(N) mean/variance of a raw photon-count stream."""
    if samples.size == 0:
        raise ValueError("samples must not be empty.")
    return PoissonStatistics(
        sample_count=int(samples.size),
        mean_photon_count=float(mean_photon_count),
        sample_mean=float(np.mean(samples)),
        sample_variance=float(np.var(samples, ddof=1)) if samples.size > 1 else 0.0,
    )


def poisson_histogram(samples: np.ndarray, mean_photon_count: float) -> list[dict[str, float]]:
    """Observed vs. theoretical Poisson frequencies, ready for a Recharts bar/line chart."""
    if samples.size == 0:
        return []
    max_count = int(samples.max())
    observed = np.bincount(samples, minlength=max_count + 1) / samples.size
    photon_numbers = np.arange(max_count + 1)
    expected = poisson.pmf(photon_numbers, mean_photon_count)
    return [
        {"photon_count": int(k), "observed": float(o), "expected": float(e)}
        for k, o, e in zip(photon_numbers, observed, expected)
    ]


def select_pauli_bases(
    token_count: int,
    mean_photon_count: float = DEFAULT_MEAN_PHOTON_COUNT,
    seed: int | None = None,
) -> SignatureTokenBatch:
    """Convenience wrapper: one-shot OQRNG token selection."""
    return OpticalQRNG(mean_photon_count=mean_photon_count, seed=seed).select_signature_tokens(token_count)

"""Zwei-Zustands-HMM als kausaler Post-Processor auf den RF-Probas.

Scaled-Likelihood-Hybrid (DNN-HMM-Trick aus der Spracherkennung): der RF
liefert die Emission — seine kalibrierte Wahrscheinlichkeit ``P(writing|x)``,
geteilt durch den Klassen-Prior, ist eine skalierte Likelihood. Das HMM lernt
aus den Train-Fold-Labels nur die 2x2-Übergangsmatrix. Reine, seiteneffektfreie
Numerik; die LOSO-Orchestrierung (Per-Person-Holdout, Leakage-Gate, Metriken)
liegt im Treiber ``scripts/ml/hmm_postprocess_loso.py``.

Zustände: ``0 = idle``, ``1 = writing``.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np


def estimate_transition_matrix(
    sequences: Iterable[Sequence[int]],
    n_states: int = 2,
    smoothing: float = 1.0,
) -> np.ndarray:
    """``A[i, j] = P(state_{t+1} = j | state_t = i)``.

    Übergänge werden **pro Sequenz** (= pro Session) gezählt; über die Grenze
    zwischen zwei Sequenzen wird nie gezählt — sonst entstünde an jeder
    Session-Grenze ein Phantom-Übergang. Laplace-Glättung ``smoothing``
    verhindert harte Nullen; eine Zeile ganz ohne Counts fällt auf uniform
    zurück (statt 0/0).
    """
    counts = np.zeros((n_states, n_states), dtype=float)
    for seq in sequences:
        s = np.asarray(seq, dtype=int)
        if s.size < 2:
            continue
        np.add.at(counts, (s[:-1], s[1:]), 1.0)
    counts += smoothing
    A = np.empty((n_states, n_states), dtype=float)
    for i in range(n_states):
        row_sum = counts[i].sum()
        A[i] = counts[i] / row_sum if row_sum > 0.0 else 1.0 / n_states
    return A


def class_priors(
    labels: Sequence[int], n_states: int = 2, smoothing: float = 1.0
) -> np.ndarray:
    """Klassen-Basisraten ``[P(idle), P(writing)]`` der (Train-)Labels."""
    counts = np.bincount(np.asarray(labels, dtype=int), minlength=n_states).astype(float)
    counts += smoothing
    return counts / counts.sum()


def scaled_likelihoods(
    proba: Sequence[float], priors: Sequence[float], eps: float = 1e-3
) -> np.ndarray:
    """Skalierte Likelihood ``b[t, s] = P(o_t | s) ∝ P(s | o_t) / P(s)``.

    ``proba`` ist der RF-Posterior ``P(writing | o_t)``. Die Skalierung mit dem
    Klassen-Prior macht daraus eine (unnormierte) Emissions-Likelihood, mit der
    das HMM rechnet. Clipping auf ``[eps, 1 - eps]`` hält das Verhältnis endlich
    (isotone Kalibrierung kann exakte 0/1 ausgeben).
    """
    p = np.clip(np.asarray(proba, dtype=float), eps, 1.0 - eps)
    pi_idle, pi_writing = float(priors[0]), float(priors[1])
    b = np.empty((p.shape[0], 2), dtype=float)
    b[:, 0] = (1.0 - p) / pi_idle
    b[:, 1] = p / pi_writing
    return b


def forward_filter(
    emissions: np.ndarray, transition: np.ndarray, initial: np.ndarray
) -> np.ndarray:
    """Kausaler Filter-Posterior ``P(state_t | o_1..t)`` pro Zeitschritt.

    Nur Vergangenheit + Gegenwart — kein Look-ahead. Das ist das live-ehrliche
    Gegenstück zur kausalen Burst-Glättung (``center=False``). Per-Schritt-
    Normierung hält die α-Rekursion numerisch stabil über lange Sessions.
    """
    b = np.asarray(emissions, dtype=float)
    A = np.asarray(transition, dtype=float)
    n = b.shape[0]
    post = np.empty_like(b)
    alpha = np.asarray(initial, dtype=float) * b[0]
    alpha = alpha / alpha.sum()
    post[0] = alpha
    for t in range(1, n):
        alpha = (A.T @ alpha) * b[t]
        alpha = alpha / alpha.sum()
        post[t] = alpha
    return post


def forward_backward(
    emissions: np.ndarray, transition: np.ndarray, initial: np.ndarray
) -> np.ndarray:
    """Nicht-kausaler Smoothing-Posterior ``P(state_t | o_1..T)`` (γ).

    Nutzt die **ganze** Sequenz (auch die Zukunft) — nur als beschriftete
    Obergrenze zu reporten, nie als Live-Headline (das wäre der
    ``center=True``-Look-ahead).
    """
    b = np.asarray(emissions, dtype=float)
    A = np.asarray(transition, dtype=float)
    n, k = b.shape
    alpha = np.empty((n, k))
    c = np.empty(n)
    a = np.asarray(initial, dtype=float) * b[0]
    c[0] = a.sum()
    alpha[0] = a / c[0]
    for t in range(1, n):
        a = (A.T @ alpha[t - 1]) * b[t]
        c[t] = a.sum()
        alpha[t] = a / c[t]
    beta = np.empty((n, k))
    beta[-1] = 1.0
    for t in range(n - 2, -1, -1):
        beta[t] = (A @ (b[t + 1] * beta[t + 1])) / c[t + 1]
    gamma = alpha * beta
    return gamma / gamma.sum(axis=1, keepdims=True)


class OnlineForwardFilter:
    """Stateful Ein-Schritt-Variante von ``forward_filter`` für Live-Decoding.

    Dieselbe α-Rekursion, aber pro Beobachtung einzeln vorgerückt: der
    Live-Tracker speist jede RF-Proba per ``step()`` ein und liest sofort den
    kausalen writing-Posterior zurück. Der Zustand (``alpha``) bleibt zwischen
    Ticks erhalten; ``reset()`` löscht ihn an Stream-Lücken / Modell-Wechseln,
    damit ein abgestandener Prior nie in eine frische Session blutet (der
    stateful-Caveat aus der HMM-Analyse).

    Die durchgereichte Sequenz ``step(p_1), step(p_2), …`` ist **bit-identisch**
    zu ``forward_filter(scaled_likelihoods([p_1, p_2, …], priors), A, priors)``
    — verifiziert in ``tests/test_hmm.py``.
    """

    def __init__(
        self, transition: np.ndarray, priors: np.ndarray, eps: float = 1e-3
    ) -> None:
        self._A = np.asarray(transition, dtype=float)
        self._priors = np.asarray(priors, dtype=float)
        self._eps = float(eps)
        self._alpha: np.ndarray | None = None

    def reset(self) -> None:
        """Verwerfe den akkumulierten Zustand — nächster ``step`` startet am Prior."""
        self._alpha = None

    def step(self, proba: float) -> float:
        """Rücke um eine Beobachtung vor, gib ``P(writing | o_1..t)`` zurück."""
        b = scaled_likelihoods([proba], self._priors, eps=self._eps)[0]
        if self._alpha is None:
            alpha = self._priors * b
        else:
            alpha = (self._A.T @ self._alpha) * b
        alpha = alpha / alpha.sum()
        self._alpha = alpha
        return float(alpha[1])


def viterbi(
    emissions: np.ndarray, transition: np.ndarray, initial: np.ndarray
) -> np.ndarray:
    """MAP-Zustandsfolge (hartes Decode) — nicht-kausal, in Log-Space."""
    b = np.asarray(emissions, dtype=float)
    A = np.asarray(transition, dtype=float)
    n, k = b.shape
    floor = 1e-300
    log_b = np.log(np.clip(b, floor, None))
    log_A = np.log(np.clip(A, floor, None))
    log_pi = np.log(np.clip(np.asarray(initial, dtype=float), floor, None))

    delta = np.empty((n, k))
    psi = np.zeros((n, k), dtype=int)
    delta[0] = log_pi + log_b[0]
    for t in range(1, n):
        for j in range(k):
            scores = delta[t - 1] + log_A[:, j]
            best = int(np.argmax(scores))
            psi[t, j] = best
            delta[t, j] = scores[best] + log_b[t, j]

    path = np.empty(n, dtype=int)
    path[-1] = int(np.argmax(delta[-1]))
    for t in range(n - 2, -1, -1):
        path[t] = psi[t + 1, path[t + 1]]
    return path

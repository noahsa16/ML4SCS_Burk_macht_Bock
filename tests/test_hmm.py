"""HMM-Post-Processing-Kern (`src/evaluation/hmm.py`).

Zwei-Zustands-HMM (idle / writing) als kausaler Glätter auf den
Per-Fenster-Wahrscheinlichkeiten des RF. Scaled-Likelihood-Hybrid: der RF
liefert die Emission (Posterior / Klassen-Prior), das HMM lernt nur die
Übergänge aus den Train-Fold-Labels.

Die tragenden Invarianten:
  - Übergänge werden **pro Session** gezählt (keine Phantom-Übergänge über
    Session-Grenzen, analog zur Sort-Stability- und Burst-Per-Session-Logik).
  - Der Forward-Filter ist **kausal**: eine Störung bei t lässt jeden
    Posterior vor t unverändert (Gegenstück zum Burst-`center=False`-Fix).
  - Forward-Backward ist nicht-kausal (nutzt die Zukunft) — als beschriftete
    Obergrenze, nie als Headline.
"""
from __future__ import annotations

import numpy as np

from src.evaluation.hmm import (
    class_priors,
    estimate_transition_matrix,
    forward_backward,
    forward_filter,
    scaled_likelihoods,
    viterbi,
)


# --- Transition estimation -------------------------------------------------

def test_transition_counts_within_a_single_session():
    # 1->1 (x3), 1->0 (x1); idle-Zeile hat keine ausgehenden Übergänge.
    seqs = [np.array([1, 1, 1, 1, 0])]
    A = estimate_transition_matrix(seqs, smoothing=1.0)
    # Zeile 1 (von writing): counts [1, 3] + 1 = [2, 4] -> [1/3, 2/3]
    assert np.allclose(A[1], [1 / 3, 2 / 3])
    # Zeile 0 (von idle): keine Counts -> reine Glättung [1,1] -> [0.5, 0.5]
    assert np.allclose(A[0], [0.5, 0.5])


def test_transitions_do_not_cross_session_boundaries():
    # Zwei Sessions: [1,1] und [0,0]. Korrekt: nur 1->1 und 0->0.
    # Würde man konkatenieren ([1,1,0,0]), entstünde ein Phantom-1->0.
    seqs = [np.array([1, 1]), np.array([0, 0])]
    A = estimate_transition_matrix(seqs, smoothing=0.0)
    assert A[1, 0] == 0.0  # kein writing->idle über die Session-Grenze
    assert A[0, 1] == 0.0  # kein idle->writing über die Session-Grenze
    assert A[1, 1] == 1.0
    assert A[0, 0] == 1.0


def test_transition_rows_sum_to_one():
    seqs = [np.array([0, 1, 0, 1, 1, 0, 0, 1])]
    A = estimate_transition_matrix(seqs, smoothing=1.0)
    assert np.allclose(A.sum(axis=1), [1.0, 1.0])


def test_empty_transition_row_falls_back_to_uniform():
    # Nur writing-Zustände, idle kommt nie vor -> idle-Zeile undefiniert.
    seqs = [np.array([1, 1, 1])]
    A = estimate_transition_matrix(seqs, smoothing=0.0)
    assert np.allclose(A[0], [0.5, 0.5])  # uniform statt 0/0


# --- Class priors ----------------------------------------------------------

def test_class_priors_are_base_rates():
    labels = np.array([1, 1, 1, 0, 0])
    pri = class_priors(labels, smoothing=0.0)
    assert np.allclose(pri, [0.4, 0.6])  # [idle, writing]
    assert np.isclose(pri.sum(), 1.0)


# --- Scaled likelihoods ----------------------------------------------------

def test_scaled_likelihoods_shape_and_values():
    proba = np.array([0.9])
    pri = np.array([0.5, 0.5])
    b = scaled_likelihoods(proba, pri)
    assert b.shape == (1, 2)
    # idle = (1-p)/pi_idle = 0.1/0.5 = 0.2 ; writing = p/pi_w = 0.9/0.5 = 1.8
    assert np.allclose(b[0], [0.2, 1.8])


def test_scaled_likelihoods_clip_extreme_proba():
    # p=0 und p=1 dürfen kein inf/nan erzeugen (Clipping auf [eps, 1-eps]).
    proba = np.array([0.0, 1.0])
    pri = np.array([0.5, 0.5])
    b = scaled_likelihoods(proba, pri, eps=1e-3)
    assert np.all(np.isfinite(b))


def test_scaled_likelihoods_higher_proba_favours_writing():
    pri = np.array([0.5, 0.5])
    b = scaled_likelihoods(np.array([0.2, 0.8]), pri)
    # Verhältnis writing/idle steigt mit der Proba.
    r_low = b[0, 1] / b[0, 0]
    r_high = b[1, 1] / b[1, 0]
    assert r_high > r_low


# --- Forward filter (causal) ----------------------------------------------

def test_forward_filter_posterior_is_normalised():
    rng = np.random.default_rng(0)
    b = rng.uniform(0.1, 2.0, size=(20, 2))
    A = np.array([[0.9, 0.1], [0.1, 0.9]])
    pi0 = np.array([0.5, 0.5])
    post = forward_filter(b, A, pi0)
    assert post.shape == (20, 2)
    assert np.allclose(post.sum(axis=1), 1.0)
    assert np.all((post >= 0.0) & (post <= 1.0))


def test_forward_filter_is_causal():
    # DER tragende Test: eine Störung der Emission bei t lässt jeden
    # Filter-Posterior VOR t unverändert (kein Look-ahead).
    rng = np.random.default_rng(1)
    b = rng.uniform(0.1, 2.0, size=(12, 2))
    A = np.array([[0.8, 0.2], [0.2, 0.8]])
    pi0 = np.array([0.5, 0.5])
    t = 7

    base = forward_filter(b, A, pi0)
    b2 = b.copy()
    b2[t] = [b[t, 1], b[t, 0]]  # Emission bei t vertauschen
    perturbed = forward_filter(b2, A, pi0)

    assert np.allclose(base[:t], perturbed[:t])      # Vergangenheit unberührt
    assert not np.allclose(base[t], perturbed[t])    # Gegenwart ändert sich


def test_forward_backward_uses_the_future():
    # Kontrast: der nicht-kausale Smoother MUSS sich vor t ändern, wenn die
    # Emission bei t gestört wird (er nutzt die Zukunft -> Obergrenze).
    rng = np.random.default_rng(2)
    b = rng.uniform(0.1, 2.0, size=(12, 2))
    A = np.array([[0.8, 0.2], [0.2, 0.8]])
    pi0 = np.array([0.5, 0.5])
    t = 7

    base = forward_backward(b, A, pi0)
    b2 = b.copy()
    b2[t] = [b[t, 1], b[t, 0]]
    perturbed = forward_backward(b2, A, pi0)

    assert not np.allclose(base[:t], perturbed[:t])  # Vergangenheit ändert sich


def test_forward_filter_carries_state_through_a_short_dip():
    # Klebrige Übergänge + starker writing-Schwung: ein einzelner low-proba-
    # Ausrutscher bleibt im Filter writing (>0.5).
    proba = np.array([0.95, 0.95, 0.95, 0.2, 0.95, 0.95])
    pri = np.array([0.5, 0.5])
    b = scaled_likelihoods(proba, pri)
    A = np.array([[0.99, 0.01], [0.01, 0.99]])
    pi0 = np.array([0.5, 0.5])
    post = forward_filter(b, A, pi0)
    assert post[3, 1] > 0.5  # Dip wird vom Schwung überstimmt


# --- Viterbi ---------------------------------------------------------------

def test_viterbi_path_shape_and_values():
    rng = np.random.default_rng(3)
    b = rng.uniform(0.1, 2.0, size=(15, 2))
    A = np.array([[0.7, 0.3], [0.3, 0.7]])
    pi0 = np.array([0.5, 0.5])
    path = viterbi(b, A, pi0)
    assert path.shape == (15,)
    assert set(np.unique(path)).issubset({0, 1})


def test_viterbi_overrules_a_single_dip():
    # Hartes MAP-Decode: ein einzelner Ausrutscher in einer klaren
    # writing-Sequenz wird bei klebrigen Übergängen geglättet.
    proba = np.array([0.95, 0.95, 0.95, 0.2, 0.95, 0.95, 0.95])
    pri = np.array([0.5, 0.5])
    b = scaled_likelihoods(proba, pri)
    A = np.array([[0.99, 0.01], [0.01, 0.99]])
    pi0 = np.array([0.5, 0.5])
    path = viterbi(b, A, pi0)
    assert np.all(path == 1)  # durchgehend writing, Dip überstimmt

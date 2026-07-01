"""Tests fuer die grouped-K-fold-Partitionierung (train_loso._make_fold_sets).

Kern-Invariante: leakage-frei — ein Subject taucht in genau EINEM Fold auf,
kreuzt also nie Train/Test (Gegenteil von Random-K-fold ueber Fenster).
"""
from src.training.train_loso import _make_fold_sets


def test_none_folds_is_loso():
    g = ["P1", "P2", "P3", "P4"]
    assert _make_fold_sets(g, None, 42) == [["P1"], ["P2"], ["P3"], ["P4"]]


def test_folds_ge_groups_falls_back_to_loso():
    g = ["P1", "P2"]
    assert len(_make_fold_sets(g, 5, 42)) == 2  # K >= #Groups -> LOSO


def test_grouped_kfold_is_leakage_free_and_complete():
    g = [f"P{i}" for i in range(15)]
    fs = _make_fold_sets(g, 5, 42)
    assert len(fs) == 5
    flat = [p for chunk in fs for p in chunk]
    assert sorted(flat) == sorted(g)          # jede Person genau einmal
    assert len(flat) == len(set(flat))        # kein Subject in zwei Folds
    assert all(len(chunk) == 3 for chunk in fs)  # 15/5 balanciert


def test_grouped_kfold_deterministic_per_seed():
    g = [f"P{i}" for i in range(12)]
    assert _make_fold_sets(g, 4, 7) == _make_fold_sets(g, 4, 7)
    assert _make_fold_sets(g, 4, 7) != _make_fold_sets(g, 4, 99)


def test_grouped_kfold_uneven_sizes_differ_by_at_most_one():
    g = [f"P{i}" for i in range(14)]  # 14 nicht durch 5 teilbar
    fs = _make_fold_sets(g, 5, 42)
    assert len(fs) == 5
    sizes = sorted(len(c) for c in fs)
    assert sizes == [2, 3, 3, 3, 3]
    flat = [p for c in fs for p in c]
    assert sorted(flat) == sorted(g)          # vollstaendig, leakage-frei

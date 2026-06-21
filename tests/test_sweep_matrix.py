"""Tests fuer den GitHub-Actions-Sweep-Matrix-Builder (scripts/ml/sweep_matrix.py).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden
(ROOT liegt via conftest schon auf sys.path).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "sweep_matrix", ROOT / "scripts" / "ml" / "sweep_matrix.py"
)
sweep_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep_matrix)

_ENV_KEYS = ("MODELS", "GAPS", "WINDOWS", "EXTRAS", "DEEP_WINS")
# Deep-Lang-Fenster-Jobs heissen cnn-win5 / tcn-win10 / tcn6-win5 — vom
# rf-win5-Klassik-Job (Prefix "rf-") sauseinanderzuhalten.
_DEEP_WIN_PREFIXES = ("cnn-win", "tcn-win", "tcn6-win")


def _build_with(monkeypatch, **env) -> dict[str, str]:
    """build() mit kontrolliertem Environment -> {name: cmd}."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return {j["name"]: j["cmd"] for j in sweep_matrix.build()["include"]}


def _deep_win_jobs(names: set[str]) -> set[str]:
    return {n for n in names if n.startswith(_DEEP_WIN_PREFIXES)}


def test_deep_wins_off_by_default(monkeypatch):
    """Leeres Environment (= Cron) -> keine langen Deep-Fenster-Jobs.

    CPU-Runner brauchen fuer 5/10-s-Deep-Laeufe lange; der naechtliche Cron
    bleibt schlank, die Dimension wird gezielt per Dispatch eingeschaltet.
    """
    assert not _deep_win_jobs(set(_build_with(monkeypatch)))


def test_deep_wins_enabled_adds_5s_and_10s_jobs(monkeypatch):
    """DEEP_WINS='5,10' -> cnn/tcn je als 5-s- und 10-s-Input-Job."""
    by = _build_with(monkeypatch, DEEP_WINS="5,10")
    for m in ("cnn", "tcn"):
        assert f"{m}-win5" in by
        assert f"{m}-win10" in by


def test_tcn6_only_at_its_design_window_5s(monkeypatch):
    """tcn6 (rezeptives Feld ~5 s) laeuft nur @5 s, nie @10 s."""
    by = _build_with(monkeypatch, DEEP_WINS="5,10")
    assert "tcn6-win5" in by
    assert "tcn6-win10" not in by
    # Ohne 5 in der Liste taucht tcn6 gar nicht auf.
    by2 = _build_with(monkeypatch, DEEP_WINS="10")
    assert "tcn6-win5" not in by2 and "tcn6-win10" not in by2


def test_deep_wins_command_well_formed(monkeypatch):
    by = _build_with(monkeypatch, DEEP_WINS="5,10")
    assert by["tcn-win10"] == (
        "python -m src.training.deep --model tcn --pool legacy --win 10"
    )
    assert by["tcn6-win5"] == (
        "python -m src.training.deep --model tcn6 --pool legacy --win 5"
    )


def test_deep_wins_single_window(monkeypatch):
    """DEEP_WINS='5' -> nur die angeforderte Skala."""
    by = _build_with(monkeypatch, DEEP_WINS="5")
    assert "tcn-win5" in by
    assert "tcn-win10" not in by


def test_deep_wins_can_be_disabled(monkeypatch):
    """DEEP_WINS='none' (Dispatch abgewaehlt) -> keine Deep-Fenster-Jobs."""
    assert not _deep_win_jobs(set(_build_with(monkeypatch, DEEP_WINS="none")))


def test_headline_jobs_unchanged(monkeypatch):
    """Bestehende Jobs (klassisch + 1-s-Deep + gap/window-Sweeps) intakt."""
    by = _build_with(monkeypatch)
    assert by["rf"].startswith("python -m src.training.train_loso")
    assert by["tcn"] == "python -m src.training.deep --model tcn --pool legacy"
    assert "rf-gap2000" in by
    assert "rf-win5" in by

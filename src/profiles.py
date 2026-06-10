"""watch_profile-Taxonomie — eine Vokabel für die Datenform, überall.

Profile beschreiben die *Form* eines Watch-Datensatzes:

==========  ====  =======  ========================================
Profil      Hz    Kanäle   Inhalt
==========  ====  =======  ========================================
50hz        50    6        Legacy-Pool (88 Features)
100hz       100   6        Transition (S032/S033, pre-Gravity)
100hz_grav  100   9        Modern (92 Features, + gx/gy/gz)
==========  ====  =======  ========================================

Dieselben Strings sind (1) Ordnernamen unter
``data/processed/windows/{profile}/``, (2) Werte der
``watch_profile``-Spalte in sessions.csv und (3) CLI-Vokabular.

Eine Modern-Session existiert legitim in zwei Profilen: nativ
(``100hz_grav``) und als downsampled Legacy-View (``50hz``, via
``src.features.downsample``). Native Auflösung = höchste vorhandene
Fidelity; Views sind per Konstruktion immer downsampled.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[1]
DATA_PROC = ROOT / "data" / "processed"
WINDOWS_DIR = DATA_PROC / "windows"

PROFILES = ("50hz", "100hz", "100hz_grav")
# Why: native = beste vorhandene Fidelity — Views sind immer
# downsampled, also findet absteigende Suche zuerst das Original.
_NATIVE_SEARCH_ORDER = ("100hz_grav", "100hz", "50hz")

_VALID_HZ = (50.0, 100.0)
# Sample-Spalten (merged/raw), nicht Feature-Spalten (windows).
_GRAVITY_SAMPLE_COLS = ("gx", "gy", "gz")


def windows_path(session_id: str, profile: str) -> Path:
    """Kanonischer Pfad der Windows-CSV für (Session, Profil)."""
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}, got {profile!r}")
    return WINDOWS_DIR / profile / f"{session_id}_windows.csv"


def find_windows(session_id: str, profile: str | None = None) -> Path | None:
    """Windows-CSV auflösen; None wenn nicht vorhanden.

    profile=None → native Auflösung (höchste Fidelity zuerst), mit
    Fallback auf den alten flachen Pfad ``data/processed/{sid}_windows.csv``.
    Explizites Profil → nur der Profil-Ordner, bewusst ohne Flat-Fallback:
    bei einer flachen Datei ist die Form nicht aus den Spalten ableitbar
    (Windows-Features tragen keine Sample-Rate).
    """
    order = (profile,) if profile is not None else _NATIVE_SEARCH_ORDER
    for prof in order:
        cand = windows_path(session_id, prof)
        if cand.exists():
            return cand
    if profile is None:
        flat = DATA_PROC / f"{session_id}_windows.csv"
        if flat.exists():
            warnings.warn(
                f"{flat.name} liegt noch flach unter data/processed/ — "
                f"bitte nach windows/{{profil}}/ migrieren "
                f"(python -m src.profiles).",
                UserWarning,
                stacklevel=2,
            )
            return flat
    return None


def profile_for(fs_hz: float, has_gravity: bool) -> str:
    """Profilname aus gemessener Rate + Gravity-Verfügbarkeit."""
    nearest = min(_VALID_HZ, key=lambda hz: abs(hz - fs_hz))
    if abs(fs_hz - nearest) / nearest > 0.2:
        raise ValueError(
            f"Sample-Rate {fs_hz:.1f} Hz liegt außerhalb ±20 % der gültigen "
            f"Raten {_VALID_HZ} — Profil nicht zuordenbar"
        )
    return f"{int(nearest)}hz" + ("_grav" if has_gravity else "")


def detect_profile(df: pd.DataFrame) -> str:
    """Profil aus dem *Inhalt* eines Sample-Frames (merged/raw) ableiten.

    Der Ordner lügt nie: Writer leiten das Zielprofil hierüber ab statt
    aus einem manuell gesetzten Flag. Braucht die per-Sample-``ts``-Spalte
    (Sekunden, Watch-Clock) — ``local_ts_ms`` hat Batch-Ties und taugt
    nicht für Raten-Messung.
    """
    if "ts" not in df.columns:
        raise ValueError("detect_profile braucht die per-Sample-'ts'-Spalte")
    dt = pd.Series(df["ts"]).diff().median()
    if not dt or dt <= 0:
        raise ValueError("ts-Spalte ist nicht monoton steigend — Rate unbestimmbar")
    fs = 1.0 / float(dt)
    has_grav = all(c in df.columns for c in _GRAVITY_SAMPLE_COLS) and (
        df[list(_GRAVITY_SAMPLE_COLS)].notna().any().any()
    )
    return profile_for(fs, has_grav)


def migrate_flat_windows() -> list[Path]:
    """Flache ``{sid}_windows.csv`` in die Profil-Ordner verschieben.

    Das Profil einer Windows-CSV ist nur über die merged-Schwester
    bestimmbar — fehlt sie, bleibt die Datei liegen (Warnung statt
    Fehler, damit ein Stragglerlauf den Rest nicht blockiert).
    """
    moved: list[Path] = []
    for flat in sorted(DATA_PROC.glob("S*_windows.csv")):
        sid = flat.name.removesuffix("_windows.csv")
        merged = DATA_PROC / f"{sid}_merged.csv"
        if not merged.exists():
            warnings.warn(
                f"{flat.name}: keine merged-Schwester ({sid}_merged.csv) — "
                f"Profil unbestimmbar, Datei bleibt flach liegen.",
                UserWarning,
                stacklevel=2,
            )
            continue
        profile = detect_profile(pd.read_csv(merged, usecols=lambda c: c in
                                             {"ts", *_GRAVITY_SAMPLE_COLS}))
        target = windows_path(sid, profile)
        target.parent.mkdir(parents=True, exist_ok=True)
        flat.rename(target)
        moved.append(target)
        print(f"{flat.name} → windows/{profile}/")
    return moved


if __name__ == "__main__":
    if not migrate_flat_windows():
        print("Nichts zu migrieren — keine flachen *_windows.csv gefunden.")


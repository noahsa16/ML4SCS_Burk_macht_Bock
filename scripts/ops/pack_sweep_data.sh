#!/usr/bin/env bash
# Packt die (gitignored) Daten, die ein LOSO-Sweep-Lauf braucht:
#   - data/sessions.csv          (Session-Index + verdict/watch_profile)
#   - data/processed/windows/    (Feature-Fenster für die klassischen Modelle)
#   - data/processed/*_merged*.csv (rohe Sequenzen für die Deep-Modelle)
#
# Ohne Argumente: alles in ein Bundle (sweep_data.zip) — bisheriges Verhalten,
# unveraendert, weil externe Runner diesen Aufruf verwenden.
#
# Mit --profile: nur der Pool, den ein Lauf tatsaechlich liest, plus die dazu
# passenden merged-Sequenzen. Warum getrennt: legacy (50 Hz, 88 Features) und
# modern (100 Hz + Gravity, 92 Features) sind zwei verschiedene Experimente;
# getrennte Bundles halten sie vergleichbar und die Transfers klein.
#
#   ./scripts/ops/pack_sweep_data.sh
#   ./scripts/ops/pack_sweep_data.sh --profile 50hz       --exclude S095
#   ./scripts/ops/pack_sweep_data.sh --profile 100hz_grav --exclude S095
#
# Hosten z. B. via GitHub-Release:
#   gh release create sweep-data sweep_data.zip --title "Sweep-Daten" --notes ""
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${PYTHON:-python}"
profile=""
exclude=""
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) profile="${2:?--profile braucht einen Wert}"; shift 2 ;;
    --exclude) exclude="${2:?--exclude braucht einen Wert}"; shift 2 ;;
    *) echo "unbekanntes Argument: $1" >&2; exit 2 ;;
  esac
done

# Why: beide Window-Profile je trainable Subject sicherstellen, bevor gepackt
# wird — sonst droppt ein both-Pool-Sweep (legacy+modern) Subjects still, denen
# ein Profil fehlt. Idempotent; harter Fail bei nicht baubarer Luecke.
"$PY" scripts/ops/ensure_views.py

[ -f data/sessions.csv ] || { echo "FEHLT: data/sessions.csv"; exit 1; }
[ -d data/processed/windows ] || { echo "FEHLT: data/processed/windows/"; exit 1; }

if [ -z "$profile" ]; then
  out="sweep_data.zip"
  rm -f "$out"

  # Why: globs vorab in ein Array, damit ein fehlendes Match nicht den ganzen
  # zip-Aufruf killt (set -e) — und damit klar wird, was eingepackt wird.
  shopt -s nullglob
  merged=(data/processed/*_merged*.csv)
  shopt -u nullglob
  [ ${#merged[@]} -gt 0 ] || { echo "FEHLT: data/processed/*_merged*.csv"; exit 1; }

  zip -rq "$out" data/sessions.csv data/processed/windows "${merged[@]}"
else
  case "$profile" in
    50hz|100hz|100hz_grav) ;;
    *) echo "unbekanntes Profil: $profile (50hz|100hz|100hz_grav)" >&2; exit 2 ;;
  esac
  src="data/processed/windows/$profile"
  [ -d "$src" ] || { echo "FEHLT: $src"; exit 1; }

  out="sweep_data_${profile}.zip"
  out_abs="$PWD/$out"
  rm -f "$out"

  # Why: Staging via Symlinks statt Kopien — die merged-CSVs sind je ~64 MB,
  # eine Kopie waere GB-teuer. zip speichert per Default den Inhalt, nicht den
  # Link (dafuer braeuchte es -y).
  stage="$(mktemp -d)"
  trap 'rm -rf "$stage"' EXIT
  mkdir -p "$stage/data/processed/windows/$profile"

  # Why: die Ausschluss-Liste wird IM Bundle als verdict='skip' materialisiert,
  # nicht nur durch Weglassen der Dateien. train_loso filtert auf verdict —
  # ein stilles Fehlen waere genau die Klasse von Bug, die dieses Projekt
  # schon dreimal Wochen gekostet hat. Die lokale sessions.csv (server-owned)
  # bleibt unangetastet.
  "$PY" - "$stage/data/sessions.csv" "$exclude" <<'PY'
import sys
import pandas as pd

dest, excl = sys.argv[1], [s for s in sys.argv[2].split(",") if s]
df = pd.read_csv("data/sessions.csv")
if excl:
    m = df.session_id.isin(excl)
    df.loc[m, "verdict"] = "skip"
    if "flag_note" in df.columns:
        # Why: die Spalte ist bei leerem Bestand float64 (all-NaN); ohne Cast
        # ist das Setzen eines Strings ab pandas 3 ein Fehler, kein Warning.
        df["flag_note"] = df["flag_note"].astype(object)
        df.loc[m, "flag_note"] = "aus Sweep-Bundle ausgeschlossen"
    print(f"  sessions.csv: {int(m.sum())} Session(s) auf verdict=skip: {', '.join(excl)}")
df.to_csv(dest, index=False)
PY

  n=0
  for f in "$src"/*_windows.csv; do
    s="$(basename "$f" _windows.csv)"
    case ",$exclude," in *",$s,"*) echo "  uebersprungen: $s"; continue ;; esac
    ln -s "$PWD/$f" "$stage/data/processed/windows/$profile/"
    if [ "$profile" = "50hz" ] && [ -f "data/processed/${s}_merged_legacy.csv" ]; then
      ln -s "$PWD/data/processed/${s}_merged_legacy.csv" "$stage/data/processed/"
    elif [ -f "data/processed/${s}_merged.csv" ]; then
      ln -s "$PWD/data/processed/${s}_merged.csv" "$stage/data/processed/"
    else
      echo "FEHLT: merged-CSV fuer $s"; exit 1
    fi
    n=$((n + 1))
  done
  [ "$n" -gt 0 ] || { echo "FEHLT: keine Fenster in $src"; exit 1; }
  echo "  $n Subjects in Profil $profile"

  (cd "$stage" && zip -rq "$out_abs" data)
fi

echo "→ $out  ($(du -h "$out" | cut -f1), $(unzip -l "$out" | tail -1 | awk '{print $2}') Dateien)"

#!/usr/bin/env bash
# Packt die (gitignored) Daten, die ein LOSO-Sweep-Lauf braucht, in sweep_data.zip:
#   - data/sessions.csv          (Session-Index + verdict/watch_profile)
#   - data/processed/windows/    (88-Feature-Fenster für die klassischen Modelle)
#   - data/processed/*_merged*.csv (rohe Sequenzen für die Deep-Modelle)
#
# Einmalig lokal ausführen, dann das Zip hosten und die URL als Repo-Secret
# SWEEP_DATA_URL hinterlegen — der Workflow (.github/workflows/sweep.yml) zieht es.
#
# Hosten z. B. via GitHub-Release:
#   ./scripts/ops/pack_sweep_data.sh
#   gh release create sweep-data sweep_data.zip --title "Sweep-Daten" --notes ""
#   # → die "browser_download_url" des Assets als Secret SWEEP_DATA_URL setzen
set -euo pipefail
cd "$(dirname "$0")/../.."

out="sweep_data.zip"
rm -f "$out"

# Why: globs vorab in ein Array, damit ein fehlendes Match nicht den ganzen
# zip-Aufruf killt (set -e) — und damit klar wird, was eingepackt wird.
shopt -s nullglob
merged=(data/processed/*_merged*.csv)
shopt -u nullglob

[ -f data/sessions.csv ] || { echo "FEHLT: data/sessions.csv"; exit 1; }
[ -d data/processed/windows ] || { echo "FEHLT: data/processed/windows/"; exit 1; }
[ ${#merged[@]} -gt 0 ] || { echo "FEHLT: data/processed/*_merged*.csv"; exit 1; }

zip -rq "$out" data/sessions.csv data/processed/windows "${merged[@]}"

echo "→ $out  ($(du -h "$out" | cut -f1), $(unzip -l "$out" | tail -1 | awk '{print $2}') Dateien)"
echo
echo "Nächste Schritte:"
echo "  1. Hosten (z. B.):  gh release create sweep-data $out"
echo "  2. Asset-URL als Repo-Secret SWEEP_DATA_URL setzen"
echo "     (Settings → Secrets and variables → Actions → New repository secret)"

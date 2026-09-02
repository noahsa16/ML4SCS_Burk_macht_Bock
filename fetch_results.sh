#!/usr/bin/env bash
# Holt die Ergebnisse des N=32/N=23-Laufs vom RunPod-Pod ab.
#
#   ./fetch_results.sh            # Status zeigen + Ergebnisse holen, wenn fertig
#   ./fetch_results.sh --status   # nur nachsehen, nichts herunterladen
#   ./fetch_results.sh --force    # herunterladen, auch wenn noch nicht fertig
#   ./fetch_results.sh --auto     # fuer cron: holen UND Pod loeschen, wenn fertig
#
# --auto loescht den Pod NUR, wenn BEIDE Laeufe ihren Fertig-Marker gesetzt
# haben UND der Download verifiziert ist (genug .pt, loso_oof da). Der Pod hat
# kein Volume -- ein Loeschen davor waere Totalverlust.
#
# Haengt ein Lauf fest (Absturz -> Fertig-Marker kommt nie), zieht --auto nach
# ALARM_HOURS Stunden ein Sicherungs-Backup OHNE zu terminieren und meldet sich
# per macOS-Notification. Sonst wuerde der Pod stumm weiter Geld kosten.
#
# Manuell terminieren (0,20 $/h, auch im Leerlauf):
#   runpodctl pod remove l3eqspwn9vb46l
set -euo pipefail
cd "$(dirname "$0")"

# Why: cron startet mit minimalem PATH -- runpodctl liegt in
# /opt/homebrew/bin und waere sonst "command not found".
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

POD=l3eqspwn9vb46l
HOST=205.196.17.108
PORT=13008
KEY=~/.runpod/ssh/runpodctl-ssh-key
REMOTE=/workspace/ML4SCS_Burk_macht_Bock
DEST="models/runs/pod_$(date +%Y%m%d)"
DONE_MARKER=".pod_fetched"
LOCK=".pod_fetch.lock"
ALARM_HOURS=20
MIN_PT=100          # erwartet 108 (6 Configs x 3 Seeds x 6 Dateien)

MODE="${1:-}"

notify() {
  echo "  !! $1"
  osascript -e "display notification \"$1\" with title \"ML4SCS Pod\"" 2>/dev/null || true
}

# Why: nach erfolgreichem Remove wuerde cron sonst ewig alle 20 min mit
# "Pod nicht erreichbar" scheitern -- verwirrend im Log.
if [ -f "$DONE_MARKER" ]; then
  echo "Bereits abgeholt und terminiert am $(cat "$DONE_MARKER"). Nichts zu tun."
  echo "Cron-Eintrag kann raus:  crontab -r"
  exit 0
fi

# Why: bei 20-min-Takt und langsamem Download koennen sich zwei Laeufe
# ueberlappen -- der zweite wuerde dem ersten das Tarball wegloeschen.
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Ein anderer Lauf ist aktiv ($LOCK). Ende."
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

sshp() { ssh -n -i "$KEY" -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new \
             -p "$PORT" "root@$HOST" "$@"; }

echo "=== $(date "+%F %T")  Pod-Status ==="
POD_JSON=$(runpodctl pod get "$POD" 2>/dev/null) || {
  echo "Pod nicht erreichbar - schon terminiert?"; exit 1; }
echo "$POD_JSON" | grep -E '"(desiredStatus|uptimeSeconds|costPerHr)"'
UPTIME=$(echo "$POD_JSON" | sed -n 's/.*"uptimeSeconds": *\([0-9]*\).*/\1/p' | head -1)
UPTIME=${UPTIME:-0}

echo
echo "=== Fortschritt ==="
sshp 'grep -h "=====" /workspace/run.log /workspace/run_modern.log 2>/dev/null | tail -6' || true

# Why: BEIDE Marker pruefen. Nur auf "MODERN FERTIG" zu schauen war ein Loch --
# stirbt der Legacy-Lauf spaet, laeuft modern trotzdem durch und meldet fertig,
# waehrend loso_oof_legacy.csv (Grundlage fuers HMM) nie eingesammelt wurde.
LEG=$(sshp 'grep -c "  fertig =====" /workspace/run.log 2>/dev/null || true' | tr -dc '0-9' | head -c 3)
MOD=$(sshp 'grep -c "MODERN FERTIG" /workspace/run_modern.log 2>/dev/null || true' | tr -dc '0-9' | head -c 3)
LEG=${LEG:-0}; MOD=${MOD:-0}
echo
echo "Fertig-Marker:  legacy=$LEG  modern=$MOD  (beide >0 = durch)"

echo "=== Artefakte auf dem Pod ==="
sshp "echo \"  .pt: \$(find $REMOTE/models/hp_grid -name '*.pt' 2>/dev/null | wc -l) / erwartet 108\"" || true

FERTIG=0
[ "${LEG#0}" != "" ] && [ "${MOD#0}" != "" ] && FERTIG=1

echo
if [ "$FERTIG" = "1" ]; then
  echo "=> Lauf ist DURCH (beide Marker)."
elif [ "$MODE" = "--force" ]; then
  echo "=> Noch nicht fertig, --force: hole Zwischenstand (ohne Terminierung)."
elif [ "$MODE" = "--auto" ] && [ "$UPTIME" -gt $((ALARM_HOURS * 3600)) ]; then
  # Why: haengt etwas, sind die fertigen Ergebnisse auf einem volumelosen Pod
  # ungesichert -- Backup ziehen, aber NICHT terminieren, damit ein Mensch
  # nachsehen kann.
  notify "Lauf haengt seit >${ALARM_HOURS}h. Ziehe Backup, Pod bleibt stehen."
  MODE="--force"
else
  echo "=> Noch nicht fertig. Spaeter nochmal, oder --force fuer den Zwischenstand."
  exit 0
fi

if [ "$MODE" = "--status" ]; then
  exit 0
fi

echo
echo "=== Herunterladen nach $DEST ==="
mkdir -p "$DEST"
# Why: results/ allein reicht nicht -- die kanonischen CSVs (loso_cv/loso_oof,
# grid_study/grid_winner) und die Deep-Checkpoints liegen unter models/ und
# werden von den Pod-Skripten erst in ihrem Schlussblock nach results/ kopiert.
# Bei einem Abbruch waeren sie sonst nicht im Tarball.
sshp "cd /workspace && tar czf /workspace/results.tgz results \
      \$(cd /workspace && ls -d ML4SCS_Burk_macht_Bock/models/hp_grid 2>/dev/null) \
      ML4SCS_Burk_macht_Bock/models/loso_*.csv \
      ML4SCS_Burk_macht_Bock/models/grid_*.csv 2>/dev/null || true"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new -P "$PORT" \
    "root@$HOST:/workspace/results.tgz" "$DEST/"
tar xzf "$DEST/results.tgz" -C "$DEST"
rm "$DEST/results.tgz"

echo
echo "=== Heruntergeladen ==="
N_PT=$(find "$DEST" -name "*.pt" | wc -l | tr -d ' ')
N_CSV=$(find "$DEST" -name "*.csv" | wc -l | tr -d ' ')
HAS_OOF=$(find "$DEST" -name "loso_oof_legacy.csv" | wc -l | tr -d ' ')
echo "  .pt-Dateien:            $N_PT"
echo "  CSV:                    $N_CSV"
echo "  loso_oof_legacy.csv:    $HAS_OOF"
du -sh "$DEST"

if [ "$MODE" != "--auto" ] || [ "$FERTIG" != "1" ]; then
  echo
  echo "Pod NICHT terminiert (kein --auto oder Lauf nicht durch)."
  echo "Manuell:  runpodctl pod remove $POD"
  exit 0
fi

echo
echo "=== Auto-Terminierung ==="
# Why: der Pod hat kein Volume -- Loeschen ist unwiderruflich. Lieber ein paar
# Stunden Leerlauf bezahlen als 13 Stunden Rechenzeit verlieren.
if [ "$N_PT" -ge "$MIN_PT" ] && [ "$HAS_OOF" -ge 1 ]; then
  echo "  Download plausibel ($N_PT .pt, OOF da) -- hole noch die RF-Joblib…"
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new -P "$PORT" \
      "root@$HOST:$REMOTE/models/rf_all_legacy.joblib" "$DEST/" \
      || echo "  (RF-Joblib nicht geholt -- trotzdem weiter)"
  echo "  loesche Pod $POD"
  if runpodctl pod remove "$POD"; then
    date "+%F %T" > "$DONE_MARKER"
    notify "Ergebnisse geholt ($N_PT Modelle), Pod terminiert."
  else
    notify "Pod-Remove FEHLGESCHLAGEN - bitte manuell terminieren!"
    exit 1
  fi
else
  notify "Download unvollstaendig ($N_PT .pt, OOF=$HAS_OOF) - Pod bleibt stehen."
  exit 1
fi

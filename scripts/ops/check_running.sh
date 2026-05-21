#!/usr/bin/env bash
# Check ob ML4SCS-Prozesse laufen (Server, Tunnel, Pen-Logger).
# Battery-Saver: schnell sehen ob ein vergessener uvicorn CPU zieht.
#
#   ./scripts/ops/check_running.sh

set -u

found=0

check() {
  local label="$1" pattern="$2"
  # ps-Zeilen: PID + %CPU + Command. grep -v auf das Pattern selbst.
  local hits
  hits=$(ps aux | grep -E "$pattern" | grep -v grep || true)
  if [[ -n "$hits" ]]; then
    found=1
    echo "● $label"
    echo "$hits" | awk '{printf "    PID %-7s %5s%% CPU  %s\n", $2, $3, $11}'
  fi
}

echo "ML4SCS — laufende Prozesse"
echo "─────────────────────────────"

check "uvicorn / FastAPI-Server" "uvicorn server:app|server:app"
check "Cloudflare-Tunnel"        "cloudflared"
check "ngrok-Tunnel"             "ngrok"
check "Pen-Logger"               "pen_logger"

# Port 8000 — auch wenn der Prozessname nicht matcht.
if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  found=1
  echo "● Port 8000 belegt"
  lsof -iTCP:8000 -sTCP:LISTEN | awk 'NR>1 {printf "    PID %-7s %s\n", $2, $1}'
fi

echo "─────────────────────────────"
if [[ "$found" -eq 0 ]]; then
  echo "✓ Nichts läuft"
else
  echo "Zum Beenden:  kill <PID>   (oder: pkill -f \"uvicorn server:app\")"
fi

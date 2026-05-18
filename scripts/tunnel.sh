#!/usr/bin/env bash
# tunnel.sh — Quick Cloudflare-Tunnel für unterwegs.
# Hängt eine öffentliche https://*.trycloudflare.com URL vor localhost:8000,
# zeigt sie groß an und kopiert sie in die Zwischenablage. Ctrl+C beendet.

set -euo pipefail

PORT="${1:-8000}"
LOG="$(mktemp -t cf_tunnel.XXXXXX.log)"
URL=""

# Cloudflared-Prozess bei jedem Exit aufräumen.
cleanup() {
  if [[ -n "${CF_PID:-}" ]] && kill -0 "$CF_PID" 2>/dev/null; then
    kill "$CF_PID" 2>/dev/null || true
    wait "$CF_PID" 2>/dev/null || true
  fi
  rm -f "$LOG"
  echo
  echo "tunnel stopped."
}
trap cleanup EXIT INT TERM

# 1. cloudflared vorhanden?
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "✗ cloudflared nicht installiert."
  echo "  brew install cloudflared"
  exit 1
fi

# 2. Server-Sanity-Check (nur Hinweis, kein Hard-Fail)
if ! curl -sS -m 2 "http://127.0.0.1:${PORT}/" -o /dev/null; then
  echo "⚠  Server scheint auf Port ${PORT} nicht erreichbar."
  echo "   Tunnel wird trotzdem gestartet — Server-Start nicht vergessen:"
  echo "   uvicorn server:app --host 0.0.0.0 --port ${PORT}"
  echo
fi

# 3. Tunnel starten — mit Retries gegen trycloudflare 1101.
MAX_ATTEMPTS=3
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if [[ $attempt -eq 1 ]]; then
    echo "starting cloudflared tunnel → http://localhost:${PORT}…"
  else
    echo "retry ${attempt}/${MAX_ATTEMPTS} …"
  fi

  : > "$LOG"
  cloudflared tunnel --url "http://localhost:${PORT}" > "$LOG" 2>&1 &
  CF_PID=$!

  URL=""
  for _ in {1..30}; do
    if ! kill -0 "$CF_PID" 2>/dev/null; then
      break
    fi
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1 || true)
    [[ -n "$URL" ]] && break
    # Why: trycloudflare returns HTTP 500 (error 1101) intermittently; fail fast on that.
    if grep -qE "failed to unmarshal|error code: 1101" "$LOG"; then
      break
    fi
    sleep 0.5
  done

  [[ -n "$URL" ]] && break

  if kill -0 "$CF_PID" 2>/dev/null; then
    kill "$CF_PID" 2>/dev/null || true
    wait "$CF_PID" 2>/dev/null || true
  fi
  unset CF_PID

  if [[ $attempt -lt $MAX_ATTEMPTS ]]; then
    echo "⚠  tunnel-URL nicht erhalten (trycloudflare 1101?) — warte 3s…"
    sleep 3
  fi
done

if [[ -z "$URL" ]]; then
  echo "✗ Konnte nach ${MAX_ATTEMPTS} Versuchen keine Tunnel-URL extrahieren. Letzte Log-Zeilen:"
  tail -20 "$LOG"
  exit 1
fi

# 5. Clipboard (macOS)
if command -v pbcopy >/dev/null 2>&1; then
  printf "%s" "$URL" | pbcopy
  CLIP_NOTE="(in Zwischenablage)"
else
  CLIP_NOTE=""
fi

# 6. Schick anzeigen
LEN=${#URL}
BAR=$(printf '─%.0s' $(seq 1 $((LEN + 4))))
echo
echo "┌${BAR}┐"
printf "│  %s  │\n" "$URL"
echo "└${BAR}┘"
echo "${CLIP_NOTE}"
echo
echo "App → Settings → Server IP → einfügen → Save → Reconnect"
echo "Ctrl+C zum Beenden."
echo

# 7. Im Vordergrund warten — wenn cloudflared stirbt, brechen wir auch ab.
wait "$CF_PID"

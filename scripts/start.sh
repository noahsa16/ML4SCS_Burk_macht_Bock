#!/usr/bin/env bash
# start.sh — Server + Cloudflare-Tunnel mit hübschem TTY-UI.
# Ctrl+C beendet beide Prozesse sauber.

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Args ──────────────────────────────────────────────────────────────────
# Usage: start.sh [PORT] [--local|--no-tunnel|--tunnel]
# Default: interactive prompt (oder via $ML4SCS_TUNNEL=0/1 im Environment).
PORT="8000"
TUNNEL_MODE=""   # "", "on", "off"
for arg in "$@"; do
  case "$arg" in
    --local|--no-tunnel) TUNNEL_MODE="off" ;;
    --tunnel)            TUNNEL_MODE="on" ;;
    [0-9]*)              PORT="$arg" ;;
    -h|--help)
      echo "Usage: $0 [PORT] [--local|--tunnel]"
      echo "  --local / --no-tunnel  : nur lokal, kein cloudflared"
      echo "  --tunnel               : cloudflared starten"
      echo "  ohne Flag: interaktive Abfrage (oder ML4SCS_TUNNEL=0/1)"
      exit 0 ;;
  esac
done
if [[ -z "$TUNNEL_MODE" && -n "${ML4SCS_TUNNEL:-}" ]]; then
  case "$ML4SCS_TUNNEL" in
    0|off|no|false) TUNNEL_MODE="off" ;;
    1|on|yes|true)  TUNNEL_MODE="on" ;;
  esac
fi

LOG_DIR="$(mktemp -d -t ml4scs)"
SERVER_LOG="$LOG_DIR/server.log"
TUNNEL_LOG="$LOG_DIR/tunnel.log"

SERVER_PID=""
TUNNEL_PID=""
WE_STARTED_SERVER=0

# ── Farb-Tokens (mirror der Web-/App-Theme-Werte) ─────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_BOLD=$'\033[1m'
  C_GREEN=$'\033[38;5;71m'      # accent grün, gedämpft
  C_RED=$'\033[38;5;167m'
  C_YELLOW=$'\033[38;5;179m'
  C_ACCENT=$'\033[38;5;208m'    # warmes Orange
  C_TEXT2=$'\033[38;5;245m'
  C_TEXT3=$'\033[38;5;239m'
else
  C_RESET=""; C_DIM=""; C_BOLD=""
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_ACCENT=""; C_TEXT2=""; C_TEXT3=""
fi

# Linksbündige 2-Space-Einrückung als visuelle "Karten-Kante".
PAD="  "
log()  { printf "%s${C_DIM}%s${C_RESET}  %s\n" "$PAD" "$(date +%H:%M:%S)" "$*"; }
ok()   { log "${C_GREEN}●${C_RESET} $*"; }
warn() { log "${C_YELLOW}▲${C_RESET} $*"; }
err()  { log "${C_RED}✗${C_RESET} $*"; }
step() { log "${C_TEXT2}◌${C_RESET} ${C_TEXT2}$*${C_RESET}"; }
hr()   { printf "%s${C_TEXT3}────────────────────────────────────────${C_RESET}\n" "$PAD"; }

# ── Cleanup ───────────────────────────────────────────────────────────────
cleanup() {
  echo
  log "${C_DIM}shutting down…${C_RESET}"
  if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    ok "tunnel stopped"
  fi
  if (( WE_STARTED_SERVER )) && [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    ok "server stopped"
  elif [[ -n "$SERVER_PID" ]]; then
    log "${C_DIM}server (pid $SERVER_PID) bleibt — nicht von uns gestartet${C_RESET}"
  fi
  echo
  printf "%s${C_DIM}logs · %s${C_RESET}\n" "$PAD" "$LOG_DIR"
  echo
}
trap cleanup EXIT INT TERM

# ── Pixel-Banner ──────────────────────────────────────────────────────────
banner() {
  local A="$C_ACCENT" R="$C_RESET" D="$C_DIM" T2="$C_TEXT2" B="$C_BOLD" G="$C_GREEN"
  local mode_tag mode_dot
  if [[ "$TUNNEL_MODE" == "on" ]]; then
    mode_tag="cloudflare tunnel"
    mode_dot="${A}●${R}"
  else
    mode_tag="LAN-only"
    mode_dot="${G}●${R}"
  fi
  printf "\n"
  printf "${A}  ██████╗ ███╗   ███╗██████╗${R}\n"
  printf "${A}  ██╔══██╗████╗ ████║██╔══██╗${R}     ${B}ML4SCS${R} ${D}·${R} Burk macht Bock\n"
  printf "${A}  ██████╔╝██╔████╔██║██████╔╝${R}     ${T2}watch streamer${R} ${D}·${R} ${T2}port %s${R}\n" "$PORT"
  printf "${A}  ██╔══██╗██║╚██╔╝██║██╔══██╗${R}     %s ${T2}%s${R}\n" "$mode_dot" "$mode_tag"
  printf "${A}  ██████╔╝██║ ╚═╝ ██║██████╔╝${R}\n"
  printf "${A}  ╚═════╝ ╚═╝     ╚═╝╚═════╝${R}\n"
  printf "\n"
}
banner

# ── 1. Tunnel-Modus klären ────────────────────────────────────────────────
if [[ -z "$TUNNEL_MODE" ]]; then
  if [[ -t 0 ]]; then
    printf "%s${C_TEXT2}Cloudflare-Tunnel starten?${C_RESET} ${C_DIM}[y/N]${C_RESET} " "$PAD"
    read -r ans || ans=""
    case "$ans" in
      y|Y|yes|j|J) TUNNEL_MODE="on" ;;
      *)           TUNNEL_MODE="off" ;;
    esac
  else
    TUNNEL_MODE="off"
  fi
fi

if [[ "$TUNNEL_MODE" == "on" ]]; then
  if ! command -v cloudflared >/dev/null 2>&1; then
    err "cloudflared nicht installiert"
    printf "%s   ${C_DIM}brew install cloudflared${C_RESET}\n" "$PAD"
    exit 1
  fi
fi

# ── 2. Server schon online? ───────────────────────────────────────────────
if curl -s -m 1 "http://127.0.0.1:${PORT}/" -o /dev/null 2>/dev/null; then
  EXISTING_PID=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)
  ok "server   ${C_DIM}läuft schon · pid ${EXISTING_PID:-?}${C_RESET}"
  SERVER_PID="${EXISTING_PID:-}"
else
  step "server   ${C_DIM}starting uvicorn…${C_RESET}"
  if command -v uvicorn >/dev/null 2>&1; then
    uvicorn server:app --host 0.0.0.0 --port "$PORT" > "$SERVER_LOG" 2>&1 &
  else
    python3 -m uvicorn server:app --host 0.0.0.0 --port "$PORT" > "$SERVER_LOG" 2>&1 &
  fi
  SERVER_PID=$!
  WE_STARTED_SERVER=1

  for _ in {1..30}; do
    sleep 0.4
    if curl -s -m 1 "http://127.0.0.1:${PORT}/" -o /dev/null 2>/dev/null; then
      ok "server   ${C_DIM}up · pid $SERVER_PID${C_RESET}"
      break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      err "uvicorn konnte nicht starten — letzte Log-Zeilen:"
      tail -20 "$SERVER_LOG" | sed "s/^/${PAD}   ${C_DIM}/; s/$/${C_RESET}/"
      exit 1
    fi
  done
  if ! curl -s -m 1 "http://127.0.0.1:${PORT}/" -o /dev/null 2>/dev/null; then
    err "server timeout — letzte Log-Zeilen:"
    tail -20 "$SERVER_LOG" | sed "s/^/${PAD}   ${C_DIM}/; s/$/${C_RESET}/"
    exit 1
  fi
fi

# ── 3. Tunnel starten (oder LAN-IP ermitteln) ─────────────────────────────
URL=""
if [[ "$TUNNEL_MODE" == "on" ]]; then
  step "tunnel   ${C_DIM}starting cloudflared…${C_RESET}"
  cloudflared tunnel --url "http://localhost:${PORT}" > "$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!

  for _ in {1..30}; do
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" | head -1 || true)
    [[ -n "$URL" ]] && break
    sleep 0.5
  done

  if [[ -z "$URL" ]]; then
    err "konnte tunnel-URL nicht extrahieren"
    tail -20 "$TUNNEL_LOG" | sed "s/^/${PAD}   ${C_DIM}/; s/$/${C_RESET}/"
    exit 1
  fi
  ok "tunnel   ${C_DIM}up · pid $TUNNEL_PID${C_RESET}"
else
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
  if [[ -z "$LAN_IP" ]]; then
    LAN_IP=$(ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}')
  fi
  if [[ -z "$LAN_IP" ]]; then
    warn "LAN-IP nicht gefunden — fallback auf localhost"
    URL="http://localhost:${PORT}"
  else
    URL="http://${LAN_IP}:${PORT}"
  fi
  ok "lokal    ${C_DIM}kein tunnel · LAN-only${C_RESET}"
fi

# ── 4. Clipboard ──────────────────────────────────────────────────────────
CLIP_NOTE=""
if command -v pbcopy >/dev/null 2>&1; then
  printf "%s" "$URL" | pbcopy
  CLIP_NOTE="${C_DIM}↳ in Zwischenablage${C_RESET}"
fi

# ── 5. URL-Box (rounded frame in accent color) ────────────────────────────
echo
LEN=${#URL}
PAD_INNER=3
WIDTH=$((LEN + PAD_INNER * 2))
LINE=$(printf '─%.0s' $(seq 1 "$WIDTH"))
LABEL=" endpoint "
LABEL_LEN=${#LABEL}
HEAD_FILL=$(printf '─%.0s' $(seq 1 $((WIDTH - LABEL_LEN - 2))))
printf "%s${C_ACCENT}╭─${C_RESET}${C_DIM}%s${C_RESET}${C_ACCENT}%s╮${C_RESET}\n" \
  "$PAD" "$LABEL" "$HEAD_FILL"
printf "%s${C_ACCENT}│${C_RESET}%*s${C_BOLD}${C_ACCENT}%s${C_RESET}%*s${C_ACCENT}│${C_RESET}\n" \
  "$PAD" "$PAD_INNER" "" "$URL" "$PAD_INNER" ""
printf "%s${C_ACCENT}╰%s╯${C_RESET}  %s\n" "$PAD" "$LINE" "$CLIP_NOTE"
echo

# ── 5b. QR-Code (optional) ────────────────────────────────────────────────
if command -v qrencode >/dev/null 2>&1; then
  printf "%s${C_DIM}scan with phone:${C_RESET}\n" "$PAD"
  qrencode -t ANSIUTF8 -m 1 "$URL" | sed "s/^/${PAD}/"
  echo
fi

# ── 6. Hinweise + Logs ────────────────────────────────────────────────────
printf "%s${C_TEXT2}▸ App${C_RESET}        ${C_DIM}Settings → Server IP → einfügen → Save → Reconnect${C_RESET}\n" "$PAD"
printf "%s${C_TEXT2}▸ Dashboard${C_RESET}  ${C_DIM}http://localhost:%s${C_RESET}\n" "$PAD" "$PORT"
printf "%s${C_TEXT2}▸ Logs${C_RESET}       ${C_DIM}%s${C_RESET}\n" "$PAD" "$LOG_DIR"
echo
hr
printf "%s${C_DIM}Ctrl+C${C_RESET}  ${C_TEXT2}beendet alles${C_RESET}\n" "$PAD"
hr
echo

# ── 7. Wachhund ───────────────────────────────────────────────────────────
while true; do
  sleep 2
  if [[ -n "$TUNNEL_PID" ]] && ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    err "tunnel ist gestorben"; exit 1
  fi
  if (( WE_STARTED_SERVER )) && ! kill -0 "$SERVER_PID" 2>/dev/null; then
    err "server ist gestorben"; exit 1
  fi
done

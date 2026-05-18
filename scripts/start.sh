#!/usr/bin/env bash
# start.sh — Server + Cloudflare-Tunnel mit hübschem TTY-UI.
# Ctrl+C beendet beide Prozesse sauber.

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Args ──────────────────────────────────────────────────────────────────
# Usage: start.sh [PORT] [--local|--no-tunnel|--tunnel|--ngrok] [--ngrok-domain=X]
# Default: interactive prompt (oder via $ML4SCS_TUNNEL=0/1 im Environment).
PORT="8000"
TUNNEL_MODE=""        # "", "on", "off"
TUNNEL_PROVIDER="auto"  # "auto" (cf→ngrok→lan), "ngrok" (ngrok→lan), "cloudflare" (cf→lan)
NGROK_DOMAIN="${ML4SCS_NGROK_DOMAIN:-}"
for arg in "$@"; do
  case "$arg" in
    --local|--no-tunnel) TUNNEL_MODE="off" ;;
    --tunnel)            TUNNEL_MODE="on" ;;
    --ngrok)             TUNNEL_MODE="on"; TUNNEL_PROVIDER="ngrok" ;;
    --cloudflare)        TUNNEL_MODE="on"; TUNNEL_PROVIDER="cloudflare" ;;
    --ngrok-domain=*)    NGROK_DOMAIN="${arg#--ngrok-domain=}" ;;
    [0-9]*)              PORT="$arg" ;;
    -h|--help)
      echo "Usage: $0 [PORT] [--local|--tunnel|--ngrok|--cloudflare] [--ngrok-domain=X]"
      echo "  --local / --no-tunnel  : nur lokal, kein Tunnel"
      echo "  --tunnel               : Auto-Chain: cloudflare → ngrok → LAN-IP fallback"
      echo "  --cloudflare           : nur cloudflared (Fallback auf LAN-IP wenn fail)"
      echo "  --ngrok                : nur ngrok (Fallback auf LAN-IP wenn fail)"
      echo "  --ngrok-domain=X       : reservierte ngrok-Subdomain (z.B. noah-ml4scs.ngrok-free.app)"
      echo "                           Alternative: ML4SCS_NGROK_DOMAIN=X im Environment"
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
NGROK_LOG="$LOG_DIR/ngrok.log"

SERVER_PID=""
TUNNEL_PID=""
ACTIVE_PROVIDER=""   # gesetzt sobald ein Tunnel/LAN steht: "cloudflare", "ngrok", "lan"
WE_STARTED_SERVER=0

# LAN-IP des Macs ermitteln (en0 wifi, en1 ethernet, ifconfig fallback).
detect_lan_ip() {
  local ip
  ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
  if [[ -z "$ip" ]]; then
    ip=$(ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}')
  fi
  echo "$ip"
}

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
    case "$TUNNEL_PROVIDER" in
      cloudflare) mode_tag="cloudflare → lan" ;;
      ngrok)      mode_tag="ngrok → lan" ;;
      *)          mode_tag="auto: cloudflare → ngrok → lan" ;;
    esac
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

# Werkzeug-Verfügbarkeit nur als Info — Auto-Chain entscheidet selbst was geht.
if [[ "$TUNNEL_MODE" == "on" ]]; then
  HAVE_CF=0; HAVE_NGROK=0
  command -v cloudflared >/dev/null 2>&1 && HAVE_CF=1
  command -v ngrok       >/dev/null 2>&1 && HAVE_NGROK=1
  if [[ "$TUNNEL_PROVIDER" == "cloudflare" && $HAVE_CF -eq 0 ]]; then
    warn "cloudflared nicht installiert — fallback auf LAN-IP"
    printf "%s   ${C_DIM}brew install cloudflared${C_RESET}\n" "$PAD"
  elif [[ "$TUNNEL_PROVIDER" == "ngrok" && $HAVE_NGROK -eq 0 ]]; then
    warn "ngrok nicht installiert — fallback auf LAN-IP"
    printf "%s   ${C_DIM}brew install ngrok && ngrok config add-authtoken <TOKEN>${C_RESET}\n" "$PAD"
  elif [[ "$TUNNEL_PROVIDER" == "auto" && $HAVE_CF -eq 0 && $HAVE_NGROK -eq 0 ]]; then
    warn "weder cloudflared noch ngrok installiert — fallback auf LAN-IP"
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

# ── 3. Tunnel-Chain: cloudflare → ngrok → LAN-IP ──────────────────────────
# Setzt am Ende garantiert $URL und $ACTIVE_PROVIDER; bricht nie ab.
URL=""
TUNNEL_PID=""

# Versuch cloudflared mit 2 Retries gegen trycloudflare 1101.
try_cloudflare() {
  command -v cloudflared >/dev/null 2>&1 || return 1
  local max=2
  for attempt in $(seq 1 $max); do
    if [[ $attempt -eq 1 ]]; then
      step "tunnel   ${C_DIM}starting cloudflared…${C_RESET}"
    else
      step "tunnel   ${C_DIM}cloudflared retry ${attempt}/${max}…${C_RESET}"
    fi
    : > "$TUNNEL_LOG"
    cloudflared tunnel --url "http://localhost:${PORT}" > "$TUNNEL_LOG" 2>&1 &
    local pid=$!
    local url=""
    for _ in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      url=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" | head -1 || true)
      [[ -n "$url" ]] && break
      if grep -qE "failed to unmarshal|error code: 1101" "$TUNNEL_LOG"; then break; fi
      sleep 0.5
    done
    if [[ -n "$url" ]]; then
      URL="$url"
      TUNNEL_PID="$pid"
      ACTIVE_PROVIDER="cloudflare"
      ok "tunnel   ${C_DIM}cloudflared up · pid $pid${C_RESET}"
      return 0
    fi
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    [[ $attempt -lt $max ]] && { warn "trycloudflare 1101 — warte 2s…"; sleep 2; }
  done
  return 1
}

# Versuch ngrok via lokaler Inspector-API (Port 4040 → JSON public_url).
try_ngrok() {
  command -v ngrok >/dev/null 2>&1 || return 1
  step "tunnel   ${C_DIM}starting ngrok…${C_RESET}"
  : > "$NGROK_LOG"
  local args=(http "$PORT" --log=stdout --log-level=info)
  if [[ -n "$NGROK_DOMAIN" ]]; then
    args=(http --domain="$NGROK_DOMAIN" "$PORT" --log=stdout --log-level=info)
  fi
  ngrok "${args[@]}" > "$NGROK_LOG" 2>&1 &
  local pid=$!
  local url=""
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    # Inspector-API erst nach ~1s verfügbar; -m 1 sorgt für schnelles Skippen.
    url=$(curl -sS -m 1 http://127.0.0.1:4040/api/tunnels 2>/dev/null \
          | grep -oE '"public_url":"https://[^"]+"' | head -1 \
          | sed -E 's/.*"public_url":"([^"]+)"/\1/' || true)
    [[ -n "$url" ]] && break
    if grep -qiE "authtoken|ERR_NGROK|failed to start" "$NGROK_LOG"; then break; fi
    sleep 0.5
  done
  if [[ -n "$url" ]]; then
    URL="$url"
    TUNNEL_PID="$pid"
    ACTIVE_PROVIDER="ngrok"
    ok "tunnel   ${C_DIM}ngrok up · pid $pid${C_RESET}"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  # Why: häufigster ngrok-Fail ist fehlender authtoken — direkt anzeigen.
  if grep -qiE "authtoken" "$NGROK_LOG"; then
    warn "ngrok: authtoken fehlt → ${C_DIM}ngrok config add-authtoken <TOKEN>${C_RESET}"
  fi
  return 1
}

# Garantierter Endpunkt: LAN-IP des Macs (oder localhost wenn auch das fehlschlägt).
# Erkennt iPhone-USB-Tethering (172.20.10.x ist Apple's Personal-Hotspot-Subnetz)
# und gibt einen entsprechenden Hinweis.
fallback_lan() {
  local ip
  ip=$(detect_lan_ip)
  if [[ -z "$ip" ]]; then
    warn "LAN-IP nicht gefunden — fallback auf localhost"
    URL="http://localhost:${PORT}"
  else
    URL="http://${ip}:${PORT}"
  fi
  ACTIVE_PROVIDER="lan"
  if [[ "$ip" == 172.20.10.* ]]; then
    ok "lokal    ${C_DIM}iPhone-USB-Tethering erkannt · ${ip}${C_RESET}"
  else
    ok "lokal    ${C_DIM}LAN-IP · kein Tunnel${C_RESET}"
  fi
}

if [[ "$TUNNEL_MODE" == "on" ]]; then
  case "$TUNNEL_PROVIDER" in
    cloudflare)
      try_cloudflare || { warn "cloudflared failed — fallback auf LAN-IP"; fallback_lan; }
      ;;
    ngrok)
      try_ngrok || { warn "ngrok failed — fallback auf LAN-IP"; fallback_lan; }
      ;;
    auto)
      if ! try_cloudflare; then
        warn "cloudflared failed — versuche ngrok…"
        if ! try_ngrok; then
          warn "ngrok failed — fallback auf LAN-IP"
          fallback_lan
        fi
      fi
      ;;
  esac
else
  fallback_lan
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
case "$ACTIVE_PROVIDER" in
  cloudflare) LABEL=" cloudflare " ;;
  ngrok)      LABEL=" ngrok " ;;
  lan)        LABEL=" lan " ;;
  *)          LABEL=" endpoint " ;;
esac
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

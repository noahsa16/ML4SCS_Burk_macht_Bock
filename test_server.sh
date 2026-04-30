#!/usr/bin/env bash
# test_server.sh — verifies the /watch endpoint accepts a batch POST
# Usage: ./test_server.sh [IP]   (defaults to 127.0.0.1)
HOST="${1:-127.0.0.1}"
URL="http://${HOST}:8000/watch"

PAYLOAD='[
  {"ts":1700000000000,"ax":0.01,"ay":-0.02,"az":9.80,"rx":0.001,"ry":0.002,"rz":-0.001},
  {"ts":1700000000020,"ax":0.02,"ay":-0.01,"az":9.81,"rx":0.001,"ry":0.001,"rz":-0.002}
]'

echo "→ POSTing 2-sample test batch to $URL"
curl -s -w "\nHTTP %{http_code}\n" \
     -X POST "$URL" \
     -H "Content-Type: application/json" \
     -d "$PAYLOAD"

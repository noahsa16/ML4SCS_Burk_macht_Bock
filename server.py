import csv, os, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request

app = FastAPI()
CSV_FILE = "watch_data.csv"
FIELDNAMES = [
    "local_ts",
    "session_id",
    "sequence",
    "sample_rate_hz",
    "watch_sent_at",
    "phone_received_at",
    "source",
    "ts",
    "ax",
    "ay",
    "az",
    "rx",
    "ry",
    "rz",
]
total = 0
last_print = time.time()

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

@app.post("/watch")
async def receive_watch(request: Request):
    global total, last_print
    payload = await request.json()
    if isinstance(payload, list):
        envelope = {}
        batch = payload
    else:
        envelope = payload
        batch = envelope.get("samples", [])

    local_ts = datetime.now(timezone.utc).isoformat()
    with open(CSV_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for s in batch:
            w.writerow({
                "local_ts": local_ts,
                "session_id": envelope.get("sessionId"),
                "sequence": envelope.get("sequence"),
                "sample_rate_hz": envelope.get("sampleRateHz"),
                "watch_sent_at": envelope.get("watchSentAt"),
                "phone_received_at": envelope.get("phoneReceivedAt"),
                "source": envelope.get("source"),
                "ts": s.get("ts"),
                "ax": s.get("ax"),
                "ay": s.get("ay"),
                "az": s.get("az"),
                "rx": s.get("rx"),
                "ry": s.get("ry"),
                "rz": s.get("rz"),
            })
    total += len(batch)
    now = time.time()
    if now - last_print >= 1.0:
        print(f"Total samples: {total}", flush=True)
        last_print = now
    return {"ok": True, "samples": len(batch)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

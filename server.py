import csv, os, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request

app = FastAPI()
CSV_FILE = "watch_data.csv"
total = 0
last_print = time.time()

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["local_ts", "ts", "ax", "ay", "az", "rx", "ry", "rz"])

@app.post("/watch")
async def receive_watch(request: Request):
    global total, last_print
    batch = await request.json()
    local_ts = datetime.now(timezone.utc).isoformat()
    with open(CSV_FILE, "a", newline="") as f:
        w = csv.writer(f)
        for s in batch:
            w.writerow([local_ts, s.get("ts"), s.get("ax"), s.get("ay"),
                        s.get("az"), s.get("rx"), s.get("ry"), s.get("rz")])
    total += len(batch)
    now = time.time()
    if now - last_print >= 1.0:
        print(f"Total samples: {total}", flush=True)
        last_print = now
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

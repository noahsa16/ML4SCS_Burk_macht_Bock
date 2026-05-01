# Machine Learning for smart and connected systems — Group Project

## Project Overview
This repository contains our semester-long group project for **Machine Learning for Quantified Self**.

The goal of this repository is to document the full project workflow over the semester:
- problem definition
- data understanding
- preprocessing
- feature engineering
- modeling
- evaluation
- iteration
- final conclusions

---

## Team Members
- Noah Samel
- Ben Kriegsmann
- Tajuddin Snasni
---
Picture will be added after the next seminar
---

## Project Question

Can writing activity (and concentration levels)  be detected and predicted using IMU data from a smartwatch in combination with ground truth data from a Moleskine Smart Pen (NWP-F130)?


---

## Dataset
- **Dataset name:** data/
- **Source:** Moleskine Smart Pen (NWP-F130) and Apple Watch (Series 6)
- **Type of data:** Multivariate time series (pen coordinates, pressure, timestamps + accelerometer, gyroscope) (tbd)
- **Target variable:** Writing activity (binary: writing / not writing), later: "concentration level" (tbd)
- **Important features:** UserAcceleration (x/y/z), RotationRate (x/y/z), pen pressure, stroke duration, pause length (tbd)

---

## Live Data Capture

The live capture stack is:

Apple Watch → iPhone bridge → FastAPI server → `data/raw/watch/{session}_watch.csv`

Moleskine Smart Pen → BLE logger → `data/raw/pen/{session}_pen.csv`

Run the dashboard/server with:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` to start/stop sessions and validate connections.
Use the session description field to record the protocol, for example
`2 min writing, 2 min pause`.

Important quality checks before using a session for modeling:

- Watch samples should contain both accelerometer (`ax`, `ay`, `az`) and gyroscope (`rx`, `ry`, `rz`).
- Watch estimated sample rate should be close to 50 Hz.
- Watch `ts` and pen `timestamp` are the canonical device timestamps. Preprocessing aligns streams on device-relative milliseconds; server/local timestamps are capture metadata and a coarse session anchor.
- The dashboard `Sessions` page and `GET /sessions/quality` endpoint report separate `ml_readiness` and `recording_health` scores; sync confidence is only an optional calibration diagnostic.

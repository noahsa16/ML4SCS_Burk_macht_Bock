Week 01 Report — Machine Learning for Smart and Connected Systems
Weekly Goal
Set up project, validate that the Moleskine Smart Pen works with available SDKs, and collect first test data.

Work Done This Week
Project Setup
Project Question:
Can writing activity and concentration levels be detected using sensor data from a Moleskine Smart Pen, and later in combination with an Apple Watch?
Hardware:

Moleskine Smart Pen (NWP-F130), connects via Bluetooth Low Energy
Data received either through NeoSmartpen Web SDK 2.0 (Chrome) or directly via Python

Tools: Python, bleak (BLE library), NeoSmartpen Web SDK 2.0, GitHub, PyCharm
Data Work

Connected the pen to the Web SDK Sample App — works fully
Pen streams data at ~80-90 Hz
Each data point contains: timestamp, x, y, pressure, dot_type (PEN_DOWN/PEN_MOVE/PEN_UP), tilt_x, tilt_y
First test experiment: one team member wrote a text concentrated (no distractions) and unconcentrated (while talking to teammates)
Collected ~10,700 data points (concentrated) and ~10,000 data points (unconcentrated)

Technical Work: Python BLE Logger

Reverse engineered the NeoSmartpen BLE protocol by analyzing the Web SDK 2.0 source code (TypeScript)
Identified the relevant GATT services, characteristics and UUIDs used for data transmission
Built a Python script using the bleak library that connects directly to the pen via Bluetooth
The script decodes the raw BLE byte packets into structured dot objects and logs them live to CSV
This means we no longer depend on a browser — data collection runs fully in Python

Experiments:
Pen Connection via Web SDK: We connected the NWP-F130 via the Web SDK in Chrome. The full data stream was confirmed — the pen is compatible despite not being in the official support list.
Python BLE Logger: We reverse engineered the SDK protocol and built a Python logger using bleak. Live dot logging directly in Python works — no browser needed.
First Data Collection: One subject wrote the same text concentrated and unconcentrated. This produced two clean CSV files with ~10k data points each.


Key Insights:

The pen delivers rich data (pressure, tilt, precise timestamps) that should be useful for ML
Having a pure Python logger is a big advantage — no browser dependency, easier to integrate into the ML pipeline later
We can start with pen-only analysis before adding Apple Watch data

Plan for Next Week:

Collect data from all 3 team members + additional volunteers
Design a study protocol with standardized text and session logging
Start exploring the data and computing first features in Python
Look into Apple Watch data collection via Sensor Logger app


Contributions:

Noah: Project setup, SDK research and testing, Python BLE logger, GitHub setup, data collection
Ben: Watch Data Testing and Logging
Taji: First test subject, data collection

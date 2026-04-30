# Week 02 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

---

## Work Done This Week

### Project Setup

**Project Question:**  
Can writing activity and concentration levels be detected using sensor data from a Moleskine Smart Pen as ground truth, and later in combination with an Apple Watch?

**Hardware:**
- Moleskine Smart Pen (NWP-F130), connected via Bluetooth Low Energy
- Apple Watch Series 7
- Google Watch

**Data Sources / Interfaces:**
- NeoSmartpen Web SDK 2.0 in Chrome
- Direct BLE connection via Python

**Tools:**
- Python
- `bleak` BLE library
- NeoSmartpen Web SDK 2.0
- GitHub
- PyCharm

### Data Work

- Saved Apple Watch sensor data as CSV using SensorLogger

### Technical Work

---

## Experiments

---

## Key Insights

- SensorLogger works well with Apple Watch
- There are many relevant research papers related to this topic

---

## Plan for Next Week

- To be determined on Thursday during the weekly meeting before the seminar

---

## Contributions

### Noah

- Read relevant papers:
  - [IMWUT 2020 Paper](https://download.cmutschler.de/publications/2020/IMWUT2020.pdf)
  - [Springer Paper](https://link.springer.com/content/pdf/10.1007/978-3-031-59091-7_12.pdf)
- Exchanged ideas with Gerrit Soltau, a former seminar participant from a higher semester
- Connected Apple Watch via SensorLogger
- Saved Apple Watch data as CSV

### Ben

-

### Taji

- Implemented a preprocessing pipeline for smart pen sensor data to transform raw CSV input into a machine-learning-ready dataset.
- Selected relevant variables, removed invalid placeholder values, and derived the features pressure, distance, and speed from the original pen data.
- Created a binary target label (label_writing) to distinguish between writing and non-writing events.
- Verified the preprocessing output by checking dataset shape, missing values, feature output, and class distribution.

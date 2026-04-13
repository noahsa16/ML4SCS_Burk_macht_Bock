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
- Member 1
- Member 2
- Member 3

---

## Project Question
Write your main research question here.

**Example:**  
Can wearable-device and self-tracking data be used to predict sleep quality, stress, activity level, or another quantified-self outcome?

---

## Dataset
- **Dataset name:**  
- **Source:**  
- **Type of data:**  
- **Target variable:**  
- **Important features:**  

> Keep using the same project dataset across the semester unless your tutor approves a change.

---

## Repository Structure

```text
.
├── README.md
├── .gitignore
├── requirements.txt
├── data/
│   ├── raw/
│   └── processed/
├── notebooks/
├── src/
├── reports/
├── results/
│   ├── plots/
│   └── metrics/
```

### Folder Purpose
- `data/raw/` → original data files
- `data/processed/` → cleaned or transformed data
- `notebooks/` → exploratory work, experiments, model development
- `src/` → reusable Python scripts
- `reports/` → weekly progress reports
- `results/plots/` → visual outputs
- `results/metrics/` → evaluation results

---

## Weekly Documentation Rule
Each week, the group must submit a short project update in the `reports/` folder.

File naming format:
- `week01.md`
- `week02.md`
- `week03.md`

Each weekly report should describe:
- what was attempted
- what changed from the previous week
- what results were obtained
- what problems were faced
- what the next steps are

---

## Suggested Workflow
1. Define the research problem
2. Understand and clean the data
3. Perform exploratory analysis
4. Build a baseline model
5. Improve the model iteratively
6. Compare experiments
7. Draw conclusions
8. Prepare final presentation/report

---

## Experiment Tracking
Groups are encouraged to maintain a running experiment table.

| Version | Main Change | Model | Metric | Notes |
|--------|-------------|-------|--------|-------|
| v1 | Baseline | TBD | TBD | Initial model |
| v2 | Added features | TBD | TBD | Improved feature set |

---

## How to Run
```bash
pip install -r requirements.txt
```

Then start with the notebooks or scripts in `src/`.

---

## Contribution Expectations
Each group member should contribute regularly through:
- commits
- notebook work
- code
- documentation
- analysis
- interpretation

Use meaningful commit messages such as:
- `add baseline model`
- `clean missing values`
- `write week03 report`
- `compare random forest and xgboost`

Avoid commit messages like:
- `final`
- `new version`
- `stuff`

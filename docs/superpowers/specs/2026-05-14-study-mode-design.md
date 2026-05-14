# Study Mode — Design Spec

**Date:** 2026-05-14
**Author:** Noah (with Claude)
**Status:** Approved for planning

---

## 1 · Goal

Add a **Study Mode** to the web dashboard that drives a protocol-based data-collection session: the proband sees the task they should be doing on-screen (with a per-task timer); the experimenter retains full control over the dashboard and can override task transitions. Task boundaries are written to a per-session marker CSV so later analysis can slice IMU / pen data by activity type.

This replaces the current ad-hoc workflow where the experimenter verbally announces task transitions, which produces 10–30 s of human jitter on every annotation boundary and isn't machine-readable.

## 2 · Non-goals

- **Marker-derived training labels.** `label_writing` from the pen remains ground truth. `task_id` is metadata for stratified evaluation and post-hoc analysis only — not a training signal.
- **Multi-device support.** Single browser, single screen. No separate proband-tablet.
- **Marker-driven LOSO variants.** No `--by task` axis in `train_loso.py`. Per-task confusion matrices in evaluation are a manual notebook exercise, not a built-in flag.
- **Live editing of protocols in the UI.** Protocols are versioned JSON files in the repo. Editing happens in a text editor + commit.
- **Backwards-modify existing sessions.** S029/S031/S037/S039 keep working untouched — they simply have `task_id = NaN` after the merge step.

## 3 · Architecture decision

**Server-side state machine.** The Python server owns the protocol state (current task, remaining time, paused/running), ticks in the existing 1 s `_status_loop`, broadcasts via the existing WebSocket, and writes marker CSV rows directly with `server_received_ms` as the timestamp — same clock as the watch / pen CSVs. The frontend renders the current state, doesn't track its own.

Rationale:
1. Existing server architecture is already server-driven (`SessionState`, status loop, WS broadcast) — protocol logic fits naturally into the same module shape.
2. Markers written server-side share the watch/pen wall-clock — no asof-join drift.
3. Robust against browser refresh, slow connection, tab backgrounding (Chrome throttles client timers to 1 Hz).
4. VL override controls are standard HTTP POSTs — trivial to add.

Alternatives considered: client-side state machine (loses sync on refresh / Chrome throttling), hybrid (over-engineered).

## 4 · Server-side

### 4.1 New module: `src/server/study.py`

Pure Python state machine (no FastAPI imports — testable in isolation). Responsibilities:

- Load protocol JSON from `study_protocols/{id}.json`.
- Randomize task order per session (seeded by `session_id` for reproducibility).
- Track current state: `idle | pre_task | running | paused | done`.
- Tick: advance state by elapsed seconds, emit transition events.
- Emit marker rows to be persisted by `csv_io.py`.

### 4.2 Extended modules

- `src/server/state.py` — `SessionState` gains `study: StudyState | None`.
- `src/server/csv_io.py` — new `write_marker(session_id, row)` writing to `data/raw/markers/{session}_markers.csv`. Creates the file with header on first write.
- `src/server/config.py` — `MARKER_FIELDNAMES`, `MARKERS_DIR` paths.
- `src/server/broadcast.py` — `_status_payload()` includes `study` field when active.
- `src/server/models.py` — Pydantic schemas `StudyProtocol`, `StudyTask`, `StudyStartBody`, `StudyState`.

### 4.3 New router: `src/server/routes/study.py`

| Endpoint                | Body / Query                          | Behavior |
|-------------------------|---------------------------------------|----------|
| `POST /study/start`     | `{protocol_id, person_id, description}` | Create session + initialize study state machine. Returns `{session_id, protocol, randomized_order}`. |
| `POST /study/next`      | —                                     | VL override: end current task immediately, advance. Writes `task_end` + next `task_start` marker. |
| `POST /study/pause`     | —                                     | Toggle pause / resume. Writes `pause` or `resume` marker. While paused, task timer does not advance. |
| `POST /study/abort`     | —                                     | End study state machine. Session continues as free-recording (no auto-stop). Writes `abort` + `study_end` marker. |
| `GET /study/protocols`  | —                                     | List `study_protocols/*.json` with id + name. |

### 4.4 Status payload extension

```jsonc
{
  // ...existing fields (session_active, watch_samples, ...)
  "study": {
    "active": true,
    "state": "running",          // idle | pre_task | running | paused | done
    "task_index": 1,
    "task_total": 6,
    "task": {
      "id": "math",
      "label": "Mathe-Aufgaben",
      "category": "writing",
      "instruction": "...",
      "content_type": "list",
      "content": ["17 × 14 = ?", "(3x + 5)(x − 2)", "..."]
    },
    "task_remaining_ms": 167000,
    "task_duration_ms": 240000,
    "protocol_id": "v1"
  }
}
```

The `study` field is **always present** in the status payload; when no study is active it carries `{"active": false}` and no other keys. Always-present is easier for the frontend than checking for an absent field on every tick.

## 5 · Frontend

### 5.1 Recording-page mode toggle

A 2-state segmented control near the existing Person / Description inputs:

```
[ free recording ] [ study mode ]
```

- Default: `free recording`. START calls `/session/start` as today.
- `study mode`: a Protocol dropdown (populated from `GET /study/protocols`) appears between Description and START. START button becomes `START STUDY`, calls `/study/start`.

The toggle only affects **what `/session/start` becomes**. After a session is running, the displayed view is driven entirely by `s.study.active` from the server status — single source of truth, no local view-mode state to drift.

### 5.2 Study view sub-states

Rendered inside the Recording page (no tab change). Each sub-state corresponds to a server `study.state` value:

| Server state | Frontend rendering |
|--------------|--------------------|
| `pre_task`   | Centered task title + large countdown ("starts in 0:03"). Background slash glyph. |
| `running`    | Topbar with task title + shrunken timer + progress bar; task content full-screen. VL override panel bottom-right. |
| `paused`     | Same as `running` but timer pulses orange and a banner "Paused — VL override" overlays. |
| `done`       | "Studie abgeschlossen ✓" centered, auto-clears after 5 s. Session continues until VL stops it. |

### 5.3 Animation `pre_task → running`

FLIP technique (First-Last-Invert-Play) via CSS `transform` for GPU-acceleration:

- Large central timer scales to `0.27` and translates to top-right topbar slot.
- Task title scales to `0.32` and translates to top-left.
- Background `/` glyph fades to `opacity: 0.03`.
- Task content fades from `0 → 1` with `translateY(8px → 0)`.
- Duration `320 ms`, easing `cubic-bezier(0.4, 0, 0.2, 1)`.

`pre_task` is triggered server-side 3 s before each `running` transition (configurable via protocol `pre_task_seconds`).

### 5.4 VL override panel

Floating bottom-right, only visible when `s.study.active`. Three small buttons: `[ ⏸ Pause ] [ ⏭ Next ] [ ✕ Abort ]`. Keyboard shortcuts: `Space` = pause/resume, `→` = next, `Esc` = abort. Deliberately small + peripheral so the proband doesn't accidentally click.

### 5.5 Files

| File | Change |
|------|--------|
| `static/views/recording.html` | Add mode-toggle + protocol dropdown + study view containers (hidden by default). |
| `static/js/pages/recording.js` | Extend `onStatus()` to branch on `s.study.active`; new `renderStudyView()` + animation logic; new `toggleSession()` branching on selected mode. |
| `static/css/study-mode.css` | New stylesheet matching `base.css` design tokens. |
| `tests/test_dashboard_static.py` | Add new CSS / JS / view paths to the 404 parametrize list. |

### 5.6 App topbar during study

The existing app topbar (Tabs, status pills) stays visible. The experimenter must be able to switch to Sessions / Settings / Connections during a run without losing study context.

## 6 · Protocol format

`study_protocols/{id}.json`. **Concrete v1 protocol** (~15 min total, schedule pattern `W-P-W-P-W`):

```json
{
  "id": "v1",
  "name": "ML4SCS Study Protocol v1",
  "pre_task_seconds": 3,
  "randomize": true,
  "interleave": "writing_with_pauses",
  "tasks": [
    {
      "id": "abschreiben",
      "label": "Text abschreiben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Schreibe den folgenden Text auf Papier ab.",
      "content_type": "text",
      "content": "Lorem ipsum dolor sit amet, consectetur adipiscing elit..."
    },
    {
      "id": "math",
      "label": "Mathe-Aufgaben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Bearbeite die Aufgaben in deinem üblichen Tempo.",
      "content_type": "list",
      "content": ["17 × 14 = ?", "Vereinfache: (3x + 5)(x − 2)", "..."]
    },
    {
      "id": "free_writing",
      "label": "Freies Schreiben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Schreibe einen frei gewählten Text — z. B. ein kurzer Erlebnisbericht.",
      "content_type": "text",
      "content": "Schreibe einfach drauf los — kein Thema vorgegeben."
    },
    {
      "id": "pause",
      "label": "Pause",
      "category": "idle",
      "duration_seconds": 90,
      "instances": 2,
      "instruction": "Lege den Stift weg. Mach was du willst — strecken, trinken, kurz reden. Hauptsache: du schreibst nicht.",
      "content_type": "text",
      "content": "Pause. Stift kann auf dem Tisch liegen bleiben."
    }
  ]
}
```

Schedule: `abschreiben` + `math` + `free_writing` + 2× `pause` = 5 slots × ~4 min ≈ 15 min total (3 × 240 s writing + 2 × 90 s pause = 900 s = 15 min, plus 5 × 3 s pre-task transitions ≈ 15 s).

### 6.1 Randomization

Per session, seeded by `hash(session_id)`. Scheduler procedure:

1. **Expand instances.** Each task in the JSON has an optional `instances` field (default `1`). A task with `instances: 2` becomes two scheduled slots that share the same content but get distinct `task_index` values in markers. For v1: `pause` has `instances: 2`, all writing tasks have `instances: 1`.
2. **Group by category.** Build `W = [writing tasks…]` and `I = [idle tasks…]` from the expanded list.
3. **Shuffle each group** independently with the seed.
4. **Interleave** per the `interleave` field:
   - `writing_with_pauses` (default): weave `W₁ I₁ W₂ I₂ W₃ I₃ …`. If `|W| > |I|`, trailing writing tasks concatenate at the end. If `|I| > |W|`, the opposite. For v1: `|W| = 3, |I| = 2 → W₁ I₁ W₂ I₂ W₃` — perfect alternation.
   - `shuffled`: single shuffle ignoring category. Escape hatch, not the default — it can violate temporal-split / class-distribution assumptions.

Seed function and scheduler exposed in `study.py` so tests can pin behavior.

### 6.2 Content rendering

`content_type` discriminates the proband-view renderer:

| `content_type` | Content shape | Rendering |
|----------------|---------------|-----------|
| `text`         | string        | Single paragraph block. |
| `list`         | array         | Numbered list, large readable font. |
| `image`        | URL / path    | Centered image (future, not v1). |

`instruction` is a single line of text always rendered above the content.

## 7 · Marker CSV format

`data/raw/markers/{session}_markers.csv`:

```
timestamp_ms, event,         task_id,      task_name,         task_index, task_category, protocol_id
1715600070123, study_start,  ,             ,                   ,           ,              v1
1715600070123, task_start,   abschreiben,  Text abschreiben,  1,          writing,       v1
1715600310123, task_end,     abschreiben,  Text abschreiben,  1,          writing,       v1
1715600313123, task_start,   pause_talk,   Pause — Gespräch, 2,          idle,          v1
1715600373123, pause,        pause_talk,   Pause — Gespräch, 2,          idle,          v1
1715600380123, resume,       pause_talk,   Pause — Gespräch, 2,          idle,          v1
...
1715601510123, study_end,    ,             ,                   ,           ,              v1
```

`event` ∈ {`study_start`, `task_start`, `task_end`, `pause`, `resume`, `abort`, `study_end`}.

`pause` / `resume` events let downstream computation of *effective* task duration (`task_end - task_start - sum(pause_durations)`).

Timestamp is `server_received_ms` — identical clock to watch/pen CSVs, no asof drift.

## 8 · ML pipeline integration — light touch

`task_id` is **analysis metadata**, not a training label. The ML pipeline gains the column but does not change behavior for binary writing detection.

- `src/merge/merge.py`: optional asof-join of `data/raw/markers/{session}_markers.csv` onto the watch-base merge. Adds `task_id`, `task_category` columns to `{session}_merged.csv`. If no markers file: columns remain `NaN`, merge runs identically to today.
- `src/features/windows.py`: window-level `task_id` = mode of sample-level `task_id` over the window. Same: `NaN` if missing.
- Existing sessions (S029, S031, S037, S039) remain trainable unchanged — `task_id` is just an empty column they don't have.
- `train_loso.py`: no new flags. Per-task confusion matrices are a manual notebook exercise (`results.groupby("task_id").apply(confusion_matrix)`).

The point is: the **data side** is wired correctly from day one, so that any later analysis ("does Mathe look different from Freitext in the model's confusion matrix?") works without retro-fitting the pipeline.

## 9 · Testing

| File | Coverage |
|------|----------|
| `tests/test_study_state_machine.py` | State transitions (idle → pre_task → running → pre_task → done), pause/resume mechanics, mock clock. |
| `tests/test_protocol_loader.py` | JSON schema validation; randomization reproducibility (same seed → same order). |
| `tests/test_markers_csv.py` | Marker schema; effective-duration computation across pause/resume events. |
| `tests/test_study_endpoints.py` | FastAPI TestClient: `/study/start → /next → /pause → /resume → /abort` happy path. |
| `tests/test_merge.py` (extend)   | Watch-base merge with + without markers file; backwards-compat for sessions without markers. |
| `tests/test_dashboard_static.py` (extend) | New CSS / JS / view files reachable. |

## 10 · Open questions — for plan-time, not blocking

- **Concrete content for writing tasks**: which exact math problems, which abschreib-text. Decided by the team, lives in `study_protocols/v1.json`. Placeholder content in Section 6 is fine for scaffolding.
- **Multiple protocol versions**: v1 for pilot, v2 for main study? Or one evolving `v1` with git history? Lean toward separate files so the `protocol_id` recorded per session uniquely identifies what ran.
- **Behaviour on session-stop mid-protocol**: VL hits the master STOP button → study state machine should `abort` cleanly and write a final marker before the session CSV finalizes.
- **Pilot-run timing verification**: 240 s writing + 90 s pause feels right, but a single pilot session might suggest adjustments. Spec'd durations are first-best-guess.

**Resolved by user 2026-05-14:**
- ✓ Protocol shape: 3 writing tasks (`abschreiben`, `math`, `free_writing`) + 1 idle task (`pause`) at 2 instances = `W-P-W-P-W` schedule.
- ✓ Pause variety: single generic pause type. Instruction is open ("strecken, trinken, kurz reden — Hauptsache nicht schreiben").
- ✓ Total session length: ~15 min.

## 11 · Out of scope (explicitly)

- Custom protocols per subject. All subjects run the same protocol; only task order varies per session_id seed.
- Live remote monitoring (e.g., experimenter on a different machine than the proband). Single-screen toggle only.
- Audio prompts / TTS. Visual cues only.
- Bilingual UI. German strings only for now (proband-facing); English remains the developer language.

---

**Approval gates:**

1. ✓ Architecture (Section 3) — server-side state machine confirmed.
2. ✓ Server design (Section 4) — endpoints + state model confirmed.
3. ✓ Frontend design (Section 5) — toggle pattern + animation confirmed.
4. ✓ Marker format + ML scope (Sections 7–8) — labels as analysis metadata, not training signal.

Ready for implementation planning.

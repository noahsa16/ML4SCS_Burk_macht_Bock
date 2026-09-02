# On-Device-Deployment Phase 1 — Spike + Core-ML-Parität — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Messen, ob `CMSensorRecorder` auf der Series 7 verwertbare Daten liefert, und beide Deployment-Modelle so nach Core ML bringen, dass ihre Gleichheit mit PyTorch auf Mac, iPhone und Watch bewiesen ist.

**Architecture:** Zwei unabhängige Stränge, die sich am Ende treffen. Strang A (Spike) nutzt den bestehenden WCSession-Command-Pfad: iPhone-Knopf → `MotionManager.handleCommand` auf der Watch → Kennzahlen zurück; die Urteilslogik liegt bewusst am iPhone, wo sie unit-testbar ist. Strang B konvertiert die PyTorch-Checkpoints in einem isolierten venv nach Core ML und erzeugt Golden-Vektoren, die anschliessend auf allen drei Ebenen dieselbe Antwort liefern müssen.

**Tech Stack:** Python 3.13 (torch 2.9, coremltools 9.0 in separatem venv), Swift 5 / SwiftUI, Core ML, WatchConnectivity, CoreMotion, Swift Testing, pytest.

**Spec:** `docs/specs/2026-08-28-on-device-deployment-design.md`

## Global Constraints

- **Modelle:** aktiv `tcn_bigru`, 6 Kanäle `[ax, ay, az, rx, ry, rz]`; passiv `tcn6`, 3 Kanäle `[x, y, z]` als `(ax+gx, ay+gy, az+gz)`. Beide **250 Samples @ 50 Hz**, Layout `(1, 250, n_channels)`.
- **Kein Z-Score, kein HMM, keine Feature-Extraktion.** Rohe Fenster gehen ins Netz. Entscheidungsschwelle **0,5**.
- **Compute-Konfiguration FP32, festgenagelt** — in Parität und Produktion. Swift: `MLModelConfiguration.computeUnits = .cpuOnly`. Python: `ct.precision.FLOAT32`.
- **Paritätstoleranz:** absolute Logit-Abweichung ≤ `1e-4`.
- **`coremltools` NIE in die Projektumgebung installieren** — ausschliesslich in `.venv-coreml/`. Präzedenzfall: die `aeon`-Installation hat numpy auf 2.3.5 heruntergestuft.
- **`weights_only=False`** ist beim Checkpoint-Laden nötig (`meta["torch_version"]` ist ein `TorchVersion`-Objekt) und **nur für eigene, im Repo erzeugte Checkpoints zulässig**.
- **Python-Pfade** relativ zum Repo-Root via `ROOT = Path(__file__).resolve().parents[N]`. Keine absoluten Pfade.
- **`pytest tests/` muss nach jeder Task grün bleiben** (aktuell 749 Tests).
- **Xcode-Target-Zugehörigkeit ergibt sich aus dem Ordner** (`PBXFileSystemSynchronizedRootGroup`): `WatchStreamer/` → iPhone, `WatchStreamer Watch App/` → Watch, `ScrybeTests/` → Test-Bundle des iPhone-Targets. **Keine pbxproj-Bearbeitung.**
- **Swift-Tests** nutzen Swift Testing (`import Testing`, `@Suite`, `@Test`, `#expect`), nicht XCTest — siehe `ScrybeTests/DataFlowEvaluatorTests.swift`.
- **Die Studien-Pipeline bleibt unberührt:** kein Eingriff in `server.py`, `src/server/`, `pen_logger.py`, Study Mode.
- **Ein Commit pro Task**, Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`). **Subject maximal 50 Zeichen**, Imperativ, ohne Punkt — die vorgegebenen Nachrichten halten das ein und werden wortgleich übernommen.
- **`models/*` ist gitignored.** Checkpoints und Zwischenartefakte werden nicht committet; die in die Xcode-Ordner kopierten `.mlpackage` und die Fixtures unter `tests/fixtures/` schon.

---

## File Structure

**Neu (Python):**

| Datei | Verantwortung |
|---|---|
| `src/deploy/__init__.py` | Paket-Marker |
| `src/deploy/checkpoint.py` | Checkpoint → einsatzbereites `nn.Module` + normalisierte Metadaten. Einziger Ort, der `weights_only=False` benutzt. |
| `src/deploy/golden.py` | Serialisierungsformat der Golden-Vektoren (base64-float32), von Generator und Test geteilt |
| `scripts/pipeline/make_golden_windows.py` | zieht Fenster aus echten Sessions, schreibt Fixtures |
| `scripts/pipeline/export_coreml.py` | Checkpoint → `.mlpackage` (läuft im `.venv-coreml`) |
| `tests/test_deploy_checkpoint.py` | Tests für `src/deploy/checkpoint.py` |
| `tests/test_deploy_golden.py` | Tests für das Fixture-Format + P1-Parität |
| `requirements-coreml.txt` | Abhängigkeiten des isolierten venv |

**Neu (Swift):**

| Datei | Target | Verantwortung |
|---|---|---|
| `WatchStreamer/Scrybe/Logic/SensorProbeEvaluator.swift` | iPhone | bewertet die Watch-Kennzahlen gegen die Spike-Kriterien — reine Logik, keine Frameworks |
| `WatchStreamer/Scrybe/Logic/ScrybeModel.swift` | iPhone | dünner Core-ML-Wrapper: Fenster rein, Logit raus |
| `WatchStreamer Watch App/SensorProbe.swift` | Watch | `CMSensorRecorder` ansteuern, rohe Kennzahlen erheben — **keine** Urteilslogik |
| `WatchStreamer Watch App/WatchScrybeModel.swift` | Watch | Core-ML-Wrapper für `ScrybePassive` |
| `ScrybeTests/SensorProbeEvaluatorTests.swift` | Tests | Urteilslogik ohne Hardware |
| `ScrybeTests/ScrybeModelParityTests.swift` | Tests | P2 — Golden-Vektoren auf dem iPhone |

**Modifiziert (Swift):**

| Datei | Änderung |
|---|---|
| `WatchStreamer Watch App/MotionManager.swift` | drei `case` im `handleCommand`-Switch: `sensor_probe_start`, `sensor_probe_report`, `parity_check` |
| `WatchStreamer/Admin/AdminPanelView.swift` | Abschnitt „On-Device-Diagnose" mit drei Knöpfen + Ergebnisanzeige |
| `WatchStreamer/ServerCommandListener.swift` | drei Sende-Methoden analog `drainWatchSpill()` |
| Watch-App `Info.plist` | `NSMotionUsageDescription` |

**Artefakte (nicht Code):**

| Pfad | Inhalt |
|---|---|
| `tests/fixtures/golden_windows_active.json` | 24 Fenster + PyTorch-Logits, `tcn_bigru` |
| `tests/fixtures/golden_windows_passive.json` | 24 Fenster + PyTorch-Logits, `tcn6` |
| `WatchStreamer/ScrybeActive.mlpackage` | aktives Modell, iPhone-Target |
| `WatchStreamer Watch App/ScrybePassive.mlpackage` | passives Modell, Watch-Target |
| `WatchStreamer Watch App/golden_windows_passive.json` | Kopie der Fixture als Bundle-Ressource für P3 |

---

# Teil A — Spike: `CMSensorRecorder`

> **Zuerst starten.** Task 4 braucht 12 Stunden Wandzeit. Wer A1–A3 zuerst abschliesst und die Aufzeichnung startet, kann Teil B laufen lassen, während die Uhr misst.

### Task 1: Urteilslogik `SensorProbeEvaluator`

Reine Bewertungslogik für die Kennzahlen, die die Watch zurückliefert. Liegt am iPhone, weil nur dieser Ordner vom Test-Target erreichbar ist. Kein CoreMotion-Import, keine Nebenwirkungen.

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/SensorProbeEvaluator.swift`
- Test: `watch_streamer/ScrybeTests/SensorProbeEvaluatorTests.swift`

**Interfaces:**
- Produces: `struct SensorProbeStats` (Rohkennzahlen von der Watch), `struct SensorProbeVerdict` (Urteil), `enum SensorProbeCheck` (die einzelnen Kriterien), `SensorProbeEvaluator.evaluate(_ stats: SensorProbeStats) -> SensorProbeVerdict`
- Consumed by: Task 3 (Anzeige), Task 2 liefert die Rohkennzahlen

- [ ] **Step 1: Write the failing test**

```swift
// watch_streamer/ScrybeTests/SensorProbeEvaluatorTests.swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("SensorProbeEvaluator")
struct SensorProbeEvaluatorTests {

    /// 1 Stunde bei sauberen 50 Hz: 180_000 Samples, alle Intervalle 20 ms.
    private func healthy(durationSeconds: Double = 3600) -> SensorProbeStats {
        let n = Int(durationSeconds * 50)
        return SensorProbeStats(
            sampleCount: n,
            firstTimestamp: 0,
            lastTimestamp: durationSeconds,
            requestedSeconds: durationSeconds,
            intervalBucketsMs: [0: 0, 20: n - 1, 40: 0, 100: 0, 1000: 0],
            maxGapSeconds: 0.02,
            nonMonotonicCount: 0,
            fetchReturnedNil: false
        )
    }

    @Test("saubere Aufzeichnung besteht alle Kriterien")
    func healthyPasses() {
        let v = SensorProbeEvaluator.evaluate(healthy())
        #expect(v.passed == true)
        #expect(v.failures.isEmpty)
    }

    @Test("nil-Rueckgabe ist der dokumentierte Ausfallmodus")
    func nilFetchFails() {
        var s = healthy()
        s.fetchReturnedNil = true
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.passed == false)
        #expect(v.failures.contains(.fetchReturnedNil))
    }

    @Test("nicht-monotone Zeitstempel schlagen fehl")
    func nonMonotonicFails() {
        var s = healthy()
        s.nonMonotonicCount = 1
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.nonMonotonic))
    }

    @Test("Rate unterhalb 45 Hz schlaegt fehl")
    func lowRateFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 40)   // 40 Hz
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.effectiveRate))
    }

    @Test("Rate oberhalb 55 Hz schlaegt fehl")
    func highRateFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 60)
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.effectiveRate))
    }

    @Test("mehr als ein Prozent lange Intervalle schlaegt fehl")
    func intervalTailFails() {
        var s = healthy()
        let n = s.sampleCount - 1
        s.intervalBucketsMs = [0: 0, 20: n - n / 50, 40: n / 50, 100: 0, 1000: 0]  // 2 %
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.intervalTail))
    }

    @Test("Coverage unter 98 Prozent schlaegt fehl")
    func coverageFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 50 * 0.9)
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.failures.contains(.coverage))
    }

    @Test("Coverage wird gegen die angeforderte Dauer gerechnet, nicht gegen die gelieferte Spanne")
    func coverageUsesRequestedDuration() {
        // Why: eine Aufzeichnung, die nach 10 min abbricht, hat ueber ihre
        // eigene Spanne perfekte Coverage — der Ausfall zeigt sich nur gegen
        // die angeforderten 3600 s.
        var s = healthy(durationSeconds: 600)
        s.requestedSeconds = 3600
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.coverage))
    }

    @Test("Verdikt zaehlt mehrere Fehlschlaege gleichzeitig")
    func multipleFailures() {
        var s = healthy()
        s.nonMonotonicCount = 3
        s.sampleCount = Int(3600 * 20)
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.failures.count >= 2)
        #expect(v.passed == false)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd watch_streamer && xcodebuild test -project WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ScrybeTests/SensorProbeEvaluatorTests 2>&1 | tail -20
```
Expected: FAIL — `cannot find 'SensorProbeStats' in scope`.

- [ ] **Step 3: Write minimal implementation**

```swift
// watch_streamer/WatchStreamer/Scrybe/Logic/SensorProbeEvaluator.swift
import Foundation

/// Rohkennzahlen einer CMSensorRecorder-Stichprobe, erhoben auf der Watch.
/// Enthaelt bewusst kein Urteil — die Bewertung liegt in SensorProbeEvaluator,
/// damit sie ohne Hardware testbar bleibt.
struct SensorProbeStats: Codable, Equatable {
    var sampleCount: Int
    /// Sekunden seit Referenzdatum, erstes und letztes geliefertes Sample.
    var firstTimestamp: Double
    var lastTimestamp: Double
    /// Dauer, die beim Aufzeichnungsauftrag angefordert wurde.
    var requestedSeconds: Double
    /// Histogramm der Abstaende aufeinanderfolgender Samples. Schluessel ist
    /// die untere Bucket-Grenze in Millisekunden.
    var intervalBucketsMs: [Int: Int]
    var maxGapSeconds: Double
    var nonMonotonicCount: Int
    var fetchReturnedNil: Bool
}

enum SensorProbeCheck: String, Codable, CaseIterable {
    case fetchReturnedNil
    case nonMonotonic
    case effectiveRate
    case intervalTail
    case coverage
}

struct SensorProbeVerdict: Equatable {
    var passed: Bool
    var failures: [SensorProbeCheck]
    var effectiveRateHz: Double
    var coverage: Double
    var longIntervalShare: Double
}

enum SensorProbeEvaluator {
    static let nominalRateHz = 50.0
    static let minRateHz = 45.0
    static let maxRateHz = 55.0
    /// Intervalle ab dieser Grenze gelten als „lang" (Spec §6).
    static let longIntervalBucketMs = 40
    static let maxLongIntervalShare = 0.01
    static let minCoverage = 0.98

    static func evaluate(_ s: SensorProbeStats) -> SensorProbeVerdict {
        var failures: [SensorProbeCheck] = []

        let span = max(s.lastTimestamp - s.firstTimestamp, 0)
        let rate = span > 0 ? Double(s.sampleCount - 1) / span : 0
        let expected = s.requestedSeconds * nominalRateHz
        let coverage = expected > 0 ? Double(s.sampleCount) / expected : 0

        let intervalTotal = s.intervalBucketsMs.values.reduce(0, +)
        let longCount = s.intervalBucketsMs
            .filter { $0.key >= longIntervalBucketMs }
            .values.reduce(0, +)
        let longShare = intervalTotal > 0 ? Double(longCount) / Double(intervalTotal) : 0

        if s.fetchReturnedNil { failures.append(.fetchReturnedNil) }
        if s.nonMonotonicCount > 0 { failures.append(.nonMonotonic) }
        if rate < minRateHz || rate > maxRateHz { failures.append(.effectiveRate) }
        if longShare > maxLongIntervalShare { failures.append(.intervalTail) }
        if coverage < minCoverage { failures.append(.coverage) }

        return SensorProbeVerdict(
            passed: failures.isEmpty,
            failures: failures,
            effectiveRateHz: rate,
            coverage: coverage,
            longIntervalShare: longShare
        )
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run the command from Step 2. Expected: alle 9 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/SensorProbeEvaluator.swift" \
        "watch_streamer/ScrybeTests/SensorProbeEvaluatorTests.swift"
git commit -m "feat(spike): add SensorProbeEvaluator for CMSensorRecorder criteria"
```

---

### Task 2: Watch-Seite — `CMSensorRecorder` ansteuern

Erhebt die Rohkennzahlen. Enthält bewusst keine Bewertung.

**Files:**
- Create: `watch_streamer/WatchStreamer Watch App/SensorProbe.swift`
- Modify: `watch_streamer/WatchStreamer Watch App/MotionManager.swift` (`handleCommand`-Switch)
- Modify: Watch-App `Info.plist` (`NSMotionUsageDescription`)

**Interfaces:**
- Consumes: nichts aus früheren Tasks
- Produces: `SensorProbe.start(durationSeconds:) -> [String: Any]`, `SensorProbe.report() -> [String: Any]` (die angeforderte Dauer wird beim Start in `UserDefaults` hinterlegt und dort wieder gelesen — der Aufrufer muss sie nicht kennen). Die Rückgabe-Dictionaries tragen exakt die Feldnamen von `SensorProbeStats` (`sampleCount`, `firstTimestamp`, `lastTimestamp`, `requestedSeconds`, `intervalBucketsMs`, `maxGapSeconds`, `nonMonotonicCount`, `fetchReturnedNil`), damit Task 3 sie ohne Umbenennung dekodieren kann. `intervalBucketsMs` wird als `[String: Int]` übertragen (WCSession erlaubt keine Int-Schlüssel).

- [ ] **Step 1: `NSMotionUsageDescription` ergänzen**

Die Watch-App-`Info.plist` finden und den Schlüssel ergänzen. Ohne ihn liefert CoreMotion keine Daten und die App wird beim Zugriff beendet.

```bash
plutil -insert NSMotionUsageDescription \
  -string "Scrybe wertet Bewegungsdaten des Handgelenks aus, um Schreibzeit zu erkennen." \
  "watch_streamer/WatchStreamer Watch App/Info.plist"
plutil -p "watch_streamer/WatchStreamer Watch App/Info.plist" | grep NSMotion
```

Falls die Datei nicht existiert, liegt der Schlüssel in den Build-Settings (`INFOPLIST_KEY_NSMotionUsageDescription`) — dann dort setzen und den `plutil`-Aufruf überspringen.

- [ ] **Step 2: `SensorProbe` implementieren**

```swift
// watch_streamer/WatchStreamer Watch App/SensorProbe.swift
import Foundation
import CoreMotion

/// Diagnose-Werkzeug fuer den CMSensorRecorder-Spike. Erhebt Rohkennzahlen
/// und faellt bewusst kein Urteil — das tut SensorProbeEvaluator auf dem
/// iPhone, wo es ohne Hardware testbar ist.
enum SensorProbe {
    private static let recorder = CMSensorRecorder()
    /// Bucket-Untergrenzen in Millisekunden.
    private static let buckets = [0, 20, 40, 100, 1000]
    /// Why: Apple dokumentiert bis zu drei Minuten Verzoegerung, bevor neue
    /// Samples abrufbar sind. Fuenf Minuten Abstand halten den Cursor sicher
    /// hinter dieser Grenze (Spec §1.1).
    static let headroomSeconds: TimeInterval = 300
    /// Ein einzelner Abruf darf hoechstens 12 h umspannen (Apple-Doku).
    static let maxFetchSpanSeconds: TimeInterval = 12 * 3600

    static func authorizationDescription() -> String {
        if #available(watchOS 9.0, *) {
            return String(describing: CMSensorRecorder.authorizationStatus())
        }
        return "unknown"
    }

    static func start(durationSeconds: Double) -> [String: Any] {
        let clamped = min(durationSeconds, 43_200)   // 12 h Maximum
        recorder.recordAccelerometer(forDuration: clamped)
        UserDefaults.standard.set(Date().timeIntervalSinceReferenceDate,
                                  forKey: "sensorProbe.startedAt")
        UserDefaults.standard.set(clamped, forKey: "sensorProbe.requestedSeconds")
        return [
            "ok": true,
            "startedAt": Date().timeIntervalSinceReferenceDate,
            "requestedSeconds": clamped,
            "authorization": authorizationDescription()
        ]
    }

    static func report() -> [String: Any] {
        let defaults = UserDefaults.standard
        let startedAt = defaults.double(forKey: "sensorProbe.startedAt")
        let requested = defaults.double(forKey: "sensorProbe.requestedSeconds")
        guard startedAt > 0 else {
            return ["ok": false, "error": "no probe started"]
        }

        let from = Date(timeIntervalSinceReferenceDate: startedAt)
        let until = min(
            Date().addingTimeInterval(-headroomSeconds),
            from.addingTimeInterval(maxFetchSpanSeconds)
        )
        guard until > from else {
            return ["ok": false, "error": "probe window not ready yet"]
        }

        guard let list = recorder.accelerometerData(from: from, to: until) else {
            return [
                "ok": true,
                "sampleCount": 0,
                "firstTimestamp": 0.0,
                "lastTimestamp": 0.0,
                "requestedSeconds": requested,
                "intervalBucketsMs": [String: Int](),
                "maxGapSeconds": 0.0,
                "nonMonotonicCount": 0,
                "fetchReturnedNil": true,
                "authorization": authorizationDescription()
            ]
        }

        var counts = Dictionary(uniqueKeysWithValues: buckets.map { (String($0), 0) })
        var n = 0
        var first = 0.0
        var last = 0.0
        var previous: Double?
        var maxGap = 0.0
        var nonMonotonic = 0

        for case let sample as CMRecordedAccelerometerData in list {
            let t = sample.startDate.timeIntervalSinceReferenceDate
            if n == 0 { first = t }
            if let prev = previous {
                let delta = t - prev
                if delta < 0 { nonMonotonic += 1 }
                maxGap = max(maxGap, delta)
                let ms = Int((delta * 1000).rounded(.down))
                let key = String(buckets.last(where: { $0 <= ms }) ?? 0)
                counts[key, default: 0] += 1
            }
            previous = t
            last = t
            n += 1
        }

        return [
            "ok": true,
            "sampleCount": n,
            "firstTimestamp": first,
            "lastTimestamp": last,
            "requestedSeconds": requested,
            "intervalBucketsMs": counts,
            "maxGapSeconds": maxGap,
            "nonMonotonicCount": nonMonotonic,
            "fetchReturnedNil": false,
            "authorization": authorizationDescription()
        ]
    }
}
```

- [ ] **Step 3: Commands im `handleCommand`-Switch ergänzen**

In `watch_streamer/WatchStreamer Watch App/MotionManager.swift`, im `switch command`-Block, direkt nach `case "drain_spill":` und dessen `return`-Block einfügen:

```swift
        case "sensor_probe_start":
            let duration = (message["duration_seconds"] as? Double) ?? 3600
            var reply = SensorProbe.start(durationSeconds: duration)
            reply["command"] = command
            reply["command_id"] = commandId ?? ""
            return reply
        case "sensor_probe_report":
            var reply = SensorProbe.report()
            reply["command"] = command
            reply["command_id"] = commandId ?? ""
            return reply
```

- [ ] **Step 4: Build verifizieren**

Run:
```bash
cd watch_streamer && xcodebuild build -project WatchStreamer.xcodeproj \
  -scheme "WatchStreamer Watch App" \
  -destination 'platform=watchOS Simulator,name=Apple Watch Series 10 (46mm)' 2>&1 | tail -5
```
Expected: `** BUILD SUCCEEDED **`. Passt der Simulator-Name nicht, mit `xcrun simctl list devices available | grep Watch` einen vorhandenen wählen.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer Watch App/SensorProbe.swift" \
        "watch_streamer/WatchStreamer Watch App/MotionManager.swift" \
        "watch_streamer/WatchStreamer Watch App/Info.plist"
git commit -m "feat(spike): collect sensor stats on the watch"
```

---

### Task 3: iPhone-Seite — Auslösen und Anzeigen

**Files:**
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift`
- Create: `watch_streamer/WatchStreamer/Admin/Sections/SensorProbeCard.swift`
- Modify: `watch_streamer/WatchStreamer/Admin/AdminPanelView.swift` (eine Zeile: Karte registrieren)

**Interfaces:**
- Consumes: `SensorProbeStats` / `SensorProbeVerdict` / `SensorProbeEvaluator.evaluate` aus Task 1; die Watch-Antwortfelder aus Task 2
- Produces: `ServerCommandListener.startSensorProbe(durationSeconds:)`, `ServerCommandListener.fetchSensorProbeReport()`, `@Published var sensorProbeVerdict: SensorProbeVerdict?`, `@Published var sensorProbeRaw: String?`

- [ ] **Step 1: `forwardToWatch` um einen Reply-Callback erweitern**

`ServerCommandListener.forwardToWatch(_ payload:)` (Zeile 373) leitet die Watch-Antwort heute ausschliesslich an den Server weiter (`sendServerEvent(["type": "watch_ack", …])`). Der serverlose Diagnosepfad braucht sie lokal. Der Parameter bekommt einen Vorgabewert, damit alle bestehenden Aufrufer (`drainWatchSpill()`, `clearWatchSpill()`, Start/Stop) unverändert bleiben.

Signatur ändern:

```swift
    func forwardToWatch(_ payload: [String: Any],
                        onReply: (([String: Any]) -> Void)? = nil) {
```

Und im `replyHandler`-Block, direkt nach `self?.sendPhoneStatus()`, ergänzen:

```swift
                onReply?(reply)
```

Der Block läuft bereits auf `DispatchQueue.main` — der Callback braucht keine eigene Dispatch-Umschaltung.

- [ ] **Step 2: Sende-Methoden ergänzen**

Neben `drainWatchSpill()` / `clearWatchSpill()` einfügen:

```swift
    @Published var sensorProbeVerdict: SensorProbeVerdict?
    @Published var sensorProbeRaw: String?

    func startSensorProbe(durationSeconds: Double) {
        forwardToWatch(["command": "sensor_probe_start",
                        "duration_seconds": durationSeconds]) { [weak self] reply in
            self?.sensorProbeRaw = String(describing: reply)
        }
    }

    func fetchSensorProbeReport() {
        forwardToWatch(["command": "sensor_probe_report"]) { [weak self] reply in
            self?.sensorProbeRaw = String(describing: reply)
            self?.sensorProbeVerdict = Self.verdict(from: reply)
        }
    }

    /// Uebersetzt die Watch-Antwort in SensorProbeStats und bewertet sie.
    /// Why: WCSession erlaubt keine Int-Schluessel, das Histogramm kommt als
    /// [String: Int] und wird hier zurueckgemappt.
    static func verdict(from reply: [String: Any]) -> SensorProbeVerdict? {
        guard let count = reply["sampleCount"] as? Int else { return nil }
        let rawBuckets = (reply["intervalBucketsMs"] as? [String: Int]) ?? [:]
        var buckets: [Int: Int] = [:]
        for (k, v) in rawBuckets { if let key = Int(k) { buckets[key] = v } }
        let stats = SensorProbeStats(
            sampleCount: count,
            firstTimestamp: (reply["firstTimestamp"] as? Double) ?? 0,
            lastTimestamp: (reply["lastTimestamp"] as? Double) ?? 0,
            requestedSeconds: (reply["requestedSeconds"] as? Double) ?? 0,
            intervalBucketsMs: buckets,
            maxGapSeconds: (reply["maxGapSeconds"] as? Double) ?? 0,
            nonMonotonicCount: (reply["nonMonotonicCount"] as? Int) ?? 0,
            fetchReturnedNil: (reply["fetchReturnedNil"] as? Bool) ?? false
        )
        return SensorProbeEvaluator.evaluate(stats)
    }
```

- [ ] **Step 3: Admin-Karte anlegen**

Der Admin-Bereich ist **keine** `Form` mit `Section`s, sondern eine `VStack` aus Karten; jede Karte ist eine eigene Datei unter `watch_streamer/WatchStreamer/Admin/Sections/`. Der Zugriff auf den Listener läuft über das Singleton `ServerCommandListener.shared`, beobachtet per `@ObservedObject` (so machen es `ConnectionsCard`, `SessionCard`, `RecordingHealthCard`). **Lies `Admin/Sections/RepairCard.swift` als Stilvorlage, bevor du schreibst** — Button-Aufbau, `theme`-Zugriff und `scrybeSurface`-Modifier werden von dort übernommen.

```swift
// watch_streamer/WatchStreamer/Admin/Sections/SensorProbeCard.swift
import SwiftUI

struct SensorProbeCard: View {
    @Environment(\.scrybe) private var theme
    @ObservedObject private var server = ServerCommandListener.shared

    var body: some View {
        AdminCard(title: "Sensor-Probe") {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    probeButton("1 h", seconds: 3600)
                    probeButton("12 h", seconds: 43_200)
                }
                actionButton("Auswerten", systemImage: "chart.bar.doc.horizontal") {
                    server.fetchSensorProbeReport()
                }
                if let verdict = server.sensorProbeVerdict {
                    result(verdict)
                }
                if let raw = server.sensorProbeRaw {
                    Text(raw)
                        .font(.caption2)
                        .foregroundStyle(theme.ink.opacity(0.5))
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func probeButton(_ title: String, seconds: Double) -> some View {
        actionButton(title, systemImage: "record.circle") {
            server.startSensorProbe(durationSeconds: seconds)
        }
    }

    private func actionButton(_ title: String, systemImage: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundStyle(theme.accent)
                .scrybeSurface(cornerRadius: 12, tint: theme.accent.opacity(0.10), interactive: true)
        }
    }

    private func result(_ v: SensorProbeVerdict) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(v.passed ? "bestanden" : "durchgefallen")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(v.passed ? theme.accent : theme.danger)
            Text(String(format: "Rate %.2f Hz · Coverage %.1f %% · lange Intervalle %.2f %%",
                        v.effectiveRateHz, v.coverage * 100, v.longIntervalShare * 100))
                .font(.caption)
                .foregroundStyle(theme.ink.opacity(0.7))
            if !v.failures.isEmpty {
                Text("Fehlschläge: " + v.failures.map(\.rawValue).joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(theme.danger)
            }
        }
    }
}
```

Weicht ein `theme`-Feld oder ein Modifier von dieser Vorlage ab, gilt das, was die Nachbarkarten tatsächlich verwenden — nicht dieser Entwurf.

- [ ] **Step 4: Karte registrieren**

In `AdminPanelView.swift` genau eine Zeile in die `VStack` einfügen, direkt nach `RepairCard()`:

```swift
                    SensorProbeCard()
```

- [ ] **Step 5: Build und Tests verifizieren**

Run:
```bash
cd watch_streamer && xcodebuild test -project WatchStreamer.xcodeproj -scheme WatchStreamer \
  -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | tail -10
```
Expected: `** TEST SUCCEEDED **`, alle bisherigen Tests plus die neun aus Task 1.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/ServerCommandListener.swift \
        watch_streamer/WatchStreamer/Admin/Sections/SensorProbeCard.swift \
        watch_streamer/WatchStreamer/Admin/AdminPanelView.swift
git commit -m "feat(spike): run sensor probe from admin panel"
```

---

### Task 4: Durchführung auf echter Hardware

Kein Code. Diese Task erzeugt die Messung, auf der Teilprojekt 3 steht oder fällt.

- [ ] **Step 1: 1-Stunden-Lauf**

App auf iPhone und Series 7 installieren. Im Admin-Panel „Sensor-Probe starten (1 h)". **Watch-App danach beenden** (Digital Crown, App aus dem Dock wischen) — die Aufzeichnung muss ohne laufende App weitergehen. Eine Stunde und fünf Minuten warten, App öffnen, „Probe auswerten".

- [ ] **Step 2: Ergebnis festhalten**

Werte in `reports/sensor_probe.md` notieren: Rate, Coverage, Anteil langer Intervalle, grösste Lücke, nicht-monotone Übergänge, Autorisierungsstatus, Verdikt.

- [ ] **Step 3: 12-Stunden-Lauf**

„Sensor-Probe starten (12 h)", Watch-App beenden, normal tragen. Am nächsten Tag auswerten. Zusätzlich notieren: ob die App zwischenzeitlich vom System beendet wurde, Akkustand vorher und nachher.

- [ ] **Step 4: Verdikt dokumentieren und committen**

```bash
git add reports/sensor_probe.md
git commit -m "docs(spike): record sensor probe measurements"
```

**Entscheidung:** Bestehen beide Läufe → Teilprojekt 3 ist baubar. Fällt einer durch, wird das Ergebnis in der Spec §6 festgehalten und die aktive Schreibphase (Teilprojekt 2) zum Hauptprodukt.

---

# Teil B — Core-ML-Konvertierung

### Task 5: Isoliertes venv für `coremltools`

**Files:**
- Create: `requirements-coreml.txt`
- Modify: `.gitignore` (`.venv-coreml/`)

**Interfaces:**
- Produces: ein venv unter `.venv-coreml/`, in dem `coremltools` und `torch` importierbar sind

- [ ] **Step 1: venv anlegen und bestücken**

```bash
python3 -m venv .venv-coreml
.venv-coreml/bin/pip install --upgrade pip
.venv-coreml/bin/pip install "coremltools==9.0" "torch==2.9.1" numpy
```

- [ ] **Step 2: Isolation verifizieren**

```bash
.venv-coreml/bin/python -c "import coremltools, torch, numpy; print(coremltools.__version__, torch.__version__, numpy.__version__)"
python -c "import numpy, torch; print('Projekt:', numpy.__version__, torch.__version__)"
python -c "import coremltools" 2>&1 | tail -1
```
Expected: das venv druckt Versionen; die Projektumgebung druckt **unveränderte** numpy- und torch-Versionen; der letzte Aufruf endet mit `ModuleNotFoundError: No module named 'coremltools'`. Ist die Projekt-numpy-Version gewandert, ist etwas ins falsche Interpreter-Umfeld installiert worden — rückgängig machen.

- [ ] **Step 3: Festschreiben**

```bash
.venv-coreml/bin/pip freeze > requirements-coreml.txt
printf '\n# Isoliertes venv fuer die Core-ML-Konvertierung (siehe requirements-coreml.txt)\n.venv-coreml/\n' >> .gitignore
```

- [ ] **Step 4: Commit**

```bash
git add requirements-coreml.txt .gitignore
git commit -m "chore(deploy): pin coremltools environment"
```

---

### Task 6: Checkpoint-Loader

**Files:**
- Create: `src/deploy/__init__.py`, `src/deploy/checkpoint.py`
- Test: `tests/test_deploy_checkpoint.py`

**Interfaces:**
- Produces: `DEPLOY_SEQ_LEN = 250`; `CHECKPOINTS: dict[str, Path]` mit den Schlüsseln `"active"` und `"passive"`; `load_deploy_model(path) -> tuple[torch.nn.Module, dict]`
- Consumed by: Tasks B3 und B4

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deploy_checkpoint.py
from pathlib import Path

import pytest
import torch

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in CHECKPOINTS.values()),
    reason="Deployment-Checkpoints liegen unter models/ und sind gitignored",
)


@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_loads_with_expected_channel_count(kind, n_channels):
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    assert meta["n_channels"] == n_channels
    assert meta["fs_hz"] == 50
    assert meta["window_sec"] == 5
    assert meta["zscore"] is False


@pytest.mark.parametrize("kind", ["active", "passive"])
def test_model_is_in_eval_mode(kind):
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    assert model.training is False


def test_missing_channels_key_defaults_to_imu():
    # Why: der aktive Checkpoint entstand vor Einfuehrung des Kanalsatz-Feldes
    # und traegt kein meta["channels"] — blindes Lesen waere ein KeyError.
    _, meta = load_deploy_model(CHECKPOINTS["active"])
    assert meta["channels"] == "imu"


def test_passive_checkpoint_declares_raw_accel():
    _, meta = load_deploy_model(CHECKPOINTS["passive"])
    assert meta["channels"] == "raw_accel"


@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_forward_pass_shape_and_determinism(kind, n_channels):
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    x = torch.zeros(1, DEPLOY_SEQ_LEN, n_channels, dtype=torch.float32)
    with torch.no_grad():
        a = model(x)
        b = model(x)
    assert a.shape == (1,)
    # eval() muss Dropout abschalten — sonst weichen zwei Laeufe ab.
    assert torch.equal(a, b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deploy_checkpoint.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.deploy'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/deploy/__init__.py
```
(leere Datei)

```python
# src/deploy/checkpoint.py
"""Laedt die Deployment-Checkpoints als einsatzbereite Modelle.

Einziger Ort im Repo, der ``weights_only=False`` verwendet: die
Checkpoint-Metadaten tragen ein ``TorchVersion``-Objekt. Zulaessig, weil
ausschliesslich eigene, im Repo erzeugte Dateien geladen werden.
"""
from __future__ import annotations

from pathlib import Path

import torch

from src.training.deep.models import MODELS

ROOT = Path(__file__).resolve().parents[2]

DEPLOY_SEQ_LEN = 250

CHECKPOINTS: dict[str, Path] = {
    "active": ROOT / "models/runs/pod_20260825/results/hp_grid/legacy"
                     "/tcn_bigru_confirm/models_tcn_bigru-g00-s42/final.pt",
    "passive": ROOT / "models/runs/pod_raw50/hp_grid/modern50"
                      "/tcn6_raw50/models_tcn6-g00-s42/final.pt",
}

_DEFAULT_CHANNELS = "imu"


def load_deploy_model(path: Path) -> tuple[torch.nn.Module, dict]:
    """Baue das Modell aus einem Checkpoint und setze es in den Eval-Modus."""
    bundle = torch.load(path, map_location="cpu", weights_only=False)
    meta = dict(bundle["meta"])
    # Why: Checkpoints von vor dem raw_accel-Kanalsatz tragen kein "channels".
    meta.setdefault("channels", _DEFAULT_CHANNELS)

    model = MODELS[meta["model"]](n_channels=int(meta["n_channels"]))
    model.load_state_dict(bundle["state_dict"], strict=True)
    model.eval()
    return model, meta
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deploy_checkpoint.py -v && pytest tests/ -q 2>&1 | tail -3`
Expected: neue Tests PASS, Gesamtsuite weiterhin grün.

- [ ] **Step 5: Commit**

```bash
git add src/deploy/__init__.py src/deploy/checkpoint.py tests/test_deploy_checkpoint.py
git commit -m "feat(deploy): add deployment checkpoint loader"
```

---

### Task 7: Golden-Vektoren erzeugen

**Files:**
- Create: `src/deploy/golden.py`
- Create: `scripts/pipeline/make_golden_windows.py`
- Test: `tests/test_deploy_golden.py`
- Artefakte: `tests/fixtures/golden_windows_{active,passive}.json`

**Interfaces:**
- Consumes: `load_deploy_model`, `CHECKPOINTS`, `DEPLOY_SEQ_LEN` aus Task 6
- Produces: `encode_window(arr) -> str`, `decode_window(b64, seq_len, n_channels) -> np.ndarray`, `load_fixture(kind) -> dict`, `FIXTURES: dict[str, Path]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deploy_golden.py
import numpy as np
import pytest
import torch

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model
from src.deploy.golden import FIXTURES, decode_window, encode_window, load_fixture


def test_encode_decode_roundtrips_exactly():
    rng = np.random.default_rng(0)
    arr = rng.standard_normal((DEPLOY_SEQ_LEN, 3)).astype(np.float32)
    back = decode_window(encode_window(arr), DEPLOY_SEQ_LEN, 3)
    # Base64 ueber float32-Bytes ist verlustfrei — hier ist "genau gleich"
    # das richtige Kriterium, nicht "ungefaehr gleich".
    assert np.array_equal(arr, back)


@pytest.mark.skipif(not all(p.exists() for p in FIXTURES.values()),
                    reason="Fixtures noch nicht erzeugt")
@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_fixture_shape_and_balance(kind, n_channels):
    fx = load_fixture(kind)
    assert fx["seq_len"] == DEPLOY_SEQ_LEN
    assert fx["n_channels"] == n_channels
    assert len(fx["windows"]) >= 24
    labels = {w["label"] for w in fx["windows"]}
    assert labels == {0, 1}, "Fixture muss beide Klassen enthalten"
    near = [w for w in fx["windows"] if abs(w["proba"] - 0.5) < 0.15]
    assert near, "Fixture muss schwellennahe Faelle enthalten"


@pytest.mark.skipif(
    not all(p.exists() for p in FIXTURES.values())
    or not all(p.exists() for p in CHECKPOINTS.values()),
    reason="Fixtures oder Checkpoints fehlen",
)
@pytest.mark.parametrize("kind", ["active", "passive"])
def test_pytorch_reproduces_stored_logits(kind):
    """P1a: der Checkpoint reproduziert die gespeicherten Logits."""
    fx = load_fixture(kind)
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    for w in fx["windows"]:
        arr = decode_window(w["data_b64"], fx["seq_len"], fx["n_channels"])
        with torch.no_grad():
            got = float(model(torch.from_numpy(arr).unsqueeze(0))[0])
        assert abs(got - w["logit"]) <= 1e-4, f"{w['id']}: {got} vs {w['logit']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deploy_golden.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.deploy.golden'`.

- [ ] **Step 3: Serialisierung implementieren**

```python
# src/deploy/golden.py
"""Format der Golden-Vektoren: base64-kodierte float32-Bytes.

Base64 statt Dezimalzahlen, weil Python und Swift so exakt dieselben Bits
sehen — bei einer Paritaetspruefung mit Toleranz 1e-4 darf die Eingabe nicht
selbst schon eine Fehlerquelle sein.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures"

FIXTURES: dict[str, Path] = {
    "active": FIXTURE_DIR / "golden_windows_active.json",
    "passive": FIXTURE_DIR / "golden_windows_passive.json",
}


def encode_window(arr: np.ndarray) -> str:
    """(seq_len, n_channels) float32, row-major → base64."""
    a = np.ascontiguousarray(arr, dtype=np.float32)
    return base64.b64encode(a.tobytes()).decode("ascii")


def decode_window(b64: str, seq_len: int, n_channels: int) -> np.ndarray:
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype=np.float32).reshape(seq_len, n_channels).copy()


def load_fixture(kind: str) -> dict:
    return json.loads(FIXTURES[kind].read_text())
```

- [ ] **Step 4: Generator implementieren**

```python
# scripts/pipeline/make_golden_windows.py
"""Zieht Golden-Vektoren aus echten Sessions und schreibt die Fixtures.

Auswahlregel: je Modell 24 Fenster — 8 sicher positive, 8 sicher negative und
8 schwellennahe. Die schwellennahen sind der eigentliche Wert: dort trennt
sich eine korrekte Konvertierung von einer knapp danebenliegenden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model
from src.deploy.golden import FIXTURES, encode_window
from src.training.deep.data import build_raw_windows

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"

N_PER_GROUP = 8


def _sha256(path: Path) -> str:
    """SHA-256 einer Datei oder eines Verzeichnisses (rekursiv, pfadsortiert)."""
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(path)).encode())
                h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()


def _session_windows(
    session: str, channels: str, suffix: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Gibt (X, y, t_center_ms) zurueck — die Signatur von build_raw_windows."""
    merged = pd.read_csv(DATA_PROC / f"{session}_merged{suffix}.csv")
    _assert_50hz(merged, session, suffix)
    return build_raw_windows(merged, seq_len=DEPLOY_SEQ_LEN, stride=25,
                             channels=channels)


def _assert_50hz(merged: pd.DataFrame, session: str, suffix: str) -> None:
    """Bricht ab, wenn die Quelle nicht ~50 Hz hat.

    Why: es gibt drei merged-Varianten je Session — die native ``_merged.csv``
    (bei Modern-Sessions 100 Hz), die 50-Hz-View ``_merged_legacy.csv`` und die
    50-Hz-mit-Gravity-View ``_merged_raw50.csv``. Beide Deployment-Modelle sind
    auf 50 Hz trainiert; eine 100-Hz-Quelle ergaebe 2,5-s- statt 5-s-Fenster,
    und zwar lautlos. Derselbe Fehlermodus hat im S093-Vorfall jedes Feature
    einer Session verzogen, ohne dass eine Metrik es angezeigt haette.
    """
    ts = merged["ts"].dropna().to_numpy(dtype=float)
    if len(ts) < 2 or ts[-1] <= ts[0]:
        raise SystemExit(f"{session}{suffix}: keine brauchbare ts-Achse")
    fs = (len(ts) - 1) * 1000.0 / (ts[-1] - ts[0])
    if not 45.0 <= fs <= 55.0:
        raise SystemExit(
            f"{session}_merged{suffix}.csv hat {fs:.1f} Hz, erwartet ~50 Hz. "
            f"Fuer das aktive Modell '_legacy' verwenden, fuer das passive "
            f"'_raw50' — die native merged-CSV ist bei Modern-Sessions 100 Hz."
        )


def build(kind: str, sessions: list[str], suffix: str) -> dict:
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    rows = []
    for session in sessions:
        X, y, t = _session_windows(session, meta["channels"], suffix)
        if len(X) == 0:
            continue
        with torch.no_grad():
            logits = model(torch.from_numpy(X)).numpy()
        probas = 1.0 / (1.0 + np.exp(-logits))
        for i in range(len(X)):
            rows.append({"session": session, "i": i, "X": X[i],
                         "logit": float(logits[i]), "proba": float(probas[i]),
                         "label": int(y[i]), "t": float(t[i])})

    near = sorted(rows, key=lambda r: abs(r["proba"] - 0.5))[:N_PER_GROUP]
    near_ids = {(r["session"], r["i"]) for r in near}
    rest = [r for r in rows if (r["session"], r["i"]) not in near_ids]
    pos = sorted((r for r in rest if r["label"] == 1),
                 key=lambda r: -r["proba"])[:N_PER_GROUP]
    neg = sorted((r for r in rest if r["label"] == 0),
                 key=lambda r: r["proba"])[:N_PER_GROUP]

    chosen = near + pos + neg
    if len(chosen) < 3 * N_PER_GROUP:
        raise SystemExit(f"nur {len(chosen)} Fenster gefunden — mehr Sessions angeben")

    return {
        "model": meta["model"],
        "kind": kind,
        "checkpoint": str(CHECKPOINTS[kind].relative_to(ROOT)),
        "checkpoint_sha256": _sha256(CHECKPOINTS[kind]),
        "seq_len": DEPLOY_SEQ_LEN,
        "n_channels": int(meta["n_channels"]),
        "channels": meta["channels"],
        "fs_hz": int(meta["fs_hz"]),
        "dtype": "float32",
        "layout": "row-major (seq_len, n_channels)",
        "windows": [
            {"id": f"{r['session']}@{r['i']}", "t_center_ms": r["t"],
             "label": r["label"], "logit": r["logit"], "proba": r["proba"],
             "data_b64": encode_window(r["X"])}
            for r in chosen
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["active", "passive"], required=True)
    ap.add_argument("--sessions", nargs="+", required=True)
    ap.add_argument("--merged-suffix", default="",
                    help="'_raw50' fuer den passiven Pool")
    args = ap.parse_args()

    fx = build(args.kind, args.sessions, args.merged_suffix)
    FIXTURES[args.kind].parent.mkdir(parents=True, exist_ok=True)
    FIXTURES[args.kind].write_text(json.dumps(fx, indent=1))
    print(f"{FIXTURES[args.kind]}: {len(fx['windows'])} Fenster")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Fixtures erzeugen**

Zuerst prüfen, welche Sessions lokal vorliegen, dann drei bis vier pro Modell wählen:

**Beide Modelle brauchen 50-Hz-Quellen.** Es existieren drei merged-Varianten je
Session, und nur zwei davon taugen hier:

| Datei | Rate | Kanäle | wofür |
|---|---:|---|---|
| `{sid}_merged.csv` | nativ (Modern-Sessions: **100 Hz**) | 6 bzw. 9 | **nicht** verwenden, ausser die Session ist nativ 50 Hz |
| `{sid}_merged_legacy.csv` | 50 Hz | 6, ohne Gravity | **aktives** Modell |
| `{sid}_merged_raw50.csv` | 50 Hz | 6 + Gravity | **passives** Modell (`raw_accel` addiert sie auf) |

Diese Zuordnung ist dieselbe, die `_pool_plan` in `src/training/deep/train_loso.py`
beim Training anwendet. Der `_assert_50hz`-Guard oben bricht ab, falls doch eine
100-Hz-Quelle durchrutscht.

```bash
ls data/processed/*_merged_legacy.csv | head -3
ls data/processed/*_merged_raw50.csv  | head -3
python scripts/pipeline/make_golden_windows.py --kind active  --sessions S038 S039 S050 --merged-suffix _legacy
python scripts/pipeline/make_golden_windows.py --kind passive --sessions S038 S039 S050 --merged-suffix _raw50
```

Schlägt der Generator mit „nur N Fenster gefunden" fehl, weitere Sessions aus den `ls`-Listen ergänzen.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_deploy_golden.py -v && pytest tests/ -q 2>&1 | tail -3`
Expected: alle PASS, Gesamtsuite grün.

- [ ] **Step 7: Commit**

```bash
git add src/deploy/golden.py scripts/pipeline/make_golden_windows.py \
        tests/test_deploy_golden.py tests/fixtures/golden_windows_*.json
git commit -m "feat(deploy): generate golden window fixtures"
```

---

### Task 8: Core-ML-Export und P1-Parität

**Files:**
- Create: `scripts/pipeline/export_coreml.py`
- Modify: `tests/test_deploy_golden.py` (P1-Test ergänzen)

**Interfaces:**
- Consumes: `load_deploy_model`, `CHECKPOINTS`, `DEPLOY_SEQ_LEN`, `decode_window`, `load_fixture`
- Produces: `models/coreml/Scrybe{Active,Passive}.mlpackage` mit Eingabe `"window"` und Ausgabe `"logit"`

- [ ] **Step 1: Verfügbares Deployment-Target ermitteln**

Die Namen der Ziel-Enums hängen von der coremltools-Version ab und werden nicht geraten:

```bash
.venv-coreml/bin/python -c "import coremltools as ct; print([t for t in dir(ct.target) if not t.startswith('_')])"
```
Das höchste `iOS*`-Ziel notieren, das mindestens iOS 17 / watchOS 10 entspricht, und in Step 2 einsetzen.

- [ ] **Step 2: Export-Skript schreiben**

```python
# scripts/pipeline/export_coreml.py
"""Konvertiert die Deployment-Checkpoints nach Core ML.

Laeuft im isolierten venv:
    .venv-coreml/bin/python scripts/pipeline/export_coreml.py --kind passive

FP32 ist festgenagelt (Spec §7.3): ein einziges Paritaetskriterium auf allen
drei Ebenen, und Core ML kann nicht still auf eine andere Praezision fallen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import coremltools as ct
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
# Why: als Skript gestartet ist sys.path[0] das Skript-Verzeichnis, nicht das
# Repo-Root — ohne diese Zeile scheitert der src-Import. Gleiche Konvention wie
# in den uebrigen scripts/pipeline/*.py.
sys.path.insert(0, str(ROOT))

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model


def _sha256(path: Path) -> str:
    """SHA-256 einer Datei oder eines Verzeichnisses (rekursiv, pfadsortiert).

    Ein .mlpackage ist ein Verzeichnis — ein Hash ueber eine einzelne Datei
    wuerde stillschweigend nur einen Teil abdecken.
    """
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(path)).encode())
                h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()

OUT_DIR = ROOT / "models" / "coreml"
OUT_NAMES = {"active": "ScrybeActive", "passive": "ScrybePassive"}

# In Step 1 ermittelt.
DEPLOYMENT_TARGET = ct.target.iOS17

INPUT_NAME = "window"
OUTPUT_NAME = "logit"


def export(kind: str) -> Path:
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    n_ch = int(meta["n_channels"])
    example = torch.zeros(1, DEPLOY_SEQ_LEN, n_ch, dtype=torch.float32)

    # model.eval() ist in load_deploy_model gesetzt — Tracing im Trainingsmodus
    # wuerde Dropout und BatchNorm-Batch-Statistiken einbacken.
    assert model.training is False
    traced = torch.jit.trace(model, example)

    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name=INPUT_NAME,
                              shape=(1, DEPLOY_SEQ_LEN, n_ch),
                              dtype=np.float32)],
        outputs=[ct.TensorType(name=OUTPUT_NAME, dtype=np.float32)],
        convert_to="mlprogram",
        compute_precision=ct.precision.FLOAT32,
        minimum_deployment_target=DEPLOYMENT_TARGET,
    )
    mlmodel.short_description = (
        f"{meta['model']} — {meta['channels']}, {n_ch} Kanaele, "
        f"{DEPLOY_SEQ_LEN} Samples @ {meta['fs_hz']} Hz, Schwelle 0.5"
    )
    mlmodel.version = f"{meta['model']}-s{meta['seed']}-{meta['git_sha']}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{OUT_NAMES[kind]}.mlpackage"
    mlmodel.save(str(out))

    # Spec §7.2: Begleitartefakt mit Version und SHA-256, damit spaeter
    # nachweisbar ist, welches Gewicht auf dem Geraet lief.
    sidecar = {
        "artifact": out.name,
        "sha256": _sha256(out),
        "model": meta["model"],
        "channels": meta["channels"],
        "n_channels": n_ch,
        "seq_len": DEPLOY_SEQ_LEN,
        "fs_hz": int(meta["fs_hz"]),
        "threshold": 0.5,
        "compute_precision": "FLOAT32",
        "input_name": INPUT_NAME,
        "output_name": OUTPUT_NAME,
        "source_checkpoint": str(CHECKPOINTS[kind].relative_to(ROOT)),
        "source_checkpoint_sha256": _sha256(CHECKPOINTS[kind]),
        "coremltools": ct.__version__,
        "torch": str(torch.__version__),
    }
    (OUT_DIR / f"{OUT_NAMES[kind]}.json").write_text(json.dumps(sidecar, indent=1))
    print(f"{out}  ({meta['model']}, {n_ch} Kanaele)  sha256={sidecar['sha256'][:12]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["active", "passive", "both"], default="both")
    args = ap.parse_args()
    kinds = ["active", "passive"] if args.kind == "both" else [args.kind]
    for k in kinds:
        export(k)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Exportieren**

```bash
.venv-coreml/bin/python scripts/pipeline/export_coreml.py --kind both
ls -la models/coreml/
cat models/coreml/ScrybePassive.json
```
Expected: zwei `.mlpackage`-Verzeichnisse und zwei Begleit-JSONs mit SHA-256.

Schlägt die Konvertierung am bidirektionalen GRU fehl, gilt die Fallback-Leiter aus Spec §7.4 — **in dieser Reihenfolge**: erst ExportedProgram statt `torch.jit.trace` (`torch.export.export`), dann Entrollen des GRU vor der Konvertierung, dann Rückfall auf `tcn6` legacy als aktives Modell (0.9154 statt 0.9209). **Kein** GRU-Nachbau in Swift.

- [ ] **Step 4: P1-Test ergänzen**

An `tests/test_deploy_golden.py` anhängen:

```python
COREML_DIR = FIXTURES["active"].parents[2] / "models" / "coreml"
COREML_NAMES = {"active": "ScrybeActive", "passive": "ScrybePassive"}


@pytest.mark.skipif(
    not all((COREML_DIR / f"{n}.mlpackage").exists() for n in COREML_NAMES.values()),
    reason="mlpackage noch nicht exportiert",
)
@pytest.mark.parametrize("kind", ["active", "passive"])
def test_coreml_matches_pytorch(kind):
    """P1: das konvertierte Modell stimmt mit PyTorch ueberein."""
    ct = pytest.importorskip("coremltools",
                             reason="nur im .venv-coreml installiert")
    fx = load_fixture(kind)
    mlmodel = ct.models.MLModel(
        str(COREML_DIR / f"{COREML_NAMES[kind]}.mlpackage"),
        compute_units=ct.ComputeUnit.CPU_ONLY,
    )
    for w in fx["windows"]:
        arr = decode_window(w["data_b64"], fx["seq_len"], fx["n_channels"])
        out = mlmodel.predict({"window": arr[None, ...].astype(np.float32)})
        got = float(np.ravel(out["logit"])[0])
        assert abs(got - w["logit"]) <= 1e-4, f"{w['id']}: {got} vs {w['logit']}"
        # Bei Schwelle 0.5 muss auch die Klassifikation identisch sein.
        assert (got >= 0) == (w["logit"] >= 0), f"{w['id']}: Klassenwechsel"
```

- [ ] **Step 5: P1 ausführen**

Run:
```bash
.venv-coreml/bin/pip install pytest pandas
.venv-coreml/bin/python -m pytest tests/test_deploy_golden.py -v -k coreml
pytest tests/ -q 2>&1 | tail -3
```
Expected: die P1-Tests PASS im venv; in der Projektumgebung werden sie übersprungen (`importorskip`), Gesamtsuite grün.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline/export_coreml.py tests/test_deploy_golden.py
git commit -m "feat(deploy): export Core ML models"
```

---

# Teil C — Parität auf den Zielgeräten

### Task 9: Core-ML-Wrapper und Artefakte in die App

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/ScrybeModel.swift`
- Artefakte: `watch_streamer/WatchStreamer/ScrybeActive.mlpackage`, `watch_streamer/WatchStreamer Watch App/ScrybePassive.mlpackage`

**Interfaces:**
- Produces: `final class ScrybeModel`, `init(resourceName:channels:seqLen:) throws`, `func logit(window: [Float]) throws -> Float`, `static func decodeBase64Window(_:) -> [Float]?`, `enum ScrybeModelError`

- [ ] **Step 1: Artefakte in die Target-Ordner kopieren**

```bash
cp -R models/coreml/ScrybeActive.mlpackage  "watch_streamer/WatchStreamer/"
cp -R models/coreml/ScrybePassive.mlpackage "watch_streamer/WatchStreamer Watch App/"
cp tests/fixtures/golden_windows_passive.json "watch_streamer/WatchStreamer Watch App/"
cp tests/fixtures/golden_windows_active.json  "watch_streamer/ScrybeTests/"
```

Die Ordner sind synchronisierte Xcode-Gruppen — die Dateien werden allein durch ihre Lage Teil des jeweiligen Targets.

- [ ] **Step 2: Wrapper schreiben**

```swift
// watch_streamer/WatchStreamer/Scrybe/Logic/ScrybeModel.swift
import CoreML
import Foundation

enum ScrybeModelError: Error {
    case missingResource(String)
    case badWindowLength(expected: Int, got: Int)
    case missingOutput(String)
}

/// Dünner Core-ML-Wrapper: ein Fenster rein, ein Logit raus.
///
/// Die Compute-Konfiguration ist bewusst auf `.cpuOnly` festgenagelt
/// (Spec §7.3): FP32, deterministisch, kein stiller Fallback bei nicht
/// unterstützten Operationen. Bei 9k bzw. 19k Parametern ist der Preis
/// dafür gegenüber der Sensorik vernachlässigbar.
final class ScrybeModel {
    static let inputName = "window"
    static let outputName = "logit"

    let seqLen: Int
    let channels: Int
    private let model: MLModel

    init(resourceName: String, channels: Int, seqLen: Int = 250) throws {
        guard let url = Bundle.main.url(forResource: resourceName,
                                        withExtension: "mlmodelc") else {
            throw ScrybeModelError.missingResource(resourceName)
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly
        self.model = try MLModel(contentsOf: url, configuration: config)
        self.seqLen = seqLen
        self.channels = channels
    }

    /// `window` ist row-major (seqLen, channels) — dieselbe Reihenfolge wie
    /// `build_raw_windows` in Python.
    func logit(window: [Float]) throws -> Float {
        let expected = seqLen * channels
        guard window.count == expected else {
            throw ScrybeModelError.badWindowLength(expected: expected,
                                                   got: window.count)
        }
        let array = try MLMultiArray(shape: [1, NSNumber(value: seqLen),
                                             NSNumber(value: channels)],
                                     dataType: .float32)
        let buffer = array.dataPointer.bindMemory(to: Float.self, capacity: expected)
        window.withUnsafeBufferPointer { buffer.update(from: $0.baseAddress!,
                                                       count: expected) }

        let input = try MLDictionaryFeatureProvider(
            dictionary: [Self.inputName: MLFeatureValue(multiArray: array)])
        let out = try model.prediction(from: input)
        guard let value = out.featureValue(for: Self.outputName)?.multiArrayValue else {
            throw ScrybeModelError.missingOutput(Self.outputName)
        }
        return value[0].floatValue
    }

    func isWriting(window: [Float]) throws -> Bool {
        try logit(window: window) >= 0   // Logit >= 0 entspricht Proba >= 0.5
    }

    /// Dekodiert das base64-float32-Format der Golden-Vektoren.
    static func decodeBase64Window(_ b64: String) -> [Float]? {
        guard let data = Data(base64Encoded: b64) else { return nil }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float32.self)) }
    }
}
```

- [ ] **Step 3: Build verifizieren**

Run:
```bash
cd watch_streamer && xcodebuild build -project WatchStreamer.xcodeproj -scheme WatchStreamer \
  -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | tail -5
```
Expected: `** BUILD SUCCEEDED **`. Findet der Build die `.mlmodelc` nicht, in den Build-Logs prüfen, ob die Core-ML-Kompilierung gelaufen ist (`CoreMLModelCompile`); fehlt sie, das `.mlpackage` einmal in Xcode öffnen, damit die Ordnersynchronisation greift.

- [ ] **Step 4: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/ScrybeModel.swift" \
        "watch_streamer/WatchStreamer/ScrybeActive.mlpackage" \
        "watch_streamer/WatchStreamer Watch App/ScrybePassive.mlpackage" \
        "watch_streamer/WatchStreamer Watch App/golden_windows_passive.json" \
        "watch_streamer/ScrybeTests/golden_windows_active.json"
git commit -m "feat(deploy): bundle Core ML models in the app"
```

---

### Task 10: P2 — Parität auf dem iPhone

**Files:**
- Create: `watch_streamer/ScrybeTests/ScrybeModelParityTests.swift`

**Interfaces:**
- Consumes: `ScrybeModel` aus Task 9, `golden_windows_active.json`

- [ ] **Step 1: Write the failing test**

```swift
// watch_streamer/ScrybeTests/ScrybeModelParityTests.swift
import Testing
import Foundation
@testable import WatchStreamer

private struct GoldenWindow: Decodable {
    let id: String
    let label: Int
    let logit: Double
    let proba: Double
    let data_b64: String
}

private struct GoldenFixture: Decodable {
    let model: String
    let seq_len: Int
    let n_channels: Int
    let windows: [GoldenWindow]
}

@Suite("ScrybeModel Paritaet (P2, iPhone)")
struct ScrybeModelParityTests {

    private func fixture() throws -> GoldenFixture {
        let url = try #require(Bundle(for: BundleMarker.self)
            .url(forResource: "golden_windows_active", withExtension: "json"))
        return try JSONDecoder().decode(GoldenFixture.self,
                                        from: Data(contentsOf: url))
    }

    @Test("aktives Modell reproduziert alle Golden-Logits innerhalb 1e-4")
    func activeModelMatchesPyTorch() throws {
        let fx = try fixture()
        let model = try ScrybeModel(resourceName: "ScrybeActive",
                                    channels: fx.n_channels,
                                    seqLen: fx.seq_len)
        for w in fx.windows {
            let window = try #require(ScrybeModel.decodeBase64Window(w.data_b64))
            #expect(window.count == fx.seq_len * fx.n_channels)
            let got = try model.logit(window: window)
            #expect(abs(Double(got) - w.logit) <= 1e-4, "\(w.id)")
        }
    }

    @Test("Klassifikation bei Schwelle 0,5 ist identisch")
    func classificationMatches() throws {
        let fx = try fixture()
        let model = try ScrybeModel(resourceName: "ScrybeActive",
                                    channels: fx.n_channels,
                                    seqLen: fx.seq_len)
        for w in fx.windows {
            let window = try #require(ScrybeModel.decodeBase64Window(w.data_b64))
            #expect(try model.isWriting(window: window) == (w.proba >= 0.5),
                    "\(w.id)")
        }
    }

    @Test("falsche Fensterlaenge wird abgewiesen")
    func rejectsWrongLength() throws {
        let model = try ScrybeModel(resourceName: "ScrybeActive", channels: 6)
        #expect(throws: ScrybeModelError.self) {
            _ = try model.logit(window: [Float](repeating: 0, count: 10))
        }
    }
}

/// Marker, um an das Test-Bundle zu kommen.
private final class BundleMarker {}
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd watch_streamer && xcodebuild test -project WatchStreamer.xcodeproj -scheme WatchStreamer \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -only-testing:ScrybeTests/ScrybeModelParityTests 2>&1 | tail -20
```
Expected: zunächst FAIL, solange `ScrybeModel` oder die Ressource fehlen.

- [ ] **Step 3: Grün machen**

Es ist kein neuer Produktionscode nötig — Task 9 hat ihn geliefert. Schlägt der Test fehl, ist es ein echter Befund:
- Toleranz verletzt → die Konvertierung ist nicht verlustfrei, zurück zu Task 8 und die Fallback-Leiter prüfen;
- Ressource nicht gefunden → das `.mlpackage` beziehungsweise die JSON liegt im falschen Ordner;
- Klassenwechsel bei sonst passender Toleranz → auf `.cpuOnly` in `ScrybeModel` prüfen.

- [ ] **Step 4: Run tests to verify they pass**

Run: das Kommando aus Step 2, danach die volle Suite ohne `-only-testing`.
Expected: `** TEST SUCCEEDED **`.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/ScrybeTests/ScrybeModelParityTests.swift
git commit -m "test(deploy): verify model parity on iPhone"
```

---

### Task 11: P3 — Parität auf der Series 7

Auf der Watch läuft kein Test-Bundle. Die Prüfung geht denselben Weg wie der Spike: Command hin, Ergebnis zurück, Anzeige im Admin-Panel.

**Files:**
- Create: `watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift`
- Modify: `watch_streamer/WatchStreamer Watch App/MotionManager.swift` (`case "parity_check"`)
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift`
- Modify: `watch_streamer/WatchStreamer/Admin/AdminPanelView.swift`

**Interfaces:**
- Consumes: `ScrybePassive.mlpackage` und `golden_windows_passive.json` aus Task 9
- Produces: `WatchParityCheck.run() -> [String: Any]` mit den Schlüsseln `total`, `passed`, `maxAbsDiff`, `classMismatches`, `failedIds`

- [ ] **Step 1: Prüfer auf der Watch**

`ScrybeModel.swift` liegt im iPhone-Ordner und ist auf der Watch nicht verfügbar; die Watch bekommt eine eigene, gleich aufgebaute Datei. Die Duplikation ist beabsichtigt — die Alternative wäre eine Cross-Target-Mitgliedschaft, die die Ordnersynchronisation aufbricht.

```swift
// watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift
import CoreML
import Foundation

enum WatchScrybeModelError: Error {
    case missingResource(String)
    case badWindowLength(expected: Int, got: Int)
    case missingOutput
}

/// Core-ML-Wrapper der Watch. Bewusst identisch aufgebaut zu ScrybeModel im
/// iPhone-Target; getrennte Datei, weil die Ordnersynchronisation des
/// Xcode-Projekts Target-Zugehörigkeit über die Lage bestimmt.
final class WatchScrybeModel {
    let seqLen: Int
    let channels: Int
    private let model: MLModel

    init(resourceName: String, channels: Int, seqLen: Int = 250) throws {
        guard let url = Bundle.main.url(forResource: resourceName,
                                        withExtension: "mlmodelc") else {
            throw WatchScrybeModelError.missingResource(resourceName)
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly
        self.model = try MLModel(contentsOf: url, configuration: config)
        self.seqLen = seqLen
        self.channels = channels
    }

    func logit(window: [Float]) throws -> Float {
        let expected = seqLen * channels
        guard window.count == expected else {
            throw WatchScrybeModelError.badWindowLength(expected: expected,
                                                        got: window.count)
        }
        let array = try MLMultiArray(shape: [1, NSNumber(value: seqLen),
                                             NSNumber(value: channels)],
                                     dataType: .float32)
        let buffer = array.dataPointer.bindMemory(to: Float.self, capacity: expected)
        window.withUnsafeBufferPointer { buffer.update(from: $0.baseAddress!,
                                                       count: expected) }
        let input = try MLDictionaryFeatureProvider(
            dictionary: ["window": MLFeatureValue(multiArray: array)])
        let out = try model.prediction(from: input)
        guard let v = out.featureValue(for: "logit")?.multiArrayValue else {
            throw WatchScrybeModelError.missingOutput
        }
        return v[0].floatValue
    }

    static func decodeBase64Window(_ b64: String) -> [Float]? {
        guard let data = Data(base64Encoded: b64) else { return nil }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float32.self)) }
    }
}

private struct WatchGoldenWindow: Decodable {
    let id: String
    let logit: Double
    let proba: Double
    let data_b64: String
}

private struct WatchGoldenFixture: Decodable {
    let seq_len: Int
    let n_channels: Int
    let windows: [WatchGoldenWindow]
}

enum WatchParityCheck {
    static let tolerance = 1e-4

    static func run() -> [String: Any] {
        do {
            guard let url = Bundle.main.url(forResource: "golden_windows_passive",
                                            withExtension: "json") else {
                return ["ok": false, "error": "fixture missing"]
            }
            let fx = try JSONDecoder().decode(WatchGoldenFixture.self,
                                              from: Data(contentsOf: url))
            // Why: eine leere Fixture wuerde als "0/0 bestanden" durchgehen —
            // ein Gate, das nicht schliessen kann, ist schlechter als keines.
            guard !fx.windows.isEmpty else {
                return ["ok": false, "error": "fixture is empty"]
            }
            let model = try WatchScrybeModel(resourceName: "ScrybePassive",
                                             channels: fx.n_channels,
                                             seqLen: fx.seq_len)
            var maxDiff = 0.0
            var passed = 0
            var classMismatches = 0
            var failedIds: [String] = []

            for w in fx.windows {
                guard let window = decode(w.data_b64) else {
                    failedIds.append(w.id); continue
                }
                let got = Double(try model.logit(window: window))
                let diff = abs(got - w.logit)
                maxDiff = max(maxDiff, diff)
                if (got >= 0) != (w.proba >= 0.5) { classMismatches += 1 }
                if diff <= tolerance { passed += 1 } else { failedIds.append(w.id) }
            }

            return [
                "ok": true,
                "total": fx.windows.count,
                "passed": passed,
                "maxAbsDiff": maxDiff,
                "classMismatches": classMismatches,
                "failedIds": Array(failedIds.prefix(5))
            ]
        } catch {
            return ["ok": false, "error": String(describing: error)]
        }
    }

    private static func decode(_ b64: String) -> [Float]? {
        WatchScrybeModel.decodeBase64Window(b64)
    }
}
```

- [ ] **Step 2: Command ergänzen**

In `MotionManager.swift` neben den Spike-Commands aus Task 2:

```swift
        case "parity_check":
            var reply = WatchParityCheck.run()
            reply["command"] = command
            reply["command_id"] = commandId ?? ""
            return reply
```

- [ ] **Step 3: iPhone-Seite ergänzen**

In `ServerCommandListener.swift`:

```swift
    @Published var parityResult: String?

    func runWatchParityCheck() {
        forwardToWatch(["command": "parity_check"]) { [weak self] reply in
            let total = (reply["total"] as? Int) ?? 0
            let passed = (reply["passed"] as? Int) ?? 0
            let maxDiff = (reply["maxAbsDiff"] as? Double) ?? .nan
            let mismatch = (reply["classMismatches"] as? Int) ?? -1
            self?.parityResult = String(
                format: "%d/%d bestanden, max |Δ| = %.2e, Klassenwechsel: %d",
                passed, total, maxDiff, mismatch)
        }
    }
```

In `AdminPanelView.swift`, im Abschnitt „On-Device-Diagnose":

```swift
                Button("Modell-Paritaet auf der Watch pruefen") {
                    listener.runWatchParityCheck()
                }
                if let r = listener.parityResult {
                    LabeledContent("P3", value: r)
                }
```

- [ ] **Step 4: Auf echter Hardware ausführen**

Beide Apps auf iPhone und Series 7 installieren, im Admin-Panel „Modell-Paritaet auf der Watch pruefen".

Erfolgskriterium: **alle** Fenster bestanden, `maxAbsDiff` ≤ 1e-4, `classMismatches` = 0. Ergebnis in `reports/sensor_probe.md` unter einer eigenen Überschrift festhalten, mit Gerätemodell und watchOS-Version.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift" \
        "watch_streamer/WatchStreamer Watch App/MotionManager.swift" \
        watch_streamer/WatchStreamer/ServerCommandListener.swift \
        watch_streamer/WatchStreamer/Admin/AdminPanelView.swift \
        reports/sensor_probe.md
git commit -m "test(deploy): verify model parity on the watch"
```

---

## Abschluss

Nach Task 11 ist der Zustand:

- der Spike-Mechanismus (1h/12h-Sensor-Probe-Commands + Auswertung) ist gebaut
  und unit-getestet; die eigentliche Messung auf der Series 7 (Task 4) ist ein
  manueller Schritt mit bis zu zwölf Stunden Wandzeit und steht noch aus;
- beide Modelle nach Core ML konvertiert, mit festgenagelter FP32-Konfiguration;
- Gleichheit mit PyTorch gemessen auf Mac (P1) und im iPhone-Simulator (P2);
  der P3-Command-Pfad (physische Watch) ist gebaut, aber die Messung selbst
  ist ebenfalls ein noch ausstehender manueller Hardware-Schritt;
- **kein** App-Feature gebaut — das ist Teilprojekt 2.

Der 1h/12h-Spike und die P3-Paritätsprüfung sind die drei noch offenen
Messungen; ihre Akzeptanzkriterien und leeren Ergebnisfelder stehen bereit
in `reports/sensor_probe.md`. Damit sind die Voraussetzungen für die eigene
Spec zu Teilprojekt 2 (aktive Schreibphase) erfüllt; Teilprojekt 3 hängt
zusätzlich am bestandenen Spike. Fällt der Spike durch, entfällt Teilprojekt 3
und Teilprojekt 2 wird zum Hauptprodukt.

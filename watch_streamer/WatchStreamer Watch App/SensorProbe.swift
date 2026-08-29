import Foundation
import CoreMotion

/// Diagnose-Werkzeug fuer den CMSensorRecorder-Spike. Erhebt Rohkennzahlen
/// und faellt bewusst kein Urteil — das tut SensorProbeEvaluator auf dem
/// iPhone, wo es ohne Hardware testbar ist.
/// `nonisolated`: the passive tracker reads the recorder from a background
/// context, and a 12-hour fetch must never run on the main actor.
nonisolated enum SensorProbe {
    private static let recorder = CMSensorRecorder()
    /// Bucket-Untergrenzen in Millisekunden.
    private static let buckets = [0, 20, 40, 100, 1000]
    /// Why: Apple dokumentiert bis zu drei Minuten Verzoegerung, bevor neue
    /// Samples abrufbar sind. Fuenf Minuten Abstand halten den Cursor sicher
    /// hinter dieser Grenze (Spec §1.1).
    static let headroomSeconds: TimeInterval = 300
    /// Ein einzelner Abruf darf hoechstens 12 h umspannen (Apple-Doku).
    static let maxFetchSpanSeconds: TimeInterval = 12 * 3600

    /// Starts or extends the passive recorder to the longest interval Apple
    /// supports. Recording continues while the app is suspended or terminated;
    /// subsequent retrieval cycles renew the horizon when the process is alive.
    @discardableResult
    static func armPassiveRecording(for duration: TimeInterval) -> Bool {
        guard CMSensorRecorder.isAccelerometerRecordingAvailable() else { return false }
        if #available(watchOS 9.0, *) {
            switch CMSensorRecorder.authorizationStatus() {
            case .denied, .restricted:
                return false
            case .authorized, .notDetermined:
                break
            @unknown default:
                return false
            }
        }
        recorder.recordAccelerometer(
            forDuration: min(max(1, duration), maxFetchSpanSeconds)
        )
        return true
    }

    static func authorizationDescription() -> String {
        if #available(watchOS 9.0, *) {
            return String(describing: CMSensorRecorder.authorizationStatus())
        }
        return "unknown"
    }

    private static let startedAtKey = "sensorProbe.startedAt"
    private static let requestedSecondsKey = "sensorProbe.requestedSeconds"
    private static let operationIDKey = "sensorProbe.operationId"

    /// Starts a recorder run, at most once per `operationID`.
    ///
    /// Why idempotent: a probe run is a scarce measurement — the 12-hour one
    /// can only be repeated a few times a day. `sensor_probe_start` used to
    /// carry no request identity, so a duplicate WatchConnectivity delivery
    /// silently reset `startedAt` and invalidated a run already in progress.
    /// The caller now supplies a stable ID; a repeat of the same ID reports the
    /// original start instead of issuing a second `recordAccelerometer`, and a
    /// *different* ID is refused while a run is still inside its window so
    /// restarting is always a deliberate operator act.
    static func start(durationSeconds: Double, operationID: String) -> [String: Any] {
        let defaults = UserDefaults.standard
        let clamped = min(durationSeconds, maxFetchSpanSeconds)
        let storedID = defaults.string(forKey: operationIDKey)
        let storedStart = defaults.double(forKey: startedAtKey)
        let storedRequested = defaults.double(forKey: requestedSecondsKey)

        if !operationID.isEmpty, storedID == operationID, storedStart > 0 {
            return [
                "ok": true,
                "startedAt": storedStart,
                "requestedSeconds": storedRequested,
                "operationId": operationID,
                "alreadyStarted": true,
                "authorization": authorizationDescription()
            ]
        }

        let now = Date().timeIntervalSinceReferenceDate
        let stillRunning = storedStart > 0 && (now - storedStart) < storedRequested
        if stillRunning {
            return [
                "ok": false,
                "error": "probe already running",
                "startedAt": storedStart,
                "requestedSeconds": storedRequested,
                "operationId": storedID ?? "",
                "remainingSeconds": storedRequested - (now - storedStart)
            ]
        }

        recorder.recordAccelerometer(forDuration: clamped)
        defaults.set(now, forKey: startedAtKey)
        defaults.set(clamped, forKey: requestedSecondsKey)
        defaults.set(operationID, forKey: operationIDKey)
        return [
            "ok": true,
            "startedAt": now,
            "requestedSeconds": clamped,
            "operationId": operationID,
            "alreadyStarted": false,
            "authorization": authorizationDescription()
        ]
    }

    /// Reads recorded raw accelerometer samples for a span, in capture order.
    ///
    /// Shared with the passive tracker so production retrieval and the
    /// diagnostic report read the recorder through one code path — a probe
    /// that measured a different fetch than the tracker performs would be
    /// worth little.
    static func fetch(from: Date, to: Date) -> [PassiveSample] {
        guard to > from, let list = recorder.accelerometerData(from: from, to: to) else {
            return []
        }
        var out: [PassiveSample] = []
        // Why: CMSensorDataList only conforms to NSFastEnumeration, not Swift's
        // Sequence — bridge it explicitly to use a for-in loop.
        for case let s as CMRecordedAccelerometerData in
            IteratorSequence(NSFastEnumerationIterator(list)) {
            out.append(PassiveSample(
                timestamp: s.startDate.timeIntervalSinceReferenceDate,
                x: Float(s.acceleration.x),
                y: Float(s.acceleration.y),
                z: Float(s.acceleration.z)))
        }
        return out
    }

    static func report() -> [String: Any] {
        let defaults = UserDefaults.standard
        let startedAt = defaults.double(forKey: startedAtKey)
        let requested = defaults.double(forKey: requestedSecondsKey)
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

        // Why: elapsed wall-clock time since the probe started, capped the
        // same way the fetch window itself is capped. Distinct from the
        // returned samples' own (firstTimestamp, lastTimestamp) span — an
        // operator can evaluate before `requestedSeconds` have elapsed, and
        // coverage must be judged against how much time has actually passed,
        // not against the full requested duration (see SensorProbeEvaluator).
        let actualSpan = until.timeIntervalSince(from)
        let readStartedAt = Date()
        guard let list = recorder.accelerometerData(from: from, to: until) else {
            return [
                "ok": true,
                "sampleCount": 0,
                "firstTimestamp": 0.0,
                "lastTimestamp": 0.0,
                "requestedSeconds": requested,
                "actualSpanSeconds": actualSpan,
                "intervalBucketsMs": [String: Int](),
                "maxGapSeconds": 0.0,
                "nonMonotonicCount": 0,
                "fetchReturnedNil": true,
                "readDurationSeconds": Date().timeIntervalSince(readStartedAt),
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

        // Why amplitude at all: the probe measured timing only, so a recorder
        // stream that arrived at a perfect 50 Hz but in the wrong units, or
        // without gravity, looked flawless here while the classifier saw a
        // distribution it was never trained on. The training set's raw accel
        // sits at |a| = 0.990 g (sd 0.064) with a mean sample-to-sample step
        // of 0.031 g while writing and 0.024 g idle; these two numbers make
        // the on-device stream directly comparable to that.
        var magSum = 0.0
        var magSqSum = 0.0
        var stepSum = 0.0
        var stepCount = 0
        var previousAxes: (Double, Double, Double)?

        // Why: CMSensorDataList only conforms to NSFastEnumeration, not Swift's
        // Sequence — bridge it explicitly to use a for-in loop.
        for case let sample as CMRecordedAccelerometerData in IteratorSequence(NSFastEnumerationIterator(list)) {
            let t = sample.startDate.timeIntervalSinceReferenceDate
            if n == 0 { first = t }
            let a = sample.acceleration
            let mag = (a.x * a.x + a.y * a.y + a.z * a.z).squareRoot()
            magSum += mag
            magSqSum += mag * mag
            if let p = previousAxes {
                stepSum += (abs(a.x - p.0) + abs(a.y - p.1) + abs(a.z - p.2)) / 3
                stepCount += 1
            }
            previousAxes = (a.x, a.y, a.z)
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

        let magMean = n > 0 ? magSum / Double(n) : 0
        let magVar = n > 0 ? max(0, magSqSum / Double(n) - magMean * magMean) : 0

        return [
            "ok": true,
            "sampleCount": n,
            "firstTimestamp": first,
            "lastTimestamp": last,
            "requestedSeconds": requested,
            "actualSpanSeconds": actualSpan,
            "intervalBucketsMs": counts,
            "maxGapSeconds": maxGap,
            "nonMonotonicCount": nonMonotonic,
            "fetchReturnedNil": false,
            // Training reference: 0.990 g mean, 0.064 sd. A mean near 9.8
            // means m/s2, near 0 means gravity was removed upstream.
            "magnitudeMeanG": magMean,
            "magnitudeSdG": magVar.squareRoot(),
            // Training reference: 0.031 g writing, 0.024 g idle. Much lower
            // means the stream is smoother than what the model was trained on.
            "meanAbsStepG": stepCount > 0 ? stepSum / Double(stepCount) : 0,
            // Why: diagnostic gold for a spike that can only be run a few
            // times — lets the operator tell a slow-but-working read apart
            // from one that hit the sendMessage timeout on the iPhone side.
            "readDurationSeconds": Date().timeIntervalSince(readStartedAt),
            "authorization": authorizationDescription()
        ]
    }
}

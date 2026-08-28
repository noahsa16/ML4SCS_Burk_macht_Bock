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

        // Why: CMSensorDataList only conforms to NSFastEnumeration, not Swift's
        // Sequence — bridge it explicitly to use a for-in loop.
        for case let sample as CMRecordedAccelerometerData in IteratorSequence(NSFastEnumerationIterator(list)) {
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

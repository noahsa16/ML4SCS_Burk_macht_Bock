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

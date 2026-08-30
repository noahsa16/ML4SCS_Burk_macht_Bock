import Combine
import Foundation
import SwiftUI

/// A deliberately started writing session.
///
/// Holds everything in memory on purpose. Live and recorder windows never share
/// a `startMs`, so persisting both would double-count the day and idempotency
/// could not catch it. The passive path stays the single source of truth for
/// writing time; the only thing a session leaves behind is one `BestiaryEntry`.
@MainActor
final class FocusSessionStore: ObservableObject {
    static let shared = FocusSessionStore()

    enum Phase: Equatable {
        case idle
        case starting
        case running(startedAt: Date, targetSeconds: Double)
        case finished(BestiaryEntry)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var decisions: [PassiveDecision] = []

    private var builder = PassiveWindowBuilder(seqLen: 250, strideSamples: 125,
                                               nominalHz: 50, channels: 6)
    private let injected: PassiveClassifier?
    private var classifier: PassiveClassifier?
    // Why: `PassiveWindowBuilder` treats a non-monotonic sample as a recorder
    // artefact and drops it (correct for the passive path's long-lived
    // absolute clock). The live path instead gets fed successive batches
    // whose own timestamp base is the caller's concern, not this store's —
    // so windowing here runs on a clock this store owns: one tick per sample
    // actually consumed, anchored to the moment the session started.
    private var sessionAnchor: TimeInterval = 0
    private var sampleCount: Int = 0

    init(classifier: PassiveClassifier? = nil) {
        self.injected = classifier
    }

    var writingSeconds: Double {
        decisions.filter(\.writing).reduce(0) { $0 + $1.creditSeconds }
    }

    var segments: [FocusSegment] { FocusStrokes.segments(from: decisions) }

    /// Test seam: enter `running` without the Watch round-trip.
    func beginForTesting(targetSeconds: Double, at date: Date = Date()) {
        reset()
        classifier = injected
        sessionAnchor = date.timeIntervalSince1970
        phase = .running(startedAt: date, targetSeconds: targetSeconds)
    }

    /// Feeds samples handed over by `PhoneBridge` while a session runs.
    ///
    /// Only `x/y/z/rx/ry/rz` are trusted from the caller; each sample's
    /// windowing timestamp is resynthesized on `builder.nominalHz` from
    /// `sessionAnchor` — see the property comment for why.
    func consume(_ samples: [PassiveSample]) {
        guard case .running = phase else { return }
        if classifier == nil {
            classifier = injected ?? (try? ScrybeModel(resourceName: "ScrybeActive",
                                                       channels: 6, seqLen: 250))
        }
        guard let classifier else { return }
        let clocked = samples.map { sample -> PassiveSample in
            let ts = sessionAnchor + Double(sampleCount) / builder.nominalHz
            sampleCount += 1
            return PassiveSample(timestamp: ts, x: sample.x, y: sample.y, z: sample.z,
                                 rx: sample.rx, ry: sample.ry, rz: sample.rz)
        }
        for window in builder.append(clocked) {
            guard let logit = try? classifier.logit(window: window.values) else { continue }
            decisions.append(PassiveDecision(
                startMs: Int64(window.startTimestamp * 1000),
                endMs: Int64(window.endTimestamp * 1000),
                logit: logit,
                writing: logit >= 0,
                creditSeconds: builder.secondsPerWindow))
        }
    }

    private func reset() {
        decisions.removeAll()
        builder.reset()
        sampleCount = 0
    }
}

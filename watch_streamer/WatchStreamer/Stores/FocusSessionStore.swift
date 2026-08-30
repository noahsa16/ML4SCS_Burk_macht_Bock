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
        phase = .running(startedAt: date, targetSeconds: targetSeconds)
    }

    /// Feeds samples handed over by `PhoneBridge` while a session runs.
    ///
    /// Windows off each sample's own `timestamp` — no synthetic clock. A gap
    /// in the caller's stream (a WatchConnectivity stall, routine on the live
    /// path) must reset the buffer rather than being concatenated across, or
    /// the model would classify a window spanning signal that never happened.
    /// See `PassiveWindowBuilder`'s header for why that invariant lives there,
    /// not here.
    func consume(_ samples: [PassiveSample]) {
        guard case .running = phase else { return }
        if classifier == nil {
            classifier = injected ?? (try? ScrybeModel(resourceName: "ScrybeActive",
                                                       channels: 6, seqLen: 250))
        }
        guard let classifier else { return }
        for window in builder.append(samples) {
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
    }
}

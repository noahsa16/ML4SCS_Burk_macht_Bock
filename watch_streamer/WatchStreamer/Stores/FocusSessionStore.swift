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
        /// The session could not start classifying. Carries the reason so the
        /// screen can say what went wrong instead of drawing an empty page.
        case failed(String)
        case finished(BestiaryEntry)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var decisions: [PassiveDecision] = []

    private var builder = PassiveWindowBuilder(seqLen: 250, strideSamples: 125,
                                               nominalHz: 50, channels: 6)
    private let injected: PassiveClassifier?
    private let makeClassifier: () throws -> PassiveClassifier
    private var classifier: PassiveClassifier?
    // Why a stored message and not a bool: a missing or malformed bundle
    // resource will not fix itself while the process is alive, so one failed
    // attempt is final for the store's lifetime — not just for this session —
    // and every later `consume` (this session's or a later one) needs the
    // same reason to hand the phase without paying for a doomed retry.
    private var loadFailureMessage: String?

    init(classifier: PassiveClassifier? = nil,
         makeClassifier: @escaping () throws -> PassiveClassifier = {
             try ScrybeModel(resourceName: "ScrybeActive", channels: 6, seqLen: 250)
         }) {
        self.injected = classifier
        self.makeClassifier = makeClassifier
    }

    var writingSeconds: Double {
        decisions.filter(\.writing).reduce(0) { $0 + $1.creditSeconds }
    }

    var segments: [FocusSegment] { FocusStrokes.segments(from: decisions) }

    // MARK: - The creature in the margin

    /// Seeded from the session's start, so abandoning and restarting cannot
    /// reroll for a different animal.
    var currentSpecies: Int {
        guard case .running(let startedAt, _) = phase else { return 0 }
        return Bestiary.species(
            forSessionStartMs: Int64(startedAt.timeIntervalSince1970 * 1000))
    }

    var strokesTotal: Int { Marginalia.strokeCount(forSpecies: currentSpecies) }

    /// Grows with credited writing time, never with the number of bursts —
    /// see `Bestiary.strokesDrawn`. Pauses hold it still and never reduce it,
    /// and stopping early simply leaves the creature partly drawn.
    var strokesDrawn: Int {
        guard case .running(_, let target) = phase else { return 0 }
        return Bestiary.strokesDrawn(writingSeconds: writingSeconds,
                                     targetSeconds: target,
                                     strokesTotal: strokesTotal)
    }

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
        if let loadFailureMessage {
            // Why not re-attempt: the previous failure already established
            // the model will not load this run; re-throwing the same load
            // every batch would cost a bundle lookup and a manifest parse
            // for no new information.
            phase = .failed(loadFailureMessage)
            return
        }
        if classifier == nil {
            do {
                classifier = try injected ?? makeClassifier()
            } catch {
                let message = "model unavailable: \(error)"
                loadFailureMessage = message
                phase = .failed(message)
                return
            }
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

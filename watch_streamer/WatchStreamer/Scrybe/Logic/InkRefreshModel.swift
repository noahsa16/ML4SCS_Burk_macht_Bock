import CoreGraphics
import Foundation

/// What a single pull produced. Distinct from `FocusStore.watchUnreachable`,
/// which is the standing state: a pull has to report *its own* result, so a
/// sync that never reached the watch reads as a failed sync rather than as an
/// empty screen.
enum InkRefreshOutcome: Equatable {
    case updated(at: Date)
    case offline
}

/// The line the control shows. The model decides *which* status; the view owns
/// the wording, so the strings stay in the localization catalog.
enum InkRefreshStatus: Equatable {
    case hint
    case release
    case syncing
    case updated(Date)
    case offline
}

enum InkRefreshPhase: Equatable {
    case idle
    case pulling(progress: Double)
    case armed
    case refreshing
    case settled(InkRefreshOutcome)
}

/// State machine behind the ink pull-to-refresh.
///
/// Kept free of SwiftUI so the parts that are easy to get wrong — arming
/// exactly once per crossing, ignoring a release that never armed, ignoring a
/// second release mid-refresh — are testable without a UI host.
struct InkRefreshModel: Equatable {
    /// Pull distance in points at which the stroke closes into a ring.
    static let threshold: CGFloat = 88
    /// Height held open under the content while syncing and while settled.
    static let activeHeight: CGFloat = 78
    /// How long the result stays before the control retracts.
    static let settleSeconds: TimeInterval = 1.8

    private(set) var phase: InkRefreshPhase = .idle

    /// True while the control occupies layout space of its own.
    var isActive: Bool {
        switch phase {
        case .refreshing, .settled: return true
        case .idle, .pulling, .armed: return false
        }
    }

    var isArmed: Bool { phase == .armed }

    /// 0…1 — how far the stroke has closed. Full for every phase past arming,
    /// so the ring never re-opens once it has snapped shut.
    var ringProgress: Double {
        switch phase {
        case .idle: return 0
        case .pulling(let p): return p
        case .armed, .refreshing, .settled: return 1
        }
    }

    var status: InkRefreshStatus {
        switch phase {
        case .idle, .pulling: return .hint
        case .armed: return .release
        case .refreshing: return .syncing
        case .settled(.updated(let at)): return .updated(at)
        case .settled(.offline): return .offline
        }
    }

    /// Reports the current pull distance beyond the top of the content.
    /// - Returns: `true` exactly on the update that crosses the threshold, so
    ///   the caller fires one haptic per crossing instead of one per frame.
    @discardableResult
    mutating func pull(_ distance: CGFloat) -> Bool {
        // Why ignored while active: the content is padded down during a sync,
        // which the offset probe reports as a standing pull.
        guard !isActive else { return false }
        guard distance < Self.threshold else {
            let justArmed = phase != .armed
            phase = .armed
            return justArmed
        }
        phase = distance <= 0
            ? .idle
            : .pulling(progress: min(1, max(0, Double(distance / Self.threshold))))
        return false
    }

    /// The finger lifted.
    /// - Returns: `true` when a refresh should start.
    mutating func release() -> Bool {
        guard phase == .armed else {
            if case .pulling = phase { phase = .idle }
            return false
        }
        phase = .refreshing
        return true
    }

    /// Starts a refresh driven by the system pull gesture. Keeping this in the
    /// same state machine lets the branded completion state remain testable,
    /// while iOS owns gesture recognition and scroll coordination.
    @discardableResult
    mutating func beginSystemRefresh() -> Bool {
        guard !isActive else { return false }
        phase = .refreshing
        return true
    }

    mutating func finish(_ outcome: InkRefreshOutcome) {
        guard phase == .refreshing else { return }
        phase = .settled(outcome)
    }

    mutating func dismiss() {
        if case .settled = phase { phase = .idle }
    }

    /// Leaves any phase for `.idle`.
    ///
    /// `.refreshing` is not terminal and nothing else escapes it: `finish` only
    /// applies a result, `dismiss` only retracts a settled one, and
    /// `beginSystemRefresh` refuses to start while the model sits in it. A
    /// refresh that ends without a result — a cancelled task, a transport that
    /// never answered — therefore used to disable pull-to-refresh for the rest
    /// of the app's life. The caller says so explicitly instead.
    mutating func abandon() {
        phase = .idle
    }
}

import Combine
import Foundation

/// The Watch's copy of the creature the phone is drawing.
///
/// Read-only on this side: the phone owns the collection and credits the
/// writing time, the Watch only mirrors the current entry so the ring can
/// show the animal growing. Persisted so a relaunch shows the last known
/// state until the next poll reply refreshes it.
@MainActor
final class WatchCreatureStore: ObservableObject {
    static let shared = WatchCreatureStore()

    @Published private(set) var current: WatchCreatureSnapshot?

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        current = WatchCreatureSnapshot.load(from: defaults)
    }

    /// Applies the creature fields of a phone payload, if it carries any.
    /// A payload without them is not "no creature" — an older phone build
    /// never sends them — so it leaves the mirror untouched.
    func apply(from payload: [String: Any]) {
        guard let snapshot = WatchCreatureSnapshot.from(payload: payload),
              snapshot != current else { return }
        current = snapshot
        snapshot.store(in: defaults)
    }
}

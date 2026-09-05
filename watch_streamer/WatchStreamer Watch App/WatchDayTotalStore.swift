import Combine
import Foundation

/// The Watch's copy of the phone's writing total for today.
///
/// Read-only on this side: the phone owns the day's record, the Watch only
/// mirrors the figure so the ring can catch up with a focus session before
/// its own recorder has been read. Persisted so a relaunch shows the last
/// known total until the next poll reply refreshes it; `WatchDayTotal`
/// carries its day, so a stale one is ignored rather than shown tomorrow.
@MainActor
final class WatchDayTotalStore: ObservableObject {
    static let shared = WatchDayTotalStore()

    @Published private(set) var current: WatchDayTotal?

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        current = WatchDayTotal.load(from: defaults)
    }

    /// Applies the total carried by a phone payload, if it carries one. A
    /// payload without it is not "nothing written" — an older phone build
    /// never sends it — so it leaves the mirror untouched.
    func apply(from payload: [String: Any]) {
        guard let total = WatchDayTotal.from(payload: payload),
              total != current else { return }
        current = total
        total.store(in: defaults)
    }
}

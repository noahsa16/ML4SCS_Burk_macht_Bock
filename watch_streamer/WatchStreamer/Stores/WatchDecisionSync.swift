import Foundation

/// Asks the watch to hand over the writing decisions it has computed.
///
/// This is what pull-to-refresh now means: no server is involved, the watch is
/// the only source, and the phone keeps what arrives.
@MainActor
final class WatchDecisionSync {
    static let shared = WatchDecisionSync()

    private init() {}

    /// - Returns: whether the watch answered. The decisions themselves arrive
    ///   over `transferUserInfo` moments later, which is durable but not
    ///   instant — so a successful pull means "the watch heard us", not "the
    ///   numbers on screen already include it".
    func requestSync() async -> Bool {
        await withCheckedContinuation { continuation in
            // Why the flag: a continuation resumed twice traps. The reply path
            // is a callback we do not own, and its error branch also fires it.
            var resumed = false
            ServerCommandListener.shared.forwardToWatch([
                WatchPayloadKey.command: WatchCommandName.syncDecisions.rawValue,
                WatchPayloadKey.commandID: UUID().uuidString
            ]) { reply in
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: reply[WatchPayloadKey.ok] as? Bool ?? false)
            }
        }
    }
}

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
    /// How long to wait for the watch before calling the pull unanswered.
    /// The watch replies with what it already has and starts its retrieval
    /// cycle afterwards, so a healthy answer is near-instant; this bound only
    /// ever catches a transport that went silent.
    static let replyTimeout: TimeInterval = 8

    func requestSync(timeout: TimeInterval = WatchDecisionSync.replyTimeout) async -> Bool {
        await withCheckedContinuation { continuation in
            // Why the flag: a continuation resumed twice traps. The reply path
            // is a callback we do not own, and its error branch also fires it.
            var resumed = false

            // Why a deadline at all: `sendMessage` does not guarantee that
            // either of its handlers runs — the watch's own command dispatcher
            // documents the case where a reply never arrives. Resuming only
            // from the callback left this continuation suspended forever, and
            // the pull control has no way back out of its refreshing phase, so
            // one silent transport disabled pull-to-refresh until app restart.
            let deadline = DispatchWorkItem {
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: false)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout, execute: deadline)

            ServerCommandListener.shared.forwardToWatch([
                WatchPayloadKey.command: WatchCommandName.syncDecisions.rawValue,
                WatchPayloadKey.commandID: UUID().uuidString
            ]) { reply in
                guard !resumed else { return }
                resumed = true
                deadline.cancel()
                let ok = WatchPayloadValue.bool(reply[WatchPayloadKey.ok]) ?? false
                continuation.resume(returning: ok)
            }
        }
    }
}

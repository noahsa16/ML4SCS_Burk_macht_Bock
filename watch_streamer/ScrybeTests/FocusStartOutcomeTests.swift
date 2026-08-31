import Testing
@testable import WatchStreamer

@Suite("Focus start outcome")
struct FocusStartOutcomeTests {

    @Test func okMeansStarted() {
        #expect(FocusStartOutcome.from(reply: [WatchPayloadKey.ok: true]) == .started)
    }

    @Test func aKnownRefusalKeepsItsReason() {
        let reply: [String: Any] = [
            WatchPayloadKey.ok: false,
            WatchPayloadKey.error: FocusStartRefusal.recordingInProgress.rawValue,
        ]
        #expect(FocusStartOutcome.from(reply: reply) == .refused(.recordingInProgress))
    }

    /// Why unconfirmed and not unreachable: a deadline that passed says
    /// nothing about the Watch. Claiming it was reachable, or that it was
    /// not, would both be inventions.
    @Test func aMissingReplyIsUnconfirmed() {
        #expect(FocusStartOutcome.from(reply: [:]) == .unconfirmed)
    }

    @Test func aTransportFailureIsUnreachable() {
        #expect(FocusStartOutcome.unreachable != FocusStartOutcome.unconfirmed)
    }
}

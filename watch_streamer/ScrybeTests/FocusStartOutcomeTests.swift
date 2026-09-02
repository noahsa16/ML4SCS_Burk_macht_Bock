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

    /// Why this and not `.unreachable != .unconfirmed`: two distinct enum
    /// cases are trivially unequal, which proved nothing. What matters is that
    /// decoding a reply can NEVER yield `.unreachable` — that verdict belongs
    /// to the transport, and a reply that arrived is evidence against it, even
    /// one carrying the transport-failure marker.
    @Test func decodingNeverClaimsUnreachable() {
        let replies: [[String: Any]] = [
            [:],
            [WatchPayloadKey.ok: false],
            [WatchPayloadKey.ok: false, WatchPayloadKey.error: "something this build never heard of"],
            [WatchPayloadKey.ok: false, WatchPayloadKey.transportFailure: true],
        ]
        for reply in replies {
            #expect(FocusStartOutcome.from(reply: reply) != .unreachable)
        }
    }
}

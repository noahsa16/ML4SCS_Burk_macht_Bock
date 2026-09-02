import Testing
import Foundation
@testable import WatchStreamer

/// Records what a command dispatcher did with each transport, so the routing
/// table is asserted rather than assumed.
private final class TransportRecorder: @unchecked Sendable {
    private(set) var sentLive: [String] = []
    private(set) var replacedContext: [String] = []
    private(set) var queuedUserInfo: [String] = []
    private(set) var cancelledTransfers = 0

    /// Mirrors ServerCommandListener.forwardToWatch's gating. The production
    /// code and this fake read the same table on WatchCommandName, so a change
    /// to the table moves both together and a change to only one shows up here.
    func dispatch(_ raw: String, liveSendFails: Bool) {
        let route = WatchCommandName(rawValue: raw)
        if route?.mayReplaceDurableState ?? false {
            cancelledTransfers += 1
            replacedContext.append(raw)
        }
        sentLive.append(raw)
        guard liveSendFails else { return }
        if route?.mayFallBackToUserInfo ?? false {
            queuedUserInfo.append(raw)
        }
    }
}

@Suite("Transport routing matrix")
struct TransportMatrixTests {

    // §5.2: a read-only query used to cancel every queued transfer and
    // overwrite the application context on its way out, which could erase
    // pending start/stop recovery state.
    @Test("only durable state touches the context slot and the queue",
          arguments: WatchCommandName.allCases)
    func destructivePreludeIsGated(command: WatchCommandName) {
        let r = TransportRecorder()
        r.dispatch(command.rawValue, liveSendFails: false)
        let expected = command.transport == .durableState
        #expect(r.replacedContext.isEmpty != expected)
        #expect((r.cancelledTransfers > 0) == expected)
    }

    @Test("every command is attempted live", arguments: WatchCommandName.allCases)
    func everyCommandGoesLive(command: WatchCommandName) {
        let r = TransportRecorder()
        r.dispatch(command.rawValue, liveSendFails: false)
        #expect(r.sentLive == [command.rawValue])
    }

    // §5.2 second half: the Watch discards context and user-info copies of a
    // diagnostic, so queueing one produced a delivery guaranteed to be ignored.
    @Test("a failed live send queues a fallback only for durable state",
          arguments: WatchCommandName.allCases)
    func fallbackIsGated(command: WatchCommandName) {
        let r = TransportRecorder()
        r.dispatch(command.rawValue, liveSendFails: true)
        #expect(r.queuedUserInfo.isEmpty == (command.transport != .durableState))
    }

    @Test("an unrecognised command is treated as non-durable")
    func unknownCommandIsSafe() {
        let r = TransportRecorder()
        r.dispatch("something_new", liveSendFails: true)
        #expect(r.replacedContext.isEmpty)
        #expect(r.cancelledTransfers == 0)
        #expect(r.queuedUserInfo.isEmpty)
    }

    // §5.3: probe start is mirrored live only, so a queued duplicate cannot
    // restart a measurement already running.
    @Test("probe start is never mirrored through a durable transport")
    func probeStartIsLiveOnly() {
        let r = TransportRecorder()
        r.dispatch(WatchCommandName.sensorProbeStart.rawValue, liveSendFails: true)
        #expect(r.replacedContext.isEmpty)
        #expect(r.queuedUserInfo.isEmpty)
    }

    @Test("start and stop keep their full recovery path")
    func recordingCommandsKeepRecovery() {
        for command in [WatchCommandName.start, .stop] {
            let r = TransportRecorder()
            r.dispatch(command.rawValue, liveSendFails: true)
            #expect(r.replacedContext == [command.rawValue])
            #expect(r.queuedUserInfo == [command.rawValue])
        }
    }
}

// MARK: - Delivery-outcome ordering

/// Models the Watch's in-flight bookkeeping: a batch has exactly one terminal
/// outcome, whichever handler wins the reply-timeout race.
private struct DeliveryLedger {
    private var inFlight: Set<Int> = []
    private(set) var delivered = 0
    private(set) var fellBack = 0

    mutating func send(_ seq: Int) { inFlight.insert(seq) }

    mutating func replyArrived(_ seq: Int, samples: Int) {
        guard inFlight.remove(seq) != nil else { return }
        delivered += samples
    }

    mutating func errorArrived(_ seq: Int) {
        guard inFlight.remove(seq) != nil else { return }
        fellBack += 1
    }
}

@Suite("Delivery outcome ordering")
struct DeliveryOrderingTests {

    // §5.5: the reply handler computed stillInFlight, discarded it, and always
    // incremented the delivered count, so a batch whose fallback had already
    // completed was counted a second time.
    @Test("reply then error counts the batch once")
    func replyThenError() {
        var ledger = DeliveryLedger()
        ledger.send(1)
        ledger.replyArrived(1, samples: 10)
        ledger.errorArrived(1)
        #expect(ledger.delivered == 10)
        #expect(ledger.fellBack == 0)
    }

    @Test("error then reply counts the batch once")
    func errorThenReply() {
        var ledger = DeliveryLedger()
        ledger.send(1)
        ledger.errorArrived(1)
        ledger.replyArrived(1, samples: 10)
        #expect(ledger.delivered == 0)
        #expect(ledger.fellBack == 1)
    }

    @Test("a duplicate reply for the same batch is ignored")
    func duplicateReply() {
        var ledger = DeliveryLedger()
        ledger.send(1)
        ledger.replyArrived(1, samples: 10)
        ledger.replyArrived(1, samples: 10)
        #expect(ledger.delivered == 10)
    }

    @Test("independent batches each get their own outcome")
    func independentBatches() {
        var ledger = DeliveryLedger()
        ledger.send(1); ledger.send(2)
        ledger.replyArrived(1, samples: 10)
        ledger.errorArrived(2)
        #expect(ledger.delivered == 10)
        #expect(ledger.fellBack == 1)
    }
}

// MARK: - Durable acknowledgement

/// Models PhoneBridge's acknowledgement contract: a reply is only sent once the
/// write that includes the batch has completed.
private final class AckLedger: @unchecked Sendable {
    private var pending: [(Bool) -> Void] = []
    private(set) var acks: [Bool] = []

    /// Enqueues an acknowledgement that records its outcome here.
    func enqueue() {
        pending.append { [weak self] ok in self?.acks.append(ok) }
    }

    func writeCompleted(success: Bool) {
        let waiting = pending
        pending.removeAll()
        for ack in waiting { ack(success) }
    }

    var pendingCount: Int { pending.count }
}

@Suite("Durable acknowledgement")
struct DurableAckTests {

    // §5.4: replying before the batch was persisted released the Watch's copy
    // inside a window where a crash lost it.
    @Test("no acknowledgement is sent before the write completes")
    func ackWaitsForWrite() {
        let ledger = AckLedger()
        ledger.enqueue()
        #expect(ledger.acks.isEmpty)
        ledger.writeCompleted(success: true)
        #expect(ledger.acks == [true])
    }

    @Test("batches inside one debounce window share the write")
    func batchesShareOneWrite() {
        let ledger = AckLedger()
        for _ in 0..<3 { ledger.enqueue() }
        #expect(ledger.pendingCount == 3)
        ledger.writeCompleted(success: true)
        #expect(ledger.acks == [true, true, true])
    }

    @Test("a failed write acknowledges false so the Watch keeps its copy")
    func failedWriteAcksFalse() {
        let ledger = AckLedger()
        ledger.enqueue()
        ledger.writeCompleted(success: false)
        #expect(ledger.acks == [false])
    }

    @Test("no acknowledgement fires twice")
    func ackFiresOnce() {
        let ledger = AckLedger()
        ledger.enqueue()
        ledger.writeCompleted(success: true)
        ledger.writeCompleted(success: true)
        #expect(ledger.acks.count == 1)
    }
}

import Testing
@testable import WatchStreamer

@Suite("WatchCommand transport routing")
struct WatchCommandRoutingTests {

    @Test("start and stop are durable state")
    func durableState() {
        #expect(WatchCommandName.start.transport == .durableState)
        #expect(WatchCommandName.stop.transport == .durableState)
    }

    @Test("spill and probe-start are idempotent operations")
    func idempotentOperations() {
        #expect(WatchCommandName.drainSpill.transport == .idempotentOperation)
        #expect(WatchCommandName.clearSpill.transport == .idempotentOperation)
        #expect(WatchCommandName.sensorProbeStart.transport == .idempotentOperation)
    }

    @Test("report and parity are direct queries")
    func directQueries() {
        #expect(WatchCommandName.sensorProbeReport.transport == .directQuery)
        #expect(WatchCommandName.parityCheck.transport == .directQuery)
    }

    // The audit's §5.2: a query cancelled queued transfers and overwrote the
    // application context, so it could erase pending start/stop recovery.
    @Test("only durable state may replace the application context")
    func onlyDurableStateReplacesContext() {
        for name in WatchCommandName.allCases {
            #expect(name.mayReplaceDurableState == (name.transport == .durableState),
                    "\(name.rawValue)")
        }
    }

    // The audit's §5.2 second half: the queued fallback for a diagnostic is
    // discarded by the Watch, so reporting it as "queued" misleads the caller.
    @Test("only durable state may fall back to user-info")
    func onlyDurableStateFallsBack() {
        for name in WatchCommandName.allCases {
            #expect(name.mayFallBackToUserInfo == (name.transport == .durableState),
                    "\(name.rawValue)")
        }
    }

    @Test("diagnostics never include recording commands")
    func diagnosticSet() {
        #expect(WatchCommandName.sensorProbeStart.isDiagnostic)
        #expect(WatchCommandName.sensorProbeReport.isDiagnostic)
        #expect(WatchCommandName.parityCheck.isDiagnostic)
        #expect(!WatchCommandName.start.isDiagnostic)
        #expect(!WatchCommandName.stop.isDiagnostic)
        #expect(!WatchCommandName.drainSpill.isDiagnostic)
        #expect(!WatchCommandName.clearSpill.isDiagnostic)
        #expect(!WatchCommandName.syncDecisions.isDiagnostic)
    }

    // Why its own property: the passive sync must leave the recording
    // dispatcher alone like a diagnostic does — it can trigger a Core ML
    // retrieval cycle — but it is a product path, so calling it diagnostic
    // would put it in the Admin panel's category.
    @Test("the passive sync bypasses the recording dispatcher without being a diagnostic")
    func passiveSyncRouting() {
        #expect(WatchCommandName.syncDecisions.bypassesRecordingDispatcher)
        #expect(!WatchCommandName.syncDecisions.isDiagnostic)
        #expect(WatchCommandName.syncDecisions.transport == .idempotentOperation)
        // It must never overwrite start/stop recovery state.
        #expect(!WatchCommandName.syncDecisions.mayReplaceDurableState)
        #expect(!WatchCommandName.syncDecisions.mayFallBackToUserInfo)
    }

    @Test("every diagnostic also bypasses the recording dispatcher")
    func diagnosticsBypass() {
        for name in WatchCommandName.allCases where name.isDiagnostic {
            #expect(name.bypassesRecordingDispatcher)
        }
    }

    @Test("raw values match the wire protocol")
    func wireNames() {
        #expect(WatchCommandName.drainSpill.rawValue == "drain_spill")
        #expect(WatchCommandName.clearSpill.rawValue == "clear_spill")
        #expect(WatchCommandName.sensorProbeStart.rawValue == "sensor_probe_start")
        #expect(WatchCommandName.sensorProbeReport.rawValue == "sensor_probe_report")
        #expect(WatchCommandName.parityCheck.rawValue == "parity_check")
    }

    // A session start that lands minutes late is wrong, not late: it must never
    // fall back to the durable queue.
    @Test("focus commands are live-only operations that bypass the dispatcher")
    func focusCommandRouting() {
        for name in [WatchCommandName.focusStart, .focusStop] {
            #expect(name.transport == .idempotentOperation)
            #expect(name.bypassesRecordingDispatcher)
            #expect(!name.mayFallBackToUserInfo)
            #expect(!name.mayReplaceDurableState)
            #expect(!name.isDiagnostic)
        }
    }
}

/// The refusal has to survive the trip to the phone, because the phone is what
/// tells the user which of the two preconditions failed — and the two ask
/// opposite things: end the recording, versus grant a permission.
@Suite("Focus start outcome")
struct FocusStartOutcomeTests {

    // Pins wire format to enum. `replyForStart` writes the string and
    // `FocusStartOutcome.from` reads it back; a literal edited on one side
    // only would silently degrade every refusal to `.noAnswer`.
    @Test("every refusal the policy can emit decodes back into its case")
    func refusalsRoundTrip() {
        let cases: [(isRecording: Bool, authorized: Bool, expected: FocusStartRefusal)] = [
            (true, false, .recordingInProgress),
            (false, false, .workoutPermissionMissing)
        ]
        // Fails when a refusal is added without a case here, rather than
        // leaving the new one silently untested.
        #expect(cases.count == FocusStartRefusal.allCases.count)
        for c in cases {
            let reply = FocusCommandPolicy.replyForStart(isRecording: c.isRecording,
                                                         healthKitAuthorized: c.authorized)
            #expect(!reply.ok)
            let decoded = FocusStartOutcome.from(reply: [
                WatchPayloadKey.ok: reply.ok,
                WatchPayloadKey.error: reply.error ?? ""
            ])
            #expect(decoded == .refused(c.expected), "expected \(c.expected) for \(c)")
        }
    }

    @Test("an accepted start decodes as started")
    func acceptedStartDecodes() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: false, healthKitAuthorized: true)
        #expect(reply.ok)
        let decoded = FocusStartOutcome.from(reply: [WatchPayloadKey.ok: reply.ok])
        #expect(decoded == .started)
    }

    // `ok` crosses the same WatchConnectivity round trip as the six channel
    // values, so it can surface as Int or NSNumber rather than Bool. Read with
    // a naive `as? Bool`, an accepted start would decode as a refusal with no
    // reason — `.noAnswer` — and the session would never begin.
    @Test("an accepted start decodes whatever shape the transport gave `ok`")
    func acceptedStartSurvivesTheTransport() {
        #expect(FocusStartOutcome.from(reply: [WatchPayloadKey.ok: 1]) == .started)
        #expect(FocusStartOutcome.from(reply: [WatchPayloadKey.ok: "true"]) == .started)
        #expect(FocusStopOutcome.from(reply: [WatchPayloadKey.ok: 1]) == .stopped)
    }

    // A refusal this build cannot name is not a refusal it may misreport: the
    // user gets the generic message rather than one of the two specific ones.
    @Test("an unknown or absent reason is not reported as a known refusal")
    func unknownReasonFallsBack() {
        #expect(FocusStartOutcome.from(reply: [:]) == .noAnswer)
        #expect(FocusStartOutcome.from(reply: [WatchPayloadKey.ok: false,
                                               WatchPayloadKey.error: "something new"]) == .noAnswer)
    }

    // One number, two enforcers. The Watch caps the session independently
    // because a force-quit voids every phone-side path, and the two halves
    // reading different constants would be worse than either alone.
    @Test("phone and Watch cap a focus session at the same sixty minutes")
    func capIsSharedAndSixtyMinutes() {
        #expect(FocusCommandPolicy.sessionCapSeconds == 3600)
        #expect(FocusSessionStore.hardCapSeconds == FocusCommandPolicy.sessionCapSeconds)
    }
}

@Suite("WatchPayloadValue coercion")
struct WatchPayloadValueTests {

    @Test("int64 accepts every transport representation")
    func int64Coercion() {
        #expect(WatchPayloadValue.int64(Int(42)) == 42)
        #expect(WatchPayloadValue.int64(Int64(42)) == 42)
        #expect(WatchPayloadValue.int64(Double(42)) == 42)
        #expect(WatchPayloadValue.int64("42") == 42)
        #expect(WatchPayloadValue.int64("nope") == nil)
        #expect(WatchPayloadValue.int64(nil) == nil)
    }

    @Test("double accepts every transport representation")
    func doubleCoercion() {
        #expect(WatchPayloadValue.double(Int(50)) == 50.0)
        #expect(WatchPayloadValue.double(50.0) == 50.0)
        #expect(WatchPayloadValue.double("50") == 50.0)
        #expect(WatchPayloadValue.double(nil) == nil)
    }

    @Test("bool accepts numeric and string forms")
    func boolCoercion() {
        #expect(WatchPayloadValue.bool(true) == true)
        #expect(WatchPayloadValue.bool(1) == true)
        #expect(WatchPayloadValue.bool(0) == false)
        #expect(WatchPayloadValue.bool("true") == true)
        #expect(WatchPayloadValue.bool(nil) == nil)
    }
}

@Suite("CaptureSettings bounds")
struct CaptureSettingsTests {

    @Test("accepted rates match the documented band")
    func hzBounds() {
        #expect(CaptureSettings.isValidHz(50))
        #expect(CaptureSettings.isValidHz(100))
        #expect(CaptureSettings.isValidHz(10))
        #expect(CaptureSettings.isValidHz(200))
        #expect(!CaptureSettings.isValidHz(9))
        #expect(!CaptureSettings.isValidHz(201))
    }

    @Test("accepted batch sizes match the documented band")
    func batchBounds() {
        #expect(CaptureSettings.isValidBatchSize(1))
        #expect(CaptureSettings.isValidBatchSize(200))
        #expect(!CaptureSettings.isValidBatchSize(0))
        #expect(!CaptureSettings.isValidBatchSize(201))
    }
}

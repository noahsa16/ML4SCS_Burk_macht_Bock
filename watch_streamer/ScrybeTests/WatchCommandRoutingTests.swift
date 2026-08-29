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
    }

    @Test("raw values match the wire protocol")
    func wireNames() {
        #expect(WatchCommandName.drainSpill.rawValue == "drain_spill")
        #expect(WatchCommandName.clearSpill.rawValue == "clear_spill")
        #expect(WatchCommandName.sensorProbeStart.rawValue == "sensor_probe_start")
        #expect(WatchCommandName.sensorProbeReport.rawValue == "sensor_probe_report")
        #expect(WatchCommandName.parityCheck.rawValue == "parity_check")
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

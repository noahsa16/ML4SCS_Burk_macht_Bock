import Testing
import Foundation
@testable import WatchStreamer

/// `PhoneBridge.passiveSamples(from:)` is the pure mapping between a raw
/// watch-batch dictionary and the model's `PassiveSample` type. A mistake
/// here — a swapped axis, a wrong unit — never throws; it makes the
/// classifier confidently classify nonsense. These tests pin the channel
/// order, the ms→s conversion, and the malformed-input contract.
@Suite("PhoneBridge passive sample mapping")
struct PhoneBridgePassiveSamplesTests {

    /// Would still pass under a version that returned the right *values* but
    /// in the wrong *slots* (e.g. every field zeroed then only ax filled) —
    /// so every one of the six channels plus the timestamp gets its own
    /// distinct value, and every one is asserted individually.
    @Test("channel order is ax, ay, az, rx, ry, rz and ts converts ms to s")
    func channelOrderAndUnitConversion() throws {
        let raw: [String: Any] = [
            "ts": 5_000,
            "ax": 1.0, "ay": 2.0, "az": 3.0,
            "rx": 4.0, "ry": 5.0, "rz": 6.0,
        ]

        let result = PhoneBridge.passiveSamples(from: [raw])

        #expect(result.count == 1)
        let sample = try #require(result.first)
        #expect(sample.timestamp == 5.0)
        #expect(sample.x == 1.0)
        #expect(sample.y == 2.0)
        #expect(sample.z == 3.0)
        #expect(sample.rx == 4.0)
        #expect(sample.ry == 5.0)
        #expect(sample.rz == 6.0)
    }

    /// A sub-second offset that is not a multiple of 1000: would still pass
    /// under an implementation that truncated to whole seconds via integer
    /// division, so the assertion checks the fractional part explicitly.
    @Test("millisecond timestamps convert to fractional seconds, not truncated")
    func fractionalSecondConversion() throws {
        let raw: [String: Any] = ["ts": 2_500, "ax": 0.0, "ay": 0.0, "az": 0.0]

        let result = PhoneBridge.passiveSamples(from: [raw])

        let sample = try #require(result.first)
        #expect(sample.timestamp == 2.5)
    }

    /// Would still pass under an implementation that mapped `WatchPayloadValue
    /// .int64` failures to a zero timestamp instead of dropping the sample —
    /// so the surrounding valid samples are asserted present and in order,
    /// not just "the array is shorter".
    @Test("a sample missing ts is dropped, surrounding valid samples survive")
    func malformedSampleWithoutTsIsDropped() {
        let good1: [String: Any] = ["ts": 1_000, "ax": 1.0, "ay": 0, "az": 0]
        let malformed: [String: Any] = ["ax": 9.0, "ay": 9.0, "az": 9.0]
        let good2: [String: Any] = ["ts": 2_000, "ax": 2.0, "ay": 0, "az": 0]

        let result = PhoneBridge.passiveSamples(from: [good1, malformed, good2])

        #expect(result.count == 2)
        #expect(result[0].timestamp == 1.0)
        #expect(result[0].x == 1.0)
        #expect(result[1].timestamp == 2.0)
        #expect(result[1].x == 2.0)
    }

    /// `ts` crosses a WatchConnectivity/JSON round trip and may surface as a
    /// `Double` or a `String`, per `WatchPayloadValue.int64`'s own contract
    /// (see WatchCommand.swift). Would still pass under a naive `as? Int64`
    /// cast that only handled the `Int` case.
    @Test("ts tolerates Double and String encodings, not just Int")
    func tsToleratesAlternateEncodings() {
        let asDouble: [String: Any] = ["ts": 3_000.0, "ax": 1.0, "ay": 0, "az": 0]
        let asString: [String: Any] = ["ts": "4000", "ax": 2.0, "ay": 0, "az": 0]

        let result = PhoneBridge.passiveSamples(from: [asDouble, asString])

        #expect(result.count == 2)
        #expect(result[0].timestamp == 3.0)
        #expect(result[1].timestamp == 4.0)
    }

    /// Channel values cross the same WatchConnectivity/JSON round trip as
    /// `ts` and can arrive as `Int` when a sample happens to serialise as a
    /// whole number (see `WatchPayloadValue`'s header, WatchCommand.swift).
    /// Would still pass under a naive `as? Double` cast — the cast this test
    /// replaces — which silently turns such a value into 0 rather than
    /// throwing: exactly the "confidently classify nonsense" failure this
    /// file's header warns about, and exactly what none of the other
    /// fixtures above catch, since they all use Double literals.
    @Test("channel values tolerate Int encoding, not just Double")
    func channelValuesToleratesIntEncoding() throws {
        let raw: [String: Any] = ["ts": 1_000, "ax": 3, "ay": -2.5, "az": 0]

        let result = PhoneBridge.passiveSamples(from: [raw])

        let sample = try #require(result.first)
        #expect(sample.x == 3.0)
        #expect(sample.y == -2.5)
        #expect(sample.z == 0.0)
    }

    /// Missing accelerometer/gyro keys are not treated as malformed — only a
    /// missing/unparseable `ts` drops a sample. Would still pass under a
    /// version that dropped the whole sample on any missing key, since we
    /// assert the sample is present with defaulted-zero channels rather than
    /// merely checking the array length.
    @Test("missing channel keys default to zero rather than dropping the sample")
    func missingChannelKeysDefaultToZero() throws {
        let raw: [String: Any] = ["ts": 1_000]

        let result = PhoneBridge.passiveSamples(from: [raw])

        let sample = try #require(result.first)
        #expect(sample.x == 0)
        #expect(sample.y == 0)
        #expect(sample.z == 0)
        #expect(sample.rx == 0)
        #expect(sample.ry == 0)
        #expect(sample.rz == 0)
    }
}

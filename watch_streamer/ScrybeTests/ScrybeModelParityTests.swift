import Testing
import Foundation
@testable import WatchStreamer

private struct GoldenWindow: Decodable {
    let id: String
    let label: Int
    let logit: Double
    let proba: Double
    let data_b64: String
}

private struct GoldenFixture: Decodable {
    let model: String
    let seq_len: Int
    let n_channels: Int
    let windows: [GoldenWindow]
}

@Suite("ScrybeModel Paritaet (P2, iPhone)")
struct ScrybeModelParityTests {

    private func fixture() throws -> GoldenFixture {
        let url = try #require(Bundle(for: BundleMarker.self)
            .url(forResource: "golden_windows_empty_DEMO", withExtension: "json"))
        return try JSONDecoder().decode(GoldenFixture.self,
                                        from: Data(contentsOf: url))
    }

    @Test("aktives Modell reproduziert alle Golden-Logits innerhalb 1e-4")
    func activeModelMatchesPyTorch() throws {
        let fx = try fixture()
        try #require(!fx.windows.isEmpty)
        let model = try ScrybeModel(resourceName: "ScrybeActive",
                                    channels: fx.n_channels,
                                    seqLen: fx.seq_len)
        for w in fx.windows {
            let window = try #require(ScrybeModel.decodeBase64Window(w.data_b64))
            #expect(window.count == fx.seq_len * fx.n_channels)
            let got = try model.logit(window: window)
            #expect(abs(Double(got) - w.logit) <= 1e-4, "\(w.id)")
        }
    }

    @Test("Klassifikation bei Schwelle 0,5 ist identisch")
    func classificationMatches() throws {
        let fx = try fixture()
        try #require(!fx.windows.isEmpty)
        let model = try ScrybeModel(resourceName: "ScrybeActive",
                                    channels: fx.n_channels,
                                    seqLen: fx.seq_len)
        for w in fx.windows {
            let window = try #require(ScrybeModel.decodeBase64Window(w.data_b64))
            #expect(try model.isWriting(window: window) == (w.proba >= 0.5),
                    "\(w.id)")
        }
    }

    @Test("falsche Fensterlaenge wird abgewiesen")
    func rejectsWrongLength() throws {
        let model = try ScrybeModel(resourceName: "ScrybeActive", channels: 6)
        #expect(throws: ScrybeModelError.self) {
            _ = try model.logit(window: [Float](repeating: 0, count: 10))
        }
    }
}

/// Marker, um an das Test-Bundle zu kommen.
private final class BundleMarker {}

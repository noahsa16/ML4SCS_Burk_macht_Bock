import Testing
import Foundation
@testable import WatchStreamer

@Suite("PassiveModelManifest")
struct PassiveModelManifestTests {

    private func activeManifest() throws -> PassiveModelManifest {
        try PassiveModelManifest.load(resourceName: "ScrybeActive", in: .main)
    }

    @Test("the shipped active sidecar decodes")
    func decodesShippedSidecar() throws {
        let m = try activeManifest()
        #expect(m.nChannels == 6)
        #expect(m.seqLen == 250)
        #expect(m.fsHz == 50)
        #expect(m.inputName == "window")
        #expect(m.outputName == "logit")
        #expect(!m.sourceCheckpointSHA256.isEmpty)
    }

    @Test("a matching shape verifies")
    func matchingShapePasses() throws {
        try activeManifest().verify(channels: 6, seqLen: 250)
    }

    @Test("a wrong channel count is rejected")
    func wrongChannelsRejected() throws {
        let m = try activeManifest()
        #expect(throws: PassiveModelManifestError.self) {
            try m.verify(channels: 3, seqLen: 250)
        }
    }

    @Test("a wrong sequence length is rejected")
    func wrongSeqLenRejected() throws {
        let m = try activeManifest()
        #expect(throws: PassiveModelManifestError.self) {
            try m.verify(channels: 6, seqLen: 500)
        }
    }

    @Test("a missing sidecar is reported, not ignored")
    func missingSidecar() {
        #expect(throws: PassiveModelManifestError.self) {
            _ = try PassiveModelManifest.load(resourceName: "NoSuchModel", in: .main)
        }
    }

    // The point of the whole mechanism: a fixture and a model from different
    // exports must not be able to pass parity together.
    @Test("a fixture from another checkpoint is rejected")
    func fixtureCheckpointMismatch() throws {
        let m = try activeManifest()
        #expect(throws: PassiveModelManifestError.self) {
            try m.verifyFixtureCheckpoint("0000000000000000000000000000000000000000000000000000000000000000")
        }
    }

    @Test("the shipped active fixture matches the shipped active model")
    func shippedPairAgrees() throws {
        struct Fixture: Decodable { let checkpoint_sha256: String }
        let url = try #require(Bundle(for: ManifestBundleMarker.self)
            .url(forResource: "golden_windows_active", withExtension: "json"))
        let fx = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url))
        try activeManifest().verifyFixtureCheckpoint(fx.checkpoint_sha256)
    }

    @Test("the model wrapper refuses a shape the artifact does not declare")
    func wrapperRejectsWrongShape() {
        #expect(throws: (any Error).self) {
            _ = try ScrybeModel(resourceName: "ScrybeActive", channels: 3, seqLen: 250)
        }
    }

    @Test("the model wrapper exposes the artifact's own input and output names")
    func wrapperUsesManifestNames() throws {
        let model = try ScrybeModel(resourceName: "ScrybeActive", channels: 6)
        #expect(model.inputName == "window")
        #expect(model.outputName == "logit")
        #expect(model.manifest.model == "tcn_bigru")
    }
}

/// Marker, um an das Test-Bundle zu kommen.
private final class ManifestBundleMarker {}

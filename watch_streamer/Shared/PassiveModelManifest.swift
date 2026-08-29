import Foundation

public enum PassiveModelManifestError: Error, Equatable {
    case missingSidecar(String)
    case malformedSidecar(String)
    case shapeMismatch(field: String, expected: String, got: String)
    case checkpointMismatch(sidecar: String, fixture: String)
}

/// The provenance sidecar shipped beside each Core ML artifact.
///
/// Why verify at runtime: parity previously took its shape from the golden
/// fixture and its channel count from the caller, and checked neither against
/// the artifact actually bundled. A stale model paired with a stale fixture
/// stays internally consistent — every window matches — while being the wrong
/// deployment artifact. Comparing the checkpoint hash the two files claim
/// closes that, because they can only agree if they came from one export.
public struct PassiveModelManifest: Decodable, Equatable {
    public let artifact: String
    public let sha256: String
    public let model: String
    public let channels: String
    public let nChannels: Int
    public let seqLen: Int
    public let fsHz: Double
    public let threshold: Double
    public let inputName: String
    public let outputName: String
    public let sourceCheckpoint: String
    public let sourceCheckpointSHA256: String

    private enum CodingKeys: String, CodingKey {
        case artifact
        case sha256
        case model
        case channels
        case nChannels = "n_channels"
        case seqLen = "seq_len"
        case fsHz = "fs_hz"
        case threshold
        case inputName = "input_name"
        case outputName = "output_name"
        case sourceCheckpoint = "source_checkpoint"
        case sourceCheckpointSHA256 = "source_checkpoint_sha256"
    }

    /// Loads `<resourceName>.json` from a bundle.
    public static func load(resourceName: String, in bundle: Bundle) throws -> PassiveModelManifest {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            throw PassiveModelManifestError.missingSidecar(resourceName)
        }
        do {
            return try JSONDecoder().decode(PassiveModelManifest.self,
                                            from: Data(contentsOf: url))
        } catch {
            throw PassiveModelManifestError.malformedSidecar(
                "\(resourceName): \(error)")
        }
    }

    /// Throws unless the artifact's declared input schema is the one the caller
    /// is about to build a tensor for.
    public func verify(channels: Int, seqLen: Int) throws {
        guard channels == nChannels else {
            throw PassiveModelManifestError.shapeMismatch(
                field: "n_channels",
                expected: String(nChannels), got: String(channels))
        }
        guard seqLen == self.seqLen else {
            throw PassiveModelManifestError.shapeMismatch(
                field: "seq_len",
                expected: String(self.seqLen), got: String(seqLen))
        }
    }

    /// Throws unless a golden fixture was exported from the same checkpoint.
    public func verifyFixtureCheckpoint(_ fixtureSHA256: String) throws {
        guard fixtureSHA256 == sourceCheckpointSHA256 else {
            throw PassiveModelManifestError.checkpointMismatch(
                sidecar: sourceCheckpointSHA256, fixture: fixtureSHA256)
        }
    }
}

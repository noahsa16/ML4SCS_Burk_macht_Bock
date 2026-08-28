import CoreML
import Foundation

enum WatchScrybeModelError: Error {
    case missingResource(String)
    case badWindowLength(expected: Int, got: Int)
    case missingOutput
}

/// Core-ML-Wrapper der Watch. Bewusst identisch aufgebaut zu ScrybeModel im
/// iPhone-Target; getrennte Datei, weil die Ordnersynchronisation des
/// Xcode-Projekts Target-Zugehörigkeit über die Lage bestimmt.
final class WatchScrybeModel {
    let seqLen: Int
    let channels: Int
    private let model: MLModel

    init(resourceName: String, channels: Int, seqLen: Int = 250) throws {
        guard let url = Bundle.main.url(forResource: resourceName,
                                        withExtension: "mlmodelc") else {
            throw WatchScrybeModelError.missingResource(resourceName)
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly
        self.model = try MLModel(contentsOf: url, configuration: config)
        self.seqLen = seqLen
        self.channels = channels
    }

    func logit(window: [Float]) throws -> Float {
        let expected = seqLen * channels
        guard window.count == expected else {
            throw WatchScrybeModelError.badWindowLength(expected: expected,
                                                        got: window.count)
        }
        let array = try MLMultiArray(shape: [1, NSNumber(value: seqLen),
                                             NSNumber(value: channels)],
                                     dataType: .float32)
        let buffer = array.dataPointer.bindMemory(to: Float.self, capacity: expected)
        window.withUnsafeBufferPointer { buffer.update(from: $0.baseAddress!,
                                                       count: expected) }
        let input = try MLDictionaryFeatureProvider(
            dictionary: ["window": MLFeatureValue(multiArray: array)])
        let out = try model.prediction(from: input)
        guard let v = out.featureValue(for: "logit")?.multiArrayValue else {
            throw WatchScrybeModelError.missingOutput
        }
        return v[0].floatValue
    }

    static func decodeBase64Window(_ b64: String) -> [Float]? {
        guard let data = Data(base64Encoded: b64) else { return nil }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float32.self)) }
    }
}

private struct WatchGoldenWindow: Decodable {
    let id: String
    let logit: Double
    let proba: Double
    let data_b64: String
}

private struct WatchGoldenFixture: Decodable {
    let seq_len: Int
    let n_channels: Int
    let windows: [WatchGoldenWindow]
}

enum WatchParityCheck {
    static let tolerance = 1e-4

    static func run() -> [String: Any] {
        do {
            guard let url = Bundle.main.url(forResource: "golden_windows_passive",
                                            withExtension: "json") else {
                return ["ok": false, "error": "fixture missing"]
            }
            let fx = try JSONDecoder().decode(WatchGoldenFixture.self,
                                              from: Data(contentsOf: url))
            // Why: eine leere Fixture wuerde als "0/0 bestanden" durchgehen —
            // ein Gate, das nicht schliessen kann, ist schlechter als keines.
            guard !fx.windows.isEmpty else {
                return ["ok": false, "error": "fixture is empty"]
            }
            let model = try WatchScrybeModel(resourceName: "ScrybePassive",
                                             channels: fx.n_channels,
                                             seqLen: fx.seq_len)
            var maxDiff = 0.0
            var passed = 0
            var classMismatches = 0
            var failedIds: [String] = []

            for w in fx.windows {
                guard let window = decode(w.data_b64) else {
                    failedIds.append(w.id); continue
                }
                let got = Double(try model.logit(window: window))
                let diff = abs(got - w.logit)
                maxDiff = max(maxDiff, diff)
                if (got >= 0) != (w.proba >= 0.5) { classMismatches += 1 }
                if diff <= tolerance { passed += 1 } else { failedIds.append(w.id) }
            }

            return [
                "ok": true,
                "total": fx.windows.count,
                "passed": passed,
                "maxAbsDiff": maxDiff,
                "classMismatches": classMismatches,
                "failedIds": Array(failedIds.prefix(5))
            ]
        } catch {
            return ["ok": false, "error": String(describing: error)]
        }
    }

    private static func decode(_ b64: String) -> [Float]? {
        WatchScrybeModel.decodeBase64Window(b64)
    }
}

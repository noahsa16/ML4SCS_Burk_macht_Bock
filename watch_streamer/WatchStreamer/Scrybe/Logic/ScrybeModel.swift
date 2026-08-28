import CoreML
import Foundation

enum ScrybeModelError: Error {
    case missingResource(String)
    case badWindowLength(expected: Int, got: Int)
    case missingOutput(String)
}

/// Dünner Core-ML-Wrapper: ein Fenster rein, ein Logit raus.
///
/// Die Compute-Konfiguration ist bewusst auf `.cpuOnly` festgenagelt
/// (Spec §7.3): FP32, deterministisch, kein stiller Fallback bei nicht
/// unterstützten Operationen. Bei 9k bzw. 19k Parametern ist der Preis
/// dafür gegenüber der Sensorik vernachlässigbar.
final class ScrybeModel {
    static let inputName = "window"
    static let outputName = "logit"

    let seqLen: Int
    let channels: Int
    private let model: MLModel

    init(resourceName: String, channels: Int, seqLen: Int = 250) throws {
        guard let url = Bundle.main.url(forResource: resourceName,
                                        withExtension: "mlmodelc") else {
            throw ScrybeModelError.missingResource(resourceName)
        }
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly
        self.model = try MLModel(contentsOf: url, configuration: config)
        self.seqLen = seqLen
        self.channels = channels
    }

    /// `window` ist row-major (seqLen, channels) — dieselbe Reihenfolge wie
    /// `build_raw_windows` in Python.
    func logit(window: [Float]) throws -> Float {
        let expected = seqLen * channels
        guard window.count == expected else {
            throw ScrybeModelError.badWindowLength(expected: expected,
                                                   got: window.count)
        }
        let array = try MLMultiArray(shape: [1, NSNumber(value: seqLen),
                                             NSNumber(value: channels)],
                                     dataType: .float32)
        let buffer = array.dataPointer.bindMemory(to: Float.self, capacity: expected)
        window.withUnsafeBufferPointer { buffer.update(from: $0.baseAddress!,
                                                       count: expected) }

        let input = try MLDictionaryFeatureProvider(
            dictionary: [Self.inputName: MLFeatureValue(multiArray: array)])
        let out = try model.prediction(from: input)
        guard let value = out.featureValue(for: Self.outputName)?.multiArrayValue else {
            throw ScrybeModelError.missingOutput(Self.outputName)
        }
        return value[0].floatValue
    }

    func isWriting(window: [Float]) throws -> Bool {
        try logit(window: window) >= 0   // Logit >= 0 entspricht Proba >= 0.5
    }

    /// Dekodiert das base64-float32-Format der Golden-Vektoren.
    static func decodeBase64Window(_ b64: String) -> [Float]? {
        guard let data = Data(base64Encoded: b64) else { return nil }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float32.self)) }
    }
}

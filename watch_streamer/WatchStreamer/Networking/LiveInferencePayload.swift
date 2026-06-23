import Foundation

struct LiveInferencePayload: Decodable, Equatable, Sendable {
    let writing: Bool
    let proba: Double
    let fsHz: Double
    let todayWritingSeconds: Double
    let modelId: String?
    let personId: String?
    let windowSamples: Int?
    let rateMismatch: Bool?
    let trainedFsHz: Double?
    let missingChannels: Bool?

    enum CodingKeys: String, CodingKey {
        case writing, proba
        case fsHz = "fs_hz"
        case todayWritingSeconds = "today_writing_seconds"
        case modelId = "model_id"
        case personId = "person_id"
        case windowSamples = "window_samples"
        case rateMismatch = "rate_mismatch"
        case trainedFsHz = "trained_fs_hz"
        case missingChannels = "missing_channels"
    }
}

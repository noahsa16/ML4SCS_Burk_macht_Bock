import Foundation

/// UserDefaults keys and capture bounds shared by both devices.
///
/// These were literals spread across `PhoneBridge`, `ServerCommandListener`,
/// `SettingsCard` and `MotionManager`. A configuration migration had no
/// compiler protection, and the requested/effective distinction was only
/// documented in comments.
public nonisolated enum CaptureSettings {
    /// The server address the phone uploads to, as typed by the operator.
    public static let serverIPKey = "serverIP"
    /// The rate the phone *asks* the Watch to sample at.
    public static let requestedHzKey = "requestedHz"
    /// The batch size the phone asks the Watch to use.
    public static let batchSizeKey = "batchSize"
    /// The rate the Watch actually applies, persisted so it survives a relaunch.
    public static let effectiveHzKey = "effectiveHz"
    /// The batch size the Watch actually applies.
    public static let effectiveBatchSizeKey = "effectiveBatchSize"
    /// Shared secret sent with every server request, when configured.
    public static let serverTokenKey = "scrybe.serverToken"

    public static let defaultHz = 50.0
    public static let defaultBatchSize = 10

    /// Accepted bounds for a configuration push. A value outside these is
    /// ignored rather than clamped, so a malformed payload cannot quietly
    /// reconfigure a running study.
    public static let hzRange: ClosedRange<Double> = 10.0...200.0
    public static let batchSizeRange: ClosedRange<Int> = 1...200

    public static func isValidHz(_ hz: Double) -> Bool { hzRange.contains(hz) }
    public static func isValidBatchSize(_ n: Int) -> Bool { batchSizeRange.contains(n) }
}

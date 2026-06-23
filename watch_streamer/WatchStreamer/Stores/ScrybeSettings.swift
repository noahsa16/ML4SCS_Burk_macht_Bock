import Foundation

enum ScrybeSettings {
    // Daily writing goal in seconds; default 2 h.
    static let goalKey = "scrybe.dailyGoalSeconds"
    static let defaultGoalSeconds: Double = 2 * 3600

    // Local admin PIN — a lock against accidental opens, not a security feature.
    static let pinKey = "scrybe.adminPIN"
    static let defaultPIN = "0000"

    static var goalSeconds: Double {
        let v = UserDefaults.standard.double(forKey: goalKey)
        return v > 0 ? v : defaultGoalSeconds
    }

    static var adminPIN: String {
        let v = UserDefaults.standard.string(forKey: pinKey)
        return (v?.isEmpty == false) ? v! : defaultPIN
    }
}

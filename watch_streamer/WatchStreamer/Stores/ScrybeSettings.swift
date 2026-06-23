import Foundation

enum ScrybeSettings {
    // Daily writing goal in seconds; default 2 h.
    static let goalKey = "scrybe.dailyGoalSeconds"
    static let defaultGoalSeconds: Double = 2 * 3600

    // Local admin PIN — a lock against accidental opens, not a security feature.
    static let pinKey = "scrybe.adminPIN"
    static let defaultPIN = "0000"

    // First-run onboarding completion flag.
    static let onboardingDoneKey = "scrybe.onboardingDone"

    // Daily reminder: on/off + minutes after midnight (default 20:00 = 1200).
    static let reminderEnabledKey = "scrybe.reminderEnabled"
    static let reminderMinutesKey = "scrybe.reminderMinutes"
    static let defaultReminderMinutes = 20 * 60

    // UI language override: "system" | "de" | "en".
    static let languageKey = "scrybe.language"
    static let defaultLanguage = "system"

    // Calendar.firstWeekday: 1 = Sunday, 2 = Monday (default Monday).
    static let weekStartKey = "scrybe.weekStart"
    static let defaultWeekStart = 2

    static var goalSeconds: Double {
        let v = UserDefaults.standard.double(forKey: goalKey)
        return v > 0 ? v : defaultGoalSeconds
    }

    /// Resolved app locale for the in-app DE/EN override (nil = follow system).
    static var localeOverride: Locale? {
        switch UserDefaults.standard.string(forKey: languageKey) {
        case "de": return Locale(identifier: "de")
        case "en": return Locale(identifier: "en")
        default: return nil
        }
    }

    static var adminPIN: String {
        let v = UserDefaults.standard.string(forKey: pinKey)
        return (v?.isEmpty == false) ? v! : defaultPIN
    }
}

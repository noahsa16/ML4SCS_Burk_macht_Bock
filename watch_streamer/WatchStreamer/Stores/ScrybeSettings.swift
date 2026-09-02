import Foundation

enum ScrybeSettings {
    // Daily writing goal in seconds; default 2 h.
    static let goalKey = ScrybeGoal.defaultsKey
    static let defaultGoalSeconds = ScrybeGoal.defaultSeconds

    // Local admin PIN — a lock against accidental opens, not a security
    // feature. The gate is a hidden gesture plus this code; anyone who
    // discovers the gesture and the code reaches the repair controls, so it
    // gates operator tooling in a prototype, never sensitive access.
    static let pinKey = "scrybe.adminPIN"
    /// Only in effect until the operator sets their own. `hasCustomPIN` is
    /// false while it stands, and the gate forces a change on first entry —
    /// a shipped default must not remain the live credential.
    static let defaultPIN = "0000"

    static var hasCustomPIN: Bool {
        let stored = UserDefaults.standard.string(forKey: pinKey) ?? ""
        return !stored.isEmpty && stored != defaultPIN
    }

    static func setAdminPIN(_ pin: String) {
        UserDefaults.standard.set(pin, forKey: pinKey)
    }

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

    // Length of a deliberately started focus session, in whole minutes.
    // Separate from `goalKey`: that one is the day's target, this one is the
    // last session length, and the ready screen opens with it so it never has
    // to ask.
    static let focusDurationKey = "scrybe.focusDurationMinutes"
    static let defaultFocusMinutes = 25

    /// Every key "delete all local data" must remove. Kept here rather than
    /// inline in the view so a new setting cannot be added without a place
    /// that erases it.
    static let resettableKeys = [
        goalKey, reminderEnabledKey, reminderMinutesKey,
        languageKey, weekStartKey, focusDurationKey,
    ]

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

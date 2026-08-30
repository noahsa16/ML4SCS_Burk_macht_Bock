import Foundation

extension FocusStartRefusal {
    /// The refusal in the user's language.
    ///
    /// One source for two callers: `FocusSessionView`, which shows it when the
    /// Watch answers, and `FocusSessionStore`, which has to say the same thing
    /// when a study recording preempts a start still in flight.
    ///
    /// Here and not in `Shared/`: that folder compiles into the Watch app too,
    /// which carries no string catalog, so `String(localized:)` there would
    /// ship keys with nothing behind them.
    ///
    /// The two cases ask opposite things — end the recording, or grant a
    /// permission — so they get their own copy rather than one message
    /// covering both.
    var message: String {
        switch self {
        case .recordingInProgress:
            return String(localized: "Es läuft gerade eine Aufnahme. Beende sie zuerst.")
        case .workoutPermissionMissing:
            return String(localized: "Der Uhr fehlt die Workout-Freigabe. Erteile sie in den Health-Einstellungen.")
        }
    }
}

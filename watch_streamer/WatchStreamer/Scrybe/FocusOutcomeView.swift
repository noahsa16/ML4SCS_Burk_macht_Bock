import SwiftUI

/// Why a start did not become a session: refused, unconfirmed or unreachable.
/// Each carries the next action that fits it — a retry helps a timeout and
/// does nothing for a missing permission.
///
/// An ENDING is not shown here. The written page is the outcome of an ordinary
/// ending, and an exceptional reason is a remark beside it — see
/// `FocusSessionStore.FinishReason.note`.
struct FocusOutcomeView: View {
    enum Outcome: Equatable {
        case refused(FocusStartRefusal)
        case unconfirmed
        case unreachable
    }

    let outcome: Outcome
    let onRetry: () -> Void
    let onDismiss: () -> Void

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 16) {
            Text(outcome.title)
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
            Text(outcome.detail)
                .font(.subheadline)
                .foregroundStyle(theme.secondaryInk)
                .multilineTextAlignment(.center)
            if showsRetry {
                button("Erneut versuchen", action: onRetry)
            }
            button("Zurück", action: onDismiss)
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 16)
        // Why animate: a stop the Watch never confirms rewrites this screen
        // after it is already up. The correction is honest and must land, but
        // it should read as the same screen changing its mind, not as a flash.
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: outcome)
    }

    private var showsRetry: Bool {
        switch outcome {
        case .unconfirmed, .unreachable: return true
        case .refused: return false
        }
    }

    private func button(_ label: LocalizedStringKey,
                        action: @escaping () -> Void) -> some View {
        ScrybePrimaryButton(label, action: action)
    }
}

extension FocusOutcomeView.Outcome {
    var title: String {
        switch self {
        case .refused(.recordingInProgress):
            return String(localized: "Die Uhr nimmt gerade auf")
        case .refused(.workoutPermissionMissing):
            return String(localized: "Die Workout-Freigabe fehlt")
        case .unconfirmed:
            return String(localized: "Start unbestätigt")
        case .unreachable:
            return String(localized: "Die Uhr ist nicht erreichbar")
        }
    }

    var detail: String {
        switch self {
        case .refused(.recordingInProgress):
            return String(localized: "Beende sie zuerst, dann kann die Sitzung starten.")
        case .refused(.workoutPermissionMissing):
            return String(localized: "Erteile sie in den Health-Einstellungen.")
        case .unconfirmed:
            return String(localized: "Binnen 8 Sekunden kam keine Antwort. Ob die Uhr misst, ist damit offen.")
        case .unreachable:
            return String(localized: "Die Anfrage kam nicht an. Prüfe, ob die Uhr in Reichweite ist.")
        }
    }
}

extension FocusSessionStore.FinishReason {
    /// What to remark beside the finished page, or `nil` when the page already
    /// says it. Ending it yourself needs no note: the written page and its
    /// credited time are the whole statement. The other four are things the
    /// page cannot show — including the cap, which otherwise looks like the
    /// session simply stopping on its own.
    var note: (title: String, detail: String)? {
        switch self {
        case .user:
            return nil
        case .hardCap:
            return (String(localized: "Zeitgrenze erreicht"),
                    String(localized: "Nach zwei Stunden endet eine Sitzung von selbst."))
        case .studyPreemption:
            return (String(localized: "Eine Aufnahme hat die Uhr übernommen"),
                    String(localized: "Die Sitzung endete, weil eine Studien-Aufnahme die Sensoren braucht."))
        case .watchFailure:
            return (String(localized: "Die Uhr konnte nicht weiter messen"),
                    String(localized: "Prüfe die Workout-Freigabe in den Health-Einstellungen."))
        case .stopUnconfirmed:
            return (String(localized: "Beendet, ohne Bestätigung"),
                    String(localized: "Die Uhr hat den Stopp nicht bestätigt. Der Sensorstrom läuft womöglich weiter."))
        }
    }
}

import SwiftUI

/// Why a session is not running: refused, unconfirmed, unreachable, or simply
/// over. Each carries the next action that fits it — a retry helps a timeout
/// and does nothing for a missing permission.
struct FocusOutcomeView: View {
    enum Outcome: Equatable {
        case refused(FocusStartRefusal)
        case unconfirmed
        case unreachable
        case finished(FocusSessionStore.FinishReason)
    }

    let outcome: Outcome
    let onRetry: () -> Void
    let onDismiss: () -> Void

    @Environment(\.scrybe) private var theme

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
        .animation(.easeInOut(duration: 0.25), value: outcome)
    }

    private var showsRetry: Bool {
        switch outcome {
        case .unconfirmed, .unreachable: return true
        case .refused, .finished: return false
        }
    }

    private func button(_ label: LocalizedStringKey,
                        action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.paperTop)
        .background(theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

extension FocusOutcomeView.Outcome {
    /// Why the wording lives on the outcome and not inside the view: the
    /// finished page states the same thing as a banner beside the written page,
    /// which it must not replace. One outcome, one sentence, two presentations.
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
        case .finished(.user):
            return String(localized: "Sitzung beendet")
        case .finished(.hardCap):
            return String(localized: "Zeitgrenze erreicht")
        case .finished(.studyPreemption):
            return String(localized: "Eine Aufnahme hat die Uhr übernommen")
        case .finished(.watchFailure):
            return String(localized: "Die Uhr konnte nicht weiter messen")
        case .finished(.stopUnconfirmed):
            return String(localized: "Beendet, ohne Bestätigung")
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
        case .finished(.user), .finished(.hardCap):
            return String(localized: "Deine Schreibzeit ist gutgeschrieben.")
        case .finished(.studyPreemption):
            return String(localized: "Die Sitzung endete, weil eine Studien-Aufnahme die Sensoren braucht.")
        case .finished(.watchFailure):
            return String(localized: "Prüfe die Workout-Freigabe in den Health-Einstellungen.")
        case .finished(.stopUnconfirmed):
            return String(localized: "Die Uhr hat den Stopp nicht bestätigt. Der Sensorstrom läuft womöglich weiter.")
        }
    }
}

import SwiftUI

/// The focus tab on arrival: a ruled page, the creature that is being drawn,
/// and a sentence whose number can be tapped. No question, no form — the page
/// is ready to start.
struct FocusReadyView: View {
    /// Seconds, or `nil` for a session without a goal.
    let onStart: (Double?) -> Void

    @ObservedObject private var bestiary = BestiaryStore.shared
    @Environment(\.scrybe) private var theme
    @AppStorage(ScrybeSettings.focusDurationKey) private var storedMinutes =
        ScrybeSettings.defaultFocusMinutes
    @State private var goalless = false
    @State private var sheetPresented = false
    @ScaledMetric(relativeTo: .largeTitle) private var creatureSide: CGFloat = 140

    private var chosenMinutes: Int? { goalless ? nil : storedMinutes }
    private var chosenSeconds: Double? { chosenMinutes.map { Double($0) * 60 } }

    var body: some View {
        let creature = bestiary.creatureInProgress()
        let remaining = FocusProgress.remainingSeconds(writingSeconds: creature.writingSeconds)

        VStack(spacing: 20) {
            CreatureCanvas(speciesId: creature.speciesId,
                           strokesDrawn: creature.strokesDrawn)
                .frame(width: creatureSide, height: creatureSide)
                .accessibilityLabel(Text(creatureLabel(remaining: remaining)))

            VStack(spacing: 6) {
                Text(Marginalia.name(forSpecies: creature.speciesId))
                    .font(.system(.title3, design: .serif))
                    .italic()
                    .foregroundStyle(theme.ink)
                Text(progressSentence(remaining: remaining))
                    .font(.footnote)
                    .foregroundStyle(theme.secondaryInk)
                    .multilineTextAlignment(.center)
            }

            durationSentence

            Button { onStart(chosenSeconds) } label: {
                Text("Sitzung starten")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.paperTop)
            .background(theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(20)
        .sheet(isPresented: $sheetPresented) {
            FocusDurationSheet(minutes: Binding(
                get: { chosenMinutes },
                set: { newValue in
                    if let newValue { storedMinutes = newValue; goalless = false }
                    else { goalless = true }
                }), isPresented: $sheetPresented)
        }
    }

    private var durationSentence: some View {
        Button { sheetPresented = true } label: {
            if let minutes = chosenMinutes {
                Text("Eine Sitzung von ") + Text("\(minutes) Minuten").foregroundColor(theme.accent)
            } else {
                Text("Ohne Ziel — ") + Text("einfach schreiben").foregroundColor(theme.accent)
            }
        }
        .buttonStyle(.plain)
        .font(.system(.body, design: .serif))
        .foregroundStyle(theme.ink)
        .accessibilityLabel(Text(durationAccessibilityLabel))
        .accessibilityHint(Text("Ändert die Dauer."))
    }

    private var durationAccessibilityLabel: String {
        if let minutes = chosenMinutes {
            return String(localized: "Dauer: \(minutes) Minuten")
        }
        return String(localized: "Dauer: ohne Ziel")
    }

    private func progressSentence(remaining: Double) -> String {
        let minutes = Int((remaining / 60).rounded())
        if FocusProgress.exceedsCreature(remainingSeconds: remaining,
                                         sessionSeconds: chosenSeconds) {
            return String(localized: "Noch etwa \(minutes) Minuten, bis er fertig gezeichnet ist — und du beginnst ein neues.")
        }
        return String(localized: "Noch etwa \(minutes) Minuten, bis er fertig gezeichnet ist.")
    }

    private func creatureLabel(remaining: Double) -> String {
        let name = Marginalia.name(forSpecies: bestiary.creatureInProgress().speciesId)
        return "\(name), \(progressSentence(remaining: remaining))"
    }
}

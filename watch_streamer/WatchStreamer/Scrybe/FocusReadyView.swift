import SwiftUI

/// The focus tab on arrival: the creature being drawn, how far along it is,
/// the length of the next sitting, and the one button that starts it.
///
/// Sections are ruled apart, not boxed. The creature sits in a dotted circle
/// with its undrawn strokes traced faintly, so a reader sees both what the
/// writing has earned and what is still to come.
struct FocusReadyView: View {
    /// Seconds, or `nil` for a session without a goal.
    let onStart: (Double?) -> Void

    @ObservedObject private var bestiary = BestiaryStore.shared
    @Environment(\.scrybe) private var theme
    @AppStorage(ScrybeSettings.focusDurationKey) private var storedMinutes =
        ScrybeSettings.defaultFocusMinutes
    @State private var goalless = false
    @State private var sheetPresented = false
    @ScaledMetric(relativeTo: .largeTitle) private var creatureSide: CGFloat = 200

    private static let presets = [10, 25, 45]

    private var chosenMinutes: Int? { goalless ? nil : storedMinutes }
    private var chosenSeconds: Double? { chosenMinutes.map { Double($0) * 60 } }

    var body: some View {
        let creature = bestiary.creatureInProgress()
        let remaining = FocusProgress.remainingSeconds(writingSeconds: creature.writingSeconds)
        let fraction = min(1, creature.writingSeconds / Bestiary.secondsPerCreature)

        VStack(spacing: 28) {
            creatureSection(creature, remaining: remaining, fraction: fraction)
            ScrybeRule()
            durationSection
            ScrybePrimaryButton("Sitzung starten") { onStart(chosenSeconds) }
            bestiaryLink
        }
        .padding(.top, 8)
        .sheet(isPresented: $sheetPresented) {
            FocusDurationSheet(minutes: Binding(
                get: { chosenMinutes },
                set: { newValue in
                    if let newValue { storedMinutes = newValue; goalless = false }
                    else { goalless = true }
                }), isPresented: $sheetPresented)
        }
    }

    // MARK: - Creature

    private func creatureSection(_ creature: BestiaryEntry, remaining: Double,
                                 fraction: Double) -> some View {
        VStack(spacing: 24) {
            ZStack {
                Text("Im Entstehen").scrybeCaption(.caption)
                HStack {
                    Spacer()
                    Text("Strich für Strich …").scrybeMarginNote(.caption)
                }
            }

            ZStack {
                Circle()
                    .fill(RadialGradient(colors: [theme.wash(theme.sepia), .clear],
                                         center: .center, startRadius: 0,
                                         endRadius: creatureSide / 2))
                Circle()
                    .stroke(theme.sepia.opacity(0.45),
                            style: StrokeStyle(lineWidth: 1, dash: [1.5, 5]))
                CreatureCanvas(speciesId: creature.speciesId,
                               strokesDrawn: creature.strokesDrawn,
                               showsUnderdrawing: true)
                    .padding(creatureSide * 0.09)
            }
            .frame(width: creatureSide, height: creatureSide)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text(creatureLabel(creature, remaining: remaining)))

            VStack(spacing: 6) {
                Text(Marginalia.name(forSpecies: creature.speciesId))
                    .font(.system(.title, design: .serif))
                    .italic()
                    .foregroundStyle(theme.ink)
                    .multilineTextAlignment(.center)
                Text(CreatureLore.epithet(forSpecies: creature.speciesId))
                    .scrybeMarginNote(.subheadline)
            }

            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Fertig gezeichnet").scrybeCaption()
                    Spacer()
                    Text(fraction.formatted(.percent.precision(.fractionLength(0))
                        .locale(ScrybeSettings.localeOverride ?? .current)))
                        .font(.system(.title3, design: .serif))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                        .contentTransition(.numericText())
                }
                HatchedMeter(fraction: fraction)
                progressSentence(remaining: remaining)
            }
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder
    private func progressSentence(remaining: Double) -> some View {
        let minutes = Int((remaining / 60).rounded(.up))
        VStack(alignment: .leading, spacing: 4) {
            (Text("Noch ") + Text("\(minutes) Minuten").foregroundColor(theme.accent)
                + Text(" Schreibzeit."))
                .font(.system(.body, design: .serif))
                .foregroundStyle(theme.ink)
            if FocusProgress.exceedsCreature(remainingSeconds: remaining,
                                             sessionSeconds: chosenSeconds) {
                Text("Diese Sitzung vollendet die Kreatur. Danach beginnt eine neue.")
                    .scrybeMarginNote(.footnote)
            }
        }
    }

    // MARK: - Duration

    private var durationSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            ScrybeSectionHeader("Sitzungslänge") {
                if goalless {
                    Text("die Sitzung endet, wenn du sie beendest").scrybeMarginNote(.caption)
                }
            }
            HStack(spacing: 10) {
                ForEach(Self.presets, id: \.self) { preset in
                    DurationPill(minutes: preset, selected: chosenMinutes == preset) {
                        UISelectionFeedbackGenerator().selectionChanged()
                        storedMinutes = preset
                        goalless = false
                    }
                }
                customPill
            }
        }
    }

    /// The fourth pill: a chosen custom length or "no goal" while one is
    /// active, otherwise the way to the sheet that sets them.
    private var customPill: some View {
        let isCustom = goalless || !Self.presets.contains(storedMinutes)
        return DurationPill(minutes: goalless ? nil : (isCustom ? storedMinutes : nil),
                            selected: isCustom,
                            isMore: !isCustom) {
            sheetPresented = true
        }
    }

    // MARK: - Gallery

    private var bestiaryLink: some View {
        NavigationLink(value: BestiaryDestination()) {
            Text("Bestiarium ansehen · \(bestiary.completed.count) gesammelt")
                .scrybeCaption()
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func creatureLabel(_ creature: BestiaryEntry, remaining: Double) -> String {
        let name = Marginalia.name(forSpecies: creature.speciesId)
        let minutes = Int((remaining / 60).rounded(.up))
        return "\(name), " + String(localized: "Noch etwa \(minutes) Minuten, bis er fertig gezeichnet ist.")
    }
}

/// One session length: a serif figure with a small unit in a ruled capsule.
private struct DurationPill: View {
    /// Minutes, or `nil` for a session without a goal.
    let minutes: Int?
    let selected: Bool
    /// Renders the "…" pill that opens the custom-length sheet.
    var isMore = false
    let action: () -> Void

    @Environment(\.scrybe) private var theme

    var body: some View {
        Button(action: action) {
            Group {
                if isMore {
                    Image(systemName: "ellipsis")
                        .font(.body.weight(.semibold))
                } else if let minutes {
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text("\(minutes)")
                            .font(.system(.title3, design: .serif).weight(selected ? .semibold : .regular))
                        Text("min")
                            .font(.system(.caption, design: .serif))
                            .foregroundStyle(theme.secondaryInk)
                    }
                } else {
                    Image(systemName: "infinity")
                        .font(.body.weight(.semibold))
                }
            }
            .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background {
                Capsule().fill(selected ? theme.wash(theme.accent) : Color.clear)
            }
            .overlay {
                Capsule().stroke(selected ? theme.accent.opacity(0.6) : theme.sepia.opacity(0.4),
                                 lineWidth: 1)
            }
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private var label: LocalizedStringKey {
        if isMore { return "Eigene Dauer" }
        if let minutes { return "\(minutes) Minuten" }
        return "Ohne Ziel"
    }
}

#Preview {
    NavigationStack {
        ScrollView {
            FocusReadyView(onStart: { _ in })
                .padding(20)
        }
        .background(ScrybeTheme.standard.paper)
    }
    .scrybeTheme()
}

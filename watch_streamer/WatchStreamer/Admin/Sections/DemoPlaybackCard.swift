import SwiftUI

struct DemoPlaybackCard: View {
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme
    @State private var startingMinutes = 45.0
    @State private var secondsPerTick = 10.0

    var body: some View {
        AdminCard(title: "Produkt-Demo") {
            Text("Temporäre Beispieldaten für Screenshots und Video. Echte Schreibdaten bleiben unverändert.")
                .font(.caption)
                .foregroundStyle(theme.secondaryInk)

            if focus.demoModeEnabled {
                HStack(spacing: 8) {
                    Circle()
                        .fill(focus.demoIsWriting ? theme.success : theme.warning)
                        .frame(width: 10, height: 10)
                        .accessibilityHidden(true)
                    Text(focus.demoIsWriting ? "Schreiben erkannt" : "Kurze Pause")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(theme.ink)
                    Spacer()
                    Text(TimeFormatting.human(seconds: focus.todayWritingSeconds))
                        .font(.subheadline)
                        .monospacedDigit()
                        .foregroundStyle(theme.accent)
                        .contentTransition(.numericText())
                }
                .accessibilityElement(children: .combine)

                Button(role: .destructive) {
                    Task { await focus.stopDemo() }
                } label: {
                    Label("Demo beenden", systemImage: "stop.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            } else {
                LabeledContent("Startwert") {
                    HStack(spacing: 4) {
                        TextField("Minuten", value: $startingMinutes,
                                  format: .number.precision(.fractionLength(0)))
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 88)
                        Text("min")
                            .font(.caption)
                            .foregroundStyle(theme.secondaryInk)
                    }
                }

                Picker("Videotempo", selection: $secondsPerTick) {
                    Text("Echtzeit").tag(1.0)
                    Text("10×").tag(10.0)
                    Text("30×").tag(30.0)
                }
                .pickerStyle(.segmented)

                Button {
                    focus.startDemo(
                        startingSeconds: min(max(0, startingMinutes), 480) * 60,
                        secondsPerTick: secondsPerTick
                    )
                } label: {
                    Label("Demo starten", systemImage: "play.fill")
                        .font(.subheadline.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .foregroundStyle(theme.accent)
                        .scrybeSurface(cornerRadius: 12,
                                       tint: theme.accent.opacity(0.10),
                                       interactive: true)
                }
            }
        }
    }
}

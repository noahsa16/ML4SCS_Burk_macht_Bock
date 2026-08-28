import SwiftUI

/// P3: prüft, ob das auf der Watch geladene Core-ML-Modell dieselben Logits
/// wie PyTorch liefert. Auf der Watch gibt es kein Test-Bundle, deshalb geht
/// die Prüfung denselben Weg wie die Sensor-Probe: Command hin, Ergebnis
/// zurück, Anzeige hier.
struct ModelParityCard: View {
    @Environment(\.scrybe) private var theme
    @ObservedObject private var server = ServerCommandListener.shared

    var body: some View {
        AdminCard(title: "On-Device-Diagnose") {
            VStack(alignment: .leading, spacing: 12) {
                actionButton("Modell-Parität auf der Watch prüfen", systemImage: "checkmark.seal") {
                    server.runWatchParityCheck()
                }
                if let r = server.parityResult {
                    LabeledContent("P3", value: r)
                        .font(.caption)
                        .foregroundStyle(theme.ink.opacity(0.7))
                }
                if let raw = server.parityRaw {
                    Text(raw)
                        .font(.caption2)
                        .foregroundStyle(theme.ink.opacity(0.5))
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func actionButton(_ title: String, systemImage: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundStyle(theme.accent)
                .scrybeSurface(cornerRadius: 12, tint: theme.accent.opacity(0.10), interactive: true)
        }
    }
}

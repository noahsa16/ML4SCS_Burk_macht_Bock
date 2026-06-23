import SwiftUI

struct RepairCard: View {
    @Environment(\.scrybe) private var theme
    @State private var confirmClear = false

    var body: some View {
        AdminCard(title: "Reparatur") {
            Button { ServerCommandListener.shared.drainWatchSpill() } label: {
                Label("Gepufferte Daten senden", systemImage: "tray.and.arrow.up")
                    .font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .foregroundStyle(theme.accent)
                    .scrybeSurface(cornerRadius: 12, tint: theme.accent.opacity(0.10), interactive: true)
            }

            Button(role: .destructive) { confirmClear = true } label: {
                Label("Puffer verwerfen", systemImage: "trash")
                    .font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .foregroundStyle(theme.danger)
                    .scrybeSurface(cornerRadius: 12, tint: theme.danger.opacity(0.10), interactive: true)
            }
            .confirmationDialog("Puffer verwerfen?", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("Verwerfen", role: .destructive) { ServerCommandListener.shared.clearWatchSpill() }
                Button("Abbrechen", role: .cancel) {}
            } message: {
                Text("Gepufferte, noch nicht gesendete Watch-Daten werden gelöscht.")
            }
        }
    }
}

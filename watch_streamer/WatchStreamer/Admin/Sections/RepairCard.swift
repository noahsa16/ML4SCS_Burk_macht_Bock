import SwiftUI

struct RepairCard: View {
    @Environment(\.scrybe) private var theme
    @State private var confirmClear = false

    var body: some View {
        AdminCard(title: "Reparatur") {
            Button { ServerCommandListener.shared.drainWatchSpill() } label: {
                Label("Gepufferte Daten senden", systemImage: "tray.and.arrow.up")
                    .font(.subheadline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            }
            .foregroundStyle(theme.accent)

            Button(role: .destructive) { confirmClear = true } label: {
                Label("Puffer verwerfen", systemImage: "trash")
                    .font(.subheadline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            }
            .foregroundStyle(theme.danger)
            .confirmationDialog("Puffer verwerfen?", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("Verwerfen", role: .destructive) { ServerCommandListener.shared.clearWatchSpill() }
                Button("Abbrechen", role: .cancel) {}
            } message: {
                Text("Gepufferte, noch nicht gesendete Watch-Daten werden gelöscht.")
            }
        }
    }
}

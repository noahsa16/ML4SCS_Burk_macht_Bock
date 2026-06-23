import SwiftUI

struct AdminPanelView: View {
    var onExit: () -> Void
    @Environment(\.scrybe) private var theme

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                header
                RecordingHealthCard()
                DataflowCard()
                ConnectionsCard()
                SessionCard()
                RepairCard()
                LogCard()
                SettingsCard()
            }
            .padding(16)
        }
        .background(theme.paper.ignoresSafeArea())
    }

    private var header: some View {
        HStack {
            Button(action: onExit) {
                Label("Scrybe", systemImage: "chevron.left")
                    .font(.subheadline.weight(.medium))
            }
            .foregroundStyle(theme.accent)
            Spacer()
            Text("Admin").font(.headline).foregroundStyle(theme.ink)
            Spacer()
            Color.clear.frame(width: 64, height: 1)   // balances the back button
                .accessibilityHidden(true)
        }
    }
}

struct AdminCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .tracking(1.5)
                .foregroundStyle(theme.sepia)
                .accessibilityAddTraits(.isHeader)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.cardFill))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(theme.hairline))
    }
}

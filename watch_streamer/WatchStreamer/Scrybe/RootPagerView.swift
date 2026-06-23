import SwiftUI

struct RootPagerView: View {
    @State private var selection = 0
    @State private var adminPresented = false
    @State private var adminUnlocked = false
    @Environment(\.scrybe) private var theme

    private let labels = ["Heute", "Trends", "Verlauf"]

    var body: some View {
        VStack(spacing: 12) {
            ScrybeHeader(label: labels[selection]) { adminPresented = true }
            TabView(selection: $selection) {
                TodayView().tag(0)
                TrendsView().tag(1)
                HistoryView().tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .interactive))
        }
        .background(theme.paper.ignoresSafeArea())
        .fullScreenCover(isPresented: $adminPresented, onDismiss: { adminUnlocked = false }) {
            if adminUnlocked {
                AdminPanelView(onExit: { adminPresented = false }).scrybeTheme()
            } else {
                AdminGateView(onUnlock: { adminUnlocked = true }).scrybeTheme()
            }
        }
        .onAppear { FocusStore.shared.start() }
        .onDisappear { FocusStore.shared.stop() }
    }
}

private struct ScrybeHeader: View {
    let label: String
    var onAdmin: () -> Void
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 4) {
            Text("Scrybe")
                .font(.system(.title, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
                .onLongPressGesture(minimumDuration: 2.0) { onAdmin() }
            Rectangle().fill(theme.hairline).frame(width: 40, height: 1)
            Text(label.uppercased())
                .font(.caption.weight(.medium))
                .tracking(1.5)
                .foregroundStyle(theme.sepia)
        }
        .padding(.top, 8)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
        .accessibilityHint("Lang drücken öffnet den Admin-Bereich")
    }
}

#Preview {
    RootPagerView().scrybeTheme()
}

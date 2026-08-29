import SwiftUI

struct RootPagerView: View {
    private enum Tab: String {
        case today = "Heute"
        case trends = "Trends"
        case history = "Verlauf"
        case profile = "Profil"
    }

    @State private var selection: Tab = .today
    @State private var showSplash = true
    @AppStorage(ScrybeSettings.onboardingDoneKey) private var onboardingDone = false
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 12) {
            ScrybeHeader(label: selection.rawValue)
            TabView(selection: $selection) {
                TodayView()
                    .tabItem { Label("Heute", systemImage: "circle.dashed") }
                    .tag(Tab.today)
                TrendsView()
                    .tabItem { Label("Trends", systemImage: "chart.bar.fill") }
                    .tag(Tab.trends)
                HistoryView()
                    .tabItem { Label("Verlauf", systemImage: "list.bullet") }
                    .tag(Tab.history)
                ProfileView()
                    .tabItem { Label("Profil", systemImage: "person.fill") }
                    .tag(Tab.profile)
            }
        }
        .background(theme.paper.ignoresSafeArea())
        .onAppear { FocusStore.shared.start() }
        .onDisappear { FocusStore.shared.stop() }
        .fullScreenCover(isPresented: .constant(!onboardingDone)) {
            ScrybeThemeProvider {
                OnboardingFlowView(onFinish: { onboardingDone = true })
            }
        }
        .overlay {
            if showSplash {
                ScrybeSplashView()
                    .transition(.opacity)
                    .zIndex(1)
                    .onAppear(perform: dismissSplash)
            }
        }
    }

    private func dismissSplash() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.45)) {
                showSplash = false
            }
        }
    }
}

#Preview {
    RootPagerView().scrybeTheme()
}

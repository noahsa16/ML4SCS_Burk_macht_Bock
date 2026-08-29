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
    /// Why view-owned rather than `.constant(!onboardingDone)`: a constant
    /// binding cannot be written, so dismissal depended on the modifier being
    /// reconstructed. That is brittle under state restoration and leaves
    /// SwiftUI without a way to drive the dismissal itself.
    @State private var showOnboarding = false
    @AppStorage(ScrybeSettings.onboardingDoneKey) private var onboardingDone = false
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var splashTask: Task<Void, Never>?

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
        .onAppear {
            FocusStore.shared.start()
            showOnboarding = !onboardingDone
        }
        .onDisappear {
            FocusStore.shared.stop()
            splashTask?.cancel()
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            ScrybeThemeProvider {
                OnboardingFlowView(onFinish: {
                    onboardingDone = true
                    showOnboarding = false
                })
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
        // Why a cancellable task: an asyncAfter closure could land after the
        // view was gone and apply a stale animation state.
        splashTask?.cancel()
        splashTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.45)) {
                showSplash = false
            }
        }
    }
}

#Preview {
    RootPagerView().scrybeTheme()
}

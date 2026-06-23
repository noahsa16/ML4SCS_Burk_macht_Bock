import SwiftUI

struct RootPagerView: View {
    @State private var selection = 0
    @State private var showSplash = true
    @AppStorage(ScrybeSettings.onboardingDoneKey) private var onboardingDone = false
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let labels = ["Heute", "Trends", "Verlauf", "Profil"]

    var body: some View {
        VStack(spacing: 12) {
            ScrybeHeader(label: labels[selection])
            TabView(selection: $selection) {
                TodayView()
                    .tabItem { Label("Heute", systemImage: "circle.dashed") }
                    .tag(0)
                TrendsView()
                    .tabItem { Label("Trends", systemImage: "chart.bar.fill") }
                    .tag(1)
                HistoryView()
                    .tabItem { Label("Verlauf", systemImage: "list.bullet") }
                    .tag(2)
                ProfileView()
                    .tabItem { Label("Profil", systemImage: "person.fill") }
                    .tag(3)
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

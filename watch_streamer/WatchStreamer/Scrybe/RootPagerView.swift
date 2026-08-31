import SwiftUI
import UIKit

struct RootPagerView: View {
    enum Tab: String {
        case today = "Heute"
        case trends = "Trends"
        case focus = "Fokus"
        case profile = "Profil"
    }

    @ObservedObject private var session = FocusSessionStore.shared
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
            // Why the condition: the header is a sibling of the TabView, so
            // hiding the tab bar alone would leave it standing over a page
            // meant to be alone with the writer.
            if !session.isActive {
                ScrybeHeader(label: selection.rawValue)
            }
            TabView(selection: $selection) {
                TodayView(selection: $selection)
                    .tabItem { Label { Text("Heute") } icon: { ScrybeGlyph.today.image } }
                    .tag(Tab.today)
                TrendsView()
                    .tabItem { Label { Text("Trends") } icon: { ScrybeGlyph.trends.image } }
                    .tag(Tab.trends)
                FocusTabView()
                    .tabItem { Label { Text("Fokus") } icon: { ScrybeGlyph.focus.image } }
                    .tag(Tab.focus)
                ProfileView()
                    .tabItem { Label { Text("Profil") } icon: { ScrybeGlyph.profile.image } }
                    .tag(Tab.profile)
            }
        }
        .background(theme.paper.ignoresSafeArea())
        .onAppear {
            applyTabBarAppearance()
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

    /// Why UIKit here: SwiftUI has no API for the tab bar's background on
    /// iOS 16, and the container stays stock on purpose — this changes how it
    /// looks, never how it behaves.
    private func applyTabBarAppearance() {
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(theme.paperTop)
        appearance.shadowColor = UIColor(theme.track)
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
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

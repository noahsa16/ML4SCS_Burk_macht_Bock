import SwiftUI
import UIKit

struct RootPagerView: View {
    enum Tab: String {
        case today = "Heute"
        case trends = "Trends"
        case focus = "Fokus"
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
    #if DEBUG
    @State private var debugProfilePresented = false
    #endif

    var body: some View {
        // Why no shared header here: a sibling above the TabView stood still
        // while the page scrolled under it, and read as a bar with a seam.
        // Each page carries its own `ScrybeHeader` inside its scroll content.
        // Why three tabs: the profile is settings and a collection, not a
        // place a writer returns to daily. It opens from the header's
        // profile circle instead, and the strip keeps the three pages that
        // are about writing.
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
        }
        .background(theme.paper.ignoresSafeArea())
        .onReceive(FocusSessionStore.shared.$demoSpeed) { speed in
            if speed != nil { selection = .focus }
        }
        .onAppear {
            applyTabBarAppearance()
            FocusStore.shared.start()
            showOnboarding = !onboardingDone
            #if DEBUG
            if let tab = DebugFixture.initialTab { selection = tab }
            debugProfilePresented = DebugFixture.opensProfile
            Task { await DebugFixture.seedIfRequested() }
            if let speed = DebugFixture.demoSessionSpeed {
                FocusSessionStore.shared.startDemo(speed: speed)
            }
            #endif
        }
        #if DEBUG
        .sheet(isPresented: $debugProfilePresented) {
            ScrybeThemeProvider { ProfileView(onClose: { debugProfilePresented = false }) }
        }
        #endif
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

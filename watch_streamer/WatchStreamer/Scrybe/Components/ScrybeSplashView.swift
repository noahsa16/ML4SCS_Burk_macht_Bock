import SwiftUI

/// Brand launch splash shown over the app on cold start, fading into the paper UI.
/// Mirrors the app icon: cream wordmark on the deep-navy ground. The native
/// LaunchScreen.storyboard paints the same navy underneath so there is no flash
/// before this view renders.
struct ScrybeSplashView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var appeared = false

    private let navyTop = Color(hex: 0x23264F)
    private let navyBottom = Color(hex: 0x0E102A)
    private let cream = Color(hex: 0xF6EFE0)

    var body: some View {
        ZStack {
            LinearGradient(colors: [navyTop, navyBottom], startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()

            Text("scrybe")
                .font(.custom("AvenirNext-Heavy", size: 56, relativeTo: .largeTitle))
                .tracking(2)
                .foregroundStyle(cream)
                .opacity(appeared ? 1 : 0)
                .scaleEffect(appeared ? 1 : 0.94)
        }
        .onAppear {
            guard !reduceMotion else { appeared = true; return }
            withAnimation(.easeOut(duration: 0.5)) { appeared = true }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Scrybe")
    }
}

#Preview {
    ScrybeSplashView()
}

import SwiftUI

/// First-run flow shown until `onboardingDone`: welcome → watch explainer →
/// goal → optional reminders. The only real iOS permission requested is
/// notifications; motion is captured on the Watch, so there is no phone prompt.
struct OnboardingFlowView: View {
    var onFinish: () -> Void

    @Environment(\.scrybe) private var theme
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @State private var page = 0
    @State private var wantsReminder = false

    private let lastPage = 3

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $page) {
                welcome.tag(0)
                watchPage.tag(1)
                goalPage.tag(2)
                reminderPage.tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            primaryButton
                .padding(.horizontal, 24)
                .padding(.bottom, 32)
        }
        .background(theme.paper.ignoresSafeArea())
    }

    private var primaryButton: some View {
        Button {
            if page < lastPage { withAnimation { page += 1 } } else { finish() }
        } label: {
            Text(page < lastPage ? "Weiter" : "Los geht's")
                .font(.headline)
                .foregroundStyle(theme.paperTop)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(theme.accent, in: RoundedRectangle(cornerRadius: 14))
        }
    }

    private func finish() {
        guard wantsReminder else { onFinish(); return }
        Task {
            if await NotificationScheduler.requestAuthorization() {
                NotificationScheduler.schedule(minutes: ScrybeSettings.defaultReminderMinutes)
                UserDefaults.standard.set(true, forKey: ScrybeSettings.reminderEnabledKey)
            }
            onFinish()
        }
    }

    private var welcome: some View {
        page(content: {
            Text("scrybe")
                .font(.system(size: 52, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
            Text("Schreibzeit, automatisch erkannt — allein über die Watch.")
                .font(.title3)
                .foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center)
        })
    }

    private var watchPage: some View {
        page(icon: "applewatch", title: "Automatische Erkennung",
             body: "Trag deine Apple Watch und schreib wie gewohnt. Scrybe erkennt das Schreiben an der Handbewegung — kein Knopfdruck nötig.")
    }

    private var goalPage: some View {
        page(content: {
            Image(systemName: "target")
                .font(.system(size: 44)).foregroundStyle(theme.accent)
            Text("Dein Tagesziel")
                .font(.system(.title2, design: .serif)).foregroundStyle(theme.ink)
            HStack(spacing: 16) {
                Text(TimeFormatting.human(seconds: goalSeconds))
                    .font(.system(.title, design: .serif))
                    .foregroundStyle(theme.accent)
                    .contentTransition(.numericText())
                Stepper("",
                        value: Binding(get: { (goalSeconds / 60).rounded() },
                                       set: { goalSeconds = $0 * 60 }),
                        in: 5...480, step: 5)
                    .labelsHidden()
                    .accessibilityLabel("Tagesziel in Minuten")
            }
        })
    }

    private var reminderPage: some View {
        page(content: {
            Image(systemName: "bell")
                .font(.system(size: 44)).foregroundStyle(theme.accent)
            Text("Erinnerung")
                .font(.system(.title2, design: .serif)).foregroundStyle(theme.ink)
            Text("Ein täglicher Anstoß, falls dein Ziel noch offen ist.")
                .font(.subheadline).foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center)
            Toggle("Tägliche Erinnerung", isOn: $wantsReminder)
                .tint(theme.accent)
                .padding(.horizontal, 40)
        })
    }

    private func page(icon: String, title: String, body: String) -> some View {
        page {
            Image(systemName: icon)
                .font(.system(size: 44)).foregroundStyle(theme.accent)
            Text(title)
                .font(.system(.title2, design: .serif)).foregroundStyle(theme.ink)
            Text(body)
                .font(.subheadline).foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center)
        }
    }

    private func page<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 20) {
            Spacer()
            content()
            Spacer()
            Spacer()
        }
        .padding(.horizontal, 32)
        .frame(maxWidth: .infinity)
    }
}

#Preview {
    OnboardingFlowView(onFinish: {}).scrybeTheme()
}

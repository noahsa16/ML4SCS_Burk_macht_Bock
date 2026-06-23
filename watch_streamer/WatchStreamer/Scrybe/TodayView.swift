import SwiftUI

struct TodayView: View {
    @ObservedObject private var focus = FocusStore.shared
    @ObservedObject private var server = ServerCommandListener.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var liveSeconds: Double {
        max(focus.todayWritingSecondsPolled, server.liveInference?.todayWritingSeconds ?? 0)
    }
    private var progress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: liveSeconds, goalSeconds: goalSeconds)
    }
    private var isWriting: Bool { server.liveInference?.writing ?? false }
    private var isEmpty: Bool {
        liveSeconds == 0 && focus.streak == 0 && (focus.week?.maxSeconds ?? 0) == 0
    }
    private var ringSubtitle: String {
        "\(progress.percent) % · Ziel \(TimeFormatting.human(seconds: goalSeconds))"
    }
    private var streakText: String { "\(focus.streak) Tage" }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                if focus.isOffline {
                    OfflineBanner(lastUpdated: focus.lastUpdated)
                }
                if isEmpty {
                    OnboardingView().padding(.top, 40)
                } else {
                    hero
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .background { theme.paper.ignoresSafeArea() }
    }

    @ViewBuilder private var hero: some View {
        InkRing(
            fraction: progress.fraction,
            centerText: TimeFormatting.clock(seconds: liveSeconds),
            subtitle: ringSubtitle
        )
        .frame(width: 240, height: 240)
        .padding(.top, 8)

        HStack(spacing: 12) {
            Label(streakText, systemImage: "flame")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(theme.sepia)
            LiveChip(isWriting: isWriting)
        }

        if let week = focus.week {
            WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                .padding(.horizontal)
        }
    }
}

#Preview {
    TodayView().scrybeTheme()
}

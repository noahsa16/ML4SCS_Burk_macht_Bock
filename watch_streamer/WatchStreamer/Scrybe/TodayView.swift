import SwiftUI

struct TodayView: View {
    @ObservedObject private var focus = FocusStore.shared
    @ObservedObject private var server = ServerCommandListener.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var pulse = false
    @State private var celebrated = false
    @State private var celebrating = false
    @State private var shineOn = false

    private var liveSeconds: Double {
        max(focus.todayWritingSecondsPolled, server.liveInference?.todayWritingSeconds ?? 0)
    }
    private var progress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: liveSeconds, goalSeconds: goalSeconds)
    }
    private var isWriting: Bool { server.liveInference?.writing ?? false }
    private var goalMet: Bool { progress.isMet }
    private var isEmpty: Bool {
        liveSeconds == 0 && focus.streak == 0 && (focus.week?.maxSeconds ?? 0) == 0
    }
    private var ringSubtitle: String {
        "\(progress.percent) % · Ziel \(TimeFormatting.human(seconds: goalSeconds))"
    }
    private var sessionsToday: Int { focus.today?.stretches.count ?? 0 }
    private var longestToday: Double { focus.today?.stretches.map(\.durationS).max() ?? 0 }

    var body: some View {
        Group {
            if isEmpty { emptyState } else { content }
        }
        .background { theme.paper.ignoresSafeArea() }
        .onChange(of: isWriting) { _ in updatePulse() }
        .onChange(of: goalMet) { met in handleGoal(met) }
        .onAppear { updatePulse(); celebrated = goalMet }
        .goalReachedFeedback(trigger: celebrated)
    }

    // Empty: the bare ring carries the screen — no card, no illustration block.
    private var emptyState: some View {
        VStack(spacing: 20) {
            Spacer()
            InkRing(fraction: 0)
                .frame(width: 240, height: 240)
            Text("Trag die Watch und fang an zu schreiben")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }

    private var content: some View {
        ScrollView {
            VStack(spacing: 24) {
                if focus.isOffline {
                    OfflineBanner(lastUpdated: focus.lastUpdated)
                }
                ring
                LiveChip(isWriting: isWriting)
                StatTriple(sessions: sessionsToday,
                           longestSeconds: longestToday,
                           streak: focus.streak)
                if let week = focus.week {
                    WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                        .padding(.horizontal)
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
    }

    private var ring: some View {
        InkRing(
            fraction: progress.fraction,
            centerText: TimeFormatting.clock(seconds: liveSeconds),
            subtitle: ringSubtitle,
            tint: goalMet ? theme.goalReached : nil
        )
        .frame(width: 240, height: 240)
        .scaleEffect(pulse ? 1.03 : 1.0)
        .overlay {
            if celebrating {
                Circle()
                    .stroke(theme.goalReached, lineWidth: 8)
                    .scaleEffect(shineOn ? 1.18 : 0.96)
                    .opacity(shineOn ? 0 : 0.6)
            }
        }
        .padding(.top, 8)
    }

    private func updatePulse() {
        if isWriting && !reduceMotion {
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                pulse = true
            }
        } else {
            withAnimation(.easeInOut(duration: 0.2)) { pulse = false }
        }
    }

    // One-time goal-met moment: success haptic + a single outward shine. Resets
    // when the goal is no longer met (new day / raised goal) so it can fire again.
    private func handleGoal(_ met: Bool) {
        guard met else { celebrated = false; return }
        guard !celebrated else { return }
        celebrated = true
        guard !reduceMotion else { return }
        celebrating = true
        shineOn = false
        withAnimation(.easeOut(duration: 0.7)) { shineOn = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { celebrating = false }
    }
}

private extension View {
    // `.sensoryFeedback` is iOS 17+; the app deploys to iOS 16, so gate it and
    // let older devices skip the haptic (the goal-met shine still plays).
    @ViewBuilder
    func goalReachedFeedback(trigger celebrated: Bool) -> some View {
        if #available(iOS 17.0, *) {
            sensoryFeedback(trigger: celebrated) { old, new in
                (new && !old) ? .success : nil
            }
        } else {
            self
        }
    }
}

#Preview {
    TodayView().scrybeTheme()
}

import SwiftUI

struct TodayView: View {
    @ObservedObject private var focus = FocusStore.shared
    @ObservedObject private var session = FocusSessionStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var pulse = false
    @State private var celebrated = false
    @State private var celebrating = false
    @State private var shineOn = false
    @State private var celebrationTask: Task<Void, Never>?
    @State private var focusPresented = false

    private var liveSeconds: Double { focus.todayWritingSeconds }
    private var progress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: liveSeconds, goalSeconds: goalSeconds)
    }
    /// Whether the ring should still breathe. Shares `FocusStore`'s definition
    /// with the header glyph so the two cannot contradict each other.
    private var isWriting: Bool { focus.isRecentlyWriting() }
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
        // Why one scroll container for both states: connection and live
        // detection state used to exist only in the populated branch, so a new
        // user — or a product-video run — could not tell whether detection was
        // live, disconnected or stale at exactly the moment setup feedback
        // matters most. The empty state pulls to refresh too.
        InkRefreshScroll(action: { await focus.refreshForPull() },
                         lastWritingAt: focus.lastWritingAt) {
            VStack(spacing: 24) {
                if isEmpty { emptyState } else { populated }
                focusSessionEntry
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .background { theme.paper.ignoresSafeArea() }
        .fullScreenCover(isPresented: $focusPresented) {
            ScrybeThemeProvider {
                FocusSessionView(onClose: { focusPresented = false })
            }
        }
        .onChange(of: isWriting) { _ in updatePulse() }
        .onChange(of: goalMet) { met in handleGoal(met) }
        .onAppear { updatePulse(); celebrated = goalMet }
        .onDisappear { celebrationTask?.cancel() }
        .goalReachedFeedback(trigger: celebrated)
    }

    // Empty: the bare ring carries the screen — no card, no illustration block.
    private var emptyState: some View {
        VStack(spacing: 20) {
            ring
            Text("Trag die Watch und fang an zu schreiben")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity)
    }

    private var populated: some View {
        VStack(spacing: 24) {
            ring
            StatTriple(sessions: sessionsToday,
                       longestSeconds: longestToday,
                       streak: focus.streak)
            if let week = focus.week {
                WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                    .padding(.horizontal)
            }
        }
    }

    /// Opens the focus session, and reports one that is already running.
    ///
    /// The session outlives its own screen — closing that screen leaves the
    /// Watch streaming — so this row is where a running one is found again.
    private var focusSessionEntry: some View {
        Button { focusPresented = true } label: {
            HStack(spacing: 12) {
                Image(systemName: "pencil.line")
                    .font(.title3)
                    .foregroundStyle(theme.accent)
                VStack(alignment: .leading, spacing: 2) {
                    if session.isActive {
                        Text("Sitzung läuft").font(.headline)
                    } else {
                        Text("Fokus-Sitzung").font(.headline)
                    }
                    Text("Die Uhr misst, die Seite füllt sich.")
                        .font(.caption)
                        .foregroundStyle(theme.secondaryInk)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.footnote)
                    .foregroundStyle(theme.mutedInk)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.ink)
        .scrybeSurface(cornerRadius: 16)
    }

    private var ring: some View {
        // Why measured rather than a fixed 240: at accessibility text sizes,
        // in split view, in landscape or on a small phone, a fixed square
        // clipped or squeezed the content around it.
        GeometryReader { geo in
            let side = min(240, max(140, geo.size.width - 80))
            InkRing(
                fraction: isEmpty ? 0 : progress.fraction,
                centerText: isEmpty ? nil : TimeFormatting.clock(seconds: liveSeconds),
                subtitle: isEmpty ? nil : ringSubtitle,
                tint: goalMet ? theme.goalReached : nil
            )
            .frame(width: side, height: side)
            .scaleEffect(pulse ? 1.03 : 1.0)
            .overlay {
                if celebrating {
                    Circle()
                        .stroke(theme.goalReached, lineWidth: 8)
                        .scaleEffect(shineOn ? 1.18 : 0.96)
                        .opacity(shineOn ? 0 : 0.6)
                }
            }
            .frame(width: geo.size.width, height: side)
        }
        .frame(height: ringSide)
        .padding(.top, 8)
    }

    /// Mirrors the GeometryReader's clamp so the container reserves the right
    /// height; `ViewThatFits` cannot express a square capped by its own width.
    @ScaledMetric(relativeTo: .largeTitle) private var ringSide: CGFloat = 240

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
        // Why a cancellable task: an asyncAfter closure survives the view and
        // could clear `celebrating` for a later appearance that is mid-shine.
        celebrationTask?.cancel()
        celebrationTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 750_000_000)
            guard !Task.isCancelled else { return }
            celebrating = false
        }
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

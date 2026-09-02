import SwiftUI
import UIKit

struct TodayView: View {
    @Binding var selection: RootPagerView.Tab
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
    /// Non-nil only while a pull is either armed to harvest or actively
    /// sweeping in what it harvested; every other fraction change
    /// (background ingest outside a pull, session end, day rollover) falls
    /// back to `InkRing`'s own gentle default. Cleared on every path that
    /// leaves it non-nil — pull settle, disappear — so it never survives to
    /// sweep an unrelated later change.
    @State private var harvestSweep: Animation?
    @State private var harvestSweepResetTask: Task<Void, Never>?

    /// Days back from today the page is turned to. The page itself is the
    /// only thing that moves; the stores keep serving today.
    @State private var dayOffset = 0
    /// Which way the last turn went, so the new day slides in from the side
    /// it was reached from.
    @State private var turnedBack = true

    /// Fast attack, long settle — the reward reads as "arriving", not as a
    /// routine progress update.
    private static let harvestSweepDuration: TimeInterval = 1.4
    private static let harvestSweepCurve = Animation.timingCurve(
        0.2, 0.9, 0.3, 1.0, duration: harvestSweepDuration)

    private var liveSeconds: Double { focus.todayWritingSeconds }
    private var todayProgress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: liveSeconds, goalSeconds: goalSeconds)
    }
    /// Whether the ring should still breathe. Shares `FocusStore`'s definition
    /// with the header glyph so the two cannot contradict each other.
    private var isWriting: Bool { focus.isRecentlyWriting() && paging.isToday }
    private var goalMet: Bool { todayProgress.isMet }
    private var isEmpty: Bool {
        liveSeconds == 0 && focus.streak == 0 && (focus.week?.maxSeconds ?? 0) == 0
    }

    // MARK: - The shown day

    private var paging: DayPaging {
        DayPaging(offset: dayOffset, days: focus.history?.days ?? [])
    }
    private var shownSeconds: Double {
        paging.isToday ? liveSeconds : (paging.day?.writingSeconds ?? 0)
    }
    private var shownProgress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: shownSeconds, goalSeconds: goalSeconds)
    }
    private var shownStretches: [FocusStretchDTO] {
        if paging.isToday { return focus.today?.stretches ?? [] }
        guard let iso = paging.day?.date else { return [] }
        return focus.dayCache[iso]?.stretches ?? []
    }
    private var captionText: String {
        switch paging.caption {
        case .today: return String(localized: "Heute")
        case .yesterday: return String(localized: "Gestern")
        case .weekday(let name): return name
        case .date(let text): return text
        }
    }
    /// "16 % von 25 Min." — percent and goal both locale-formatted, so the
    /// English override gets "16% of 25 min" from the same line.
    private var ringSubtitle: String {
        let locale = ScrybeSettings.localeOverride ?? .current
        let percent = shownProgress.percent.formatted(.percent.locale(locale))
        return String(localized: "\(percent) von \(TimeFormatting.abbreviated(seconds: goalSeconds))")
    }
    /// Past days reload after every refresh: the store drops its day cache
    /// then, and the same ISO date must not keep showing stale stretches.
    private var dayLoadKey: String {
        "\(paging.day?.date ?? "")#\(focus.lastUpdated?.timeIntervalSince1970 ?? 0)"
    }

    var body: some View {
        // Why one scroll container for both states: connection and live
        // detection state used to exist only in the populated branch, so a new
        // user — or a product-video run — could not tell whether detection was
        // live, disconnected or stale at exactly the moment setup feedback
        // matters most. The empty state pulls to refresh too.
        InkRefreshScroll(action: {
            // Armed *before* the pull starts, not after it returns: the
            // watch batch can land — and `today` reassign, and the ring
            // re-render with a new `fraction` — while `refreshForPull` is
            // still parked in its delivery wait, well before it returns an
            // outcome. Arming late meant the sweep for the value change was
            // always in the past by the time it applied.
            armHarvestSweep()
            let outcome = await focus.refreshForPull()
            settleHarvestSweep(for: outcome)
            return outcome
        }, lastWritingAt: focus.lastWritingAt) {
            VStack(spacing: 24) {
                ScrybeHeader(label: captionText,
                             onPrevious: !isEmpty && paging.canGoBack ? { turn(by: 1) } : nil,
                             onNext: !isEmpty && paging.canGoForward ? { turn(by: -1) } : nil)
                if isEmpty { emptyState } else { populated }
                focusSessionEntry
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .background { theme.paper.ignoresSafeArea() }
        .simultaneousGesture(dayTurnGesture)
        .onChange(of: isWriting) { _ in updatePulse() }
        .onChange(of: goalMet) { met in handleGoal(met) }
        .onAppear { updatePulse(); celebrated = goalMet }
        .onDisappear {
            celebrationTask?.cancel()
            harvestSweepResetTask?.cancel()
            harvestSweep = nil
        }
        .task(id: dayLoadKey) {
            guard !paging.isToday, let iso = paging.day?.date else { return }
            await focus.loadDay(iso)
        }
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
            StatTriple(sessions: shownStretches.count,
                       longestSeconds: shownStretches.map(\.durationS).max() ?? 0,
                       streak: focus.streak)
            if !paging.window.isEmpty {
                WeekCard(days: paging.window, maxSeconds: paging.windowMax,
                         highlightedDate: paging.day?.date)
            }
        }
        // Why keyed by the offset: a turned page is a different page, and a
        // slide says so where a number morphing in place would not.
        .id(dayOffset)
        .transition(reduceMotion ? .opacity : .asymmetric(
            insertion: .move(edge: turnedBack ? .leading : .trailing).combined(with: .opacity),
            removal: .move(edge: turnedBack ? .trailing : .leading).combined(with: .opacity)))
    }

    // MARK: - Turning days

    /// A sideways swipe turns the page; the scroll view keeps every vertical
    /// drag, so the gesture only acts when it ended clearly horizontal.
    private var dayTurnGesture: some Gesture {
        DragGesture(minimumDistance: 24)
            .onEnded { value in
                let t = value.translation
                guard !isEmpty, abs(t.width) > 50, abs(t.width) > abs(t.height) * 1.5 else { return }
                turn(by: t.width > 0 ? 1 : -1)
            }
    }

    /// Earlier days lie to the left, like pages already written.
    private func turn(by delta: Int) {
        let target = dayOffset + delta
        guard target >= 0, target <= paging.maxOffset else { return }
        turnedBack = delta > 0
        UISelectionFeedbackGenerator().selectionChanged()
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.3)) {
            dayOffset = target
        }
    }

    /// Reports a running session and leads to it.
    ///
    /// The session outlives its own screen — leaving the tab keeps the Watch
    /// streaming — so this line is where a running one is found again. It says
    /// nothing while none is running: the focus tab is one tap away regardless.
    @ViewBuilder
    private var focusSessionEntry: some View {
        if session.isActive {
            Button { selection = .focus } label: {
                HStack(spacing: 12) {
                    Image(systemName: "pencil.line")
                        .font(.footnote)
                        .foregroundStyle(theme.accent)
                    Text("Fokus läuft — öffnen")
                        .font(.footnote)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption2)
                        .foregroundStyle(theme.mutedInk)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.secondaryInk)
            .scrybeSurface(cornerRadius: 12)
        }
    }

    private var ring: some View {
        // Why measured rather than a fixed 240: at accessibility text sizes,
        // in split view, in landscape or on a small phone, a fixed square
        // clipped or squeezed the content around it.
        GeometryReader { geo in
            let side = min(240, max(140, geo.size.width - 80))
            InkRing(
                fraction: isEmpty ? 0 : shownProgress.fraction,
                centerText: isEmpty ? nil : TimeFormatting.clock(seconds: shownSeconds),
                subtitle: isEmpty ? nil : ringSubtitle,
                tint: shownProgress.isMet ? theme.goalReached : nil,
                sweepAnimation: paging.isToday ? harvestSweep : nil
            )
            .frame(width: side, height: side)
            .scaleEffect(pulse ? 1.03 : 1.0)
            .overlay {
                if celebrating && paging.isToday {
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

    /// Arms the harvest curve speculatively, before the pull's outcome is
    /// known, so it is already in place for whatever fraction change the
    /// pull causes. Under Reduce Motion this stays `nil` — `InkRing` already
    /// falls back to no animation at all there, and the capsule's number is
    /// the reward, not a softened sweep in its place.
    private func armHarvestSweep() {
        harvestSweepResetTask?.cancel()
        harvestSweep = reduceMotion ? nil : Self.harvestSweepCurve
    }

    /// Resolves the speculative arm once the pull's outcome is known: a real
    /// harvest keeps the curve alive for the rest of its sweep, anything
    /// else (nothing new, offline) clears it immediately so a later,
    /// unrelated fraction change (a live session, a day rollover) is not
    /// swept with an event curve that was never really this pull's.
    private func settleHarvestSweep(for outcome: InkRefreshOutcome) {
        guard case .updated(_, let minutes) = outcome, let minutes, minutes > 0 else {
            harvestSweep = nil
            return
        }
        harvestSweepResetTask = Task { @MainActor in
            try? await Task.sleep(
                nanoseconds: UInt64(Self.harvestSweepDuration * 1_000_000_000))
            guard !Task.isCancelled else { return }
            harvestSweep = nil
        }
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
    TodayView(selection: .constant(.today)).scrybeTheme()
}

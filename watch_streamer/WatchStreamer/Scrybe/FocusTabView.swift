import SwiftUI
import UIKit

/// The focus area. Owns the tab's `NavigationStack` — `HistoryView` and
/// `BestiaryView` give theirs up, because a pushed stack inside a stack
/// produces two navigation bars and an unpredictable back gesture.
struct FocusTabView: View {
    @ObservedObject private var session = FocusSessionStore.shared
    @Environment(\.scrybe) private var theme

    /// The running session's clock. Scaled: it is the largest thing on the
    /// screen and the one a reader at arm's length actually reads.
    @ScaledMetric(relativeTo: .largeTitle) private var sessionClockSize: CGFloat = 44

    @State private var startOutcome: FocusOutcomeView.Outcome?
    @State private var lastRequested: Double?
    @State private var lastSegmentKind: FocusSegmentKind?

    var body: some View {
        let segments = session.segments
        NavigationStack {
            ScrollView {
                content(segments: segments)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
            }
            .background { theme.paper.ignoresSafeArea() }
            .navigationDestination(for: BestiaryDestination.self) { _ in
                BestiaryView()
            }
        }
        .toolbar(session.isActive ? .hidden : .visible, for: .tabBar)
        .onChange(of: segments.last?.kind) { kind in
            if FocusPageTear.occurred(previousLastKind: lastSegmentKind, segments: segments) {
                UIImpactFeedbackGenerator(style: .soft).impactOccurred()
            }
            lastSegmentKind = kind
        }
    }

    @ViewBuilder
    private func content(segments: [FocusSegment]) -> some View {
        if let startOutcome {
            FocusOutcomeView(outcome: startOutcome,
                             onRetry: {
                                 self.startOutcome = nil
                                 start(seconds: lastRequested)
                             },
                             onDismiss: { self.startOutcome = nil })
                .padding(.top, 24)
        } else {
            switch session.phase {
            case .idle:
                FocusReadyView(onStart: start(seconds:))
            case .starting:
                starting
            case .running(let startedAt, let targetSeconds):
                // Why a TimelineView: the session clock and the pen tip both run
                // on wall-clock time, while the decisions behind them arrive every
                // 2.5 s. A per-second tick keeps the two honest about the lag.
                TimelineView(.periodic(from: startedAt, by: 1)) { context in
                    running(segments: segments, startedAt: startedAt,
                            targetSeconds: targetSeconds, now: context.date)
                }
            case .failed(let message):
                failure(message)
            case .finished(let entry):
                finished(segments: segments, entry: entry)
            }
        }
    }

    // MARK: - Starting

    private var starting: some View {
        VStack(spacing: 12) {
            ProgressView().tint(theme.accent)
            Text("Sitzung wird gestartet …")
                .font(.footnote)
                .foregroundStyle(theme.secondaryInk)
        }
        .padding(.top, 48)
        .frame(maxWidth: .infinity)
    }

    // MARK: - Running

    private func running(segments: [FocusSegment], startedAt: Date,
                         targetSeconds: Double?, now: Date) -> some View {
        VStack(spacing: 16) {
            VStack(spacing: 4) {
                Text(sessionClock(now.timeIntervalSince(startedAt)))
                    .font(.system(size: sessionClockSize, weight: .regular, design: .serif))
                    .monospacedDigit()
                    .foregroundStyle(theme.ink)
                // Why the start time when there is no goal: a goalless session
                // has no "of 25 min" to state, but when it began is still the
                // one fact the clock alone cannot give back.
                if let targetSeconds {
                    Text("von \(TimeFormatting.human(seconds: targetSeconds))")
                        .font(.footnote)
                        .foregroundStyle(theme.secondaryInk)
                } else {
                    Text("seit \(startedAt.formatted(date: .omitted, time: .shortened))")
                        .font(.footnote)
                        .foregroundStyle(theme.secondaryInk)
                }
            }
            .padding(.top, 16)
            .accessibilityElement(children: .combine)

            WritingPageView(segments: segments,
                            species: session.currentSpecies,
                            strokesDrawn: session.strokesDrawn,
                            headMs: Int64(now.timeIntervalSince1970 * 1000))
                .scrybeSurface(cornerRadius: 16)

            primaryButton("Beenden") { session.end() }
        }
    }

    /// mm:ss. `TimeFormatting.clock` is h:mm, which would spend a whole
    /// 25-minute session reading "0:24".
    private func sessionClock(_ seconds: Double) -> String {
        let total = Int(max(0, seconds))
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: - Finished

    private func finished(segments: [FocusSegment], entry: BestiaryEntry) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            // The head is parked on the last decision, so the page draws no
            // trace ahead of it: a finished session has nothing left to write.
            WritingPageView(segments: segments,
                            species: entry.speciesId,
                            strokesDrawn: entry.strokesDrawn,
                            headMs: segments.last?.endMs ?? 0)
                .scrybeSurface(cornerRadius: 16)

            if let signature {
                // Dates and times, not copy — `Text(String)` is the right init
                // here, and the catalog has nothing to add to it.
                Text(signature)
                    .font(.system(.caption, design: .serif))
                    .italic()
                    .foregroundStyle(theme.secondaryInk)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }

            Text("\(TimeFormatting.human(seconds: session.writingSeconds)) geschrieben")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)

            // Why a banner and not a screen of its own: the written page IS the
            // outcome of an ordinary ending, and an exceptional reason is a
            // remark about that page, not a replacement for it.
            if let reason = session.finishReason, reason != .user, reason != .hardCap {
                Label(FocusOutcomeView.Outcome.finished(reason).detail,
                      systemImage: "exclamationmark.triangle")
                    .font(.footnote)
                    .foregroundStyle(theme.warning)
            }

            primaryButton("Fertig") { session.returnToIdle() }
        }
        .padding(.top, 16)
        .animation(.easeInOut(duration: 0.25), value: session.finishReason)
    }

    /// `29. August · 14:31–15:06` — what makes the page a document (Spec §6).
    private var signature: String? {
        guard let start = session.lastSessionStart,
              let end = session.lastSessionEnd else { return nil }
        let day = DateFormatting.dayMonth(ms: Int64(start.timeIntervalSince1970 * 1000))
        return "\(day) · \(start.formatted(date: .omitted, time: .shortened))"
            + "–\(end.formatted(date: .omitted, time: .shortened))"
    }

    // MARK: - Failed

    private func failure(_ message: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.title2)
                .foregroundStyle(theme.danger)
            // A refusal arrives already translated (`FocusStartRefusal.message`);
            // only the model loader's message is raw data, which is why this
            // is `Text(String)` rather than a catalog key.
            Text(message)
                .font(.subheadline)
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
            primaryButton("Zurück") { session.returnToIdle() }
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 16)
        .padding(.top, 24)
    }

    // MARK: - Shared pieces

    private func primaryButton(_ title: LocalizedStringKey,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.paperTop)
        .background(theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func start(seconds: Double?) {
        lastRequested = seconds
        session.markStarting()
        // Why an unstructured task: leaving this screen must not abandon a
        // start the Watch may already have accepted. The store owns the
        // session; this view only asks for it.
        Task {
            switch await ServerCommandListener.shared.startFocusSession() {
            case .started:
                session.begin(targetSeconds: seconds)
            case .refused(let refusal):
                startOutcome = .refused(refusal)
                session.returnToIdle()
            case .unconfirmed:
                startOutcome = .unconfirmed
                session.returnToIdle()
            case .unreachable:
                startOutcome = .unreachable
                session.returnToIdle()
            }
        }
    }
}

/// A push target with no payload; the gallery reads the shared store.
struct BestiaryDestination: Hashable {}

#Preview {
    FocusTabView().scrybeTheme()
}

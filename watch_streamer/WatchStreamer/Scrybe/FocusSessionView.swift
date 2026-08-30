import SwiftUI
import UIKit

/// When the page's line tears.
///
/// Only a `.lift` at the end of the page counts, and only with ink before it:
/// a `.resting` gap is the thinking pause the three-state line exists to draw
/// as continuous, and a session that opens with a pause tears nothing.
enum FocusPageTear {
    static func occurred(previousLastKind: FocusSegmentKind?,
                         segments: [FocusSegment]) -> Bool {
        guard previousLastKind != .lift,
              segments.count >= 2,
              segments.last?.kind == .lift else { return false }
        return segments[segments.count - 2].kind == .ink
    }
}

/// A deliberately started writing session: the Watch measures, the page fills.
///
/// The session lives in `FocusSessionStore`, not here. Closing this screen
/// leaves it running — which is why the entry point on `TodayView` says so and
/// why the hard cap is the store's task, not the view's.
struct FocusSessionView: View {
    let onClose: () -> Void

    @ObservedObject private var session = FocusSessionStore.shared
    @Environment(\.scrybe) private var theme

    @State private var targetMinutes = 25
    @State private var lastSegmentKind: FocusSegmentKind?

    private static let targetChoices = [15, 25, 45]

    var body: some View {
        let segments = session.segments
        return VStack(spacing: 0) {
            topBar
            ScrollView {
                content(segments: segments)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
            }
        }
        .background { theme.paper.ignoresSafeArea() }
        .onChange(of: segments.last?.kind) { kind in
            if FocusPageTear.occurred(previousLastKind: lastSegmentKind, segments: segments) {
                UIImpactFeedbackGenerator(style: .soft).impactOccurred()
            }
            lastSegmentKind = kind
        }
    }

    private var topBar: some View {
        HStack(spacing: 0) {
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(theme.secondaryInk)
                    .frame(width: 44, height: 44)
            }
            .accessibilityLabel(Text("Schließen"))
            Spacer()
            Text("Fokus-Sitzung")
                .font(.system(.headline, design: .serif))
                .foregroundStyle(theme.ink)
            Spacer()
            // Balances the close button so the title stays centred.
            Color.clear.frame(width: 44, height: 44)
        }
        .padding(.horizontal, 8)
    }

    @ViewBuilder
    private func content(segments: [FocusSegment]) -> some View {
        switch session.phase {
        case .idle:
            picker
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

    // MARK: - Idle

    private var picker: some View {
        VStack(spacing: 24) {
            VStack(spacing: 8) {
                Text("Wie lange willst du schreiben?")
                    .font(.system(.title3, design: .serif))
                    .foregroundStyle(theme.ink)
                    .multilineTextAlignment(.center)
                Text("Die Uhr misst, das iPhone zeichnet mit. Deine Schreibzeit zählt weiterhin der Tagestracker.")
                    .font(.footnote)
                    .foregroundStyle(theme.secondaryInk)
                    .multilineTextAlignment(.center)
            }
            HStack(spacing: 12) {
                ForEach(Self.targetChoices, id: \.self) { minutes in
                    targetChip(minutes)
                }
            }
            primaryButton("Sitzung starten", action: startSession)
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 16)
        .padding(.top, 24)
    }

    private func targetChip(_ minutes: Int) -> some View {
        let selected = minutes == targetMinutes
        return Button { targetMinutes = minutes } label: {
            Text("\(minutes) Min")
                .font(.system(.body, design: .serif))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
        .background(selected ? theme.wash(theme.accent) : theme.track,
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
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
                         targetSeconds: Double, now: Date) -> some View {
        VStack(spacing: 16) {
            VStack(spacing: 4) {
                Text(sessionClock(now.timeIntervalSince(startedAt)))
                    .font(.system(size: 44, weight: .regular, design: .serif))
                    .monospacedDigit()
                    .foregroundStyle(theme.ink)
                Text("von \(TimeFormatting.human(seconds: targetSeconds))")
                    .font(.footnote)
                    .foregroundStyle(theme.secondaryInk)
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

            if session.stopUnconfirmed {
                Label("Die Uhr hat den Stopp nicht bestätigt.", systemImage: "exclamationmark.triangle")
                    .font(.footnote)
                    .foregroundStyle(theme.warning)
            }

            primaryButton("Fertig") { session.returnToIdle() }
        }
        .padding(.top, 16)
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
            // The reason comes from the Watch's refusal or the model loader,
            // so it is shown as data rather than through the catalog.
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

    private func startSession() {
        session.markStarting()
        // Why an unstructured task: dismissing this screen must not abandon a
        // start the Watch may already have accepted. The store owns the
        // session; this view only asks for it.
        Task {
            switch await ServerCommandListener.shared.startFocusSession() {
            case .started:
                session.begin(targetSeconds: Double(targetMinutes) * 60)
            case .refused(let refusal):
                session.failToStart(Self.message(for: refusal))
            case .noAnswer:
                session.failToStart(String(localized: "Die Uhr hat nicht geantwortet. Prüfe, ob sie in Reichweite ist."))
            }
        }
    }

    /// A refusal in the user's language. The two cases ask opposite things —
    /// end the recording, or grant a permission — so they get their own copy
    /// rather than one message covering both.
    private static func message(for refusal: FocusStartRefusal) -> String {
        switch refusal {
        case .recordingInProgress:
            return String(localized: "Es läuft gerade eine Aufnahme. Beende sie zuerst.")
        case .workoutPermissionMissing:
            return String(localized: "Der Uhr fehlt die Workout-Freigabe. Erteile sie in den Health-Einstellungen.")
        }
    }
}

#Preview {
    FocusSessionView(onClose: {}).scrybeTheme()
}

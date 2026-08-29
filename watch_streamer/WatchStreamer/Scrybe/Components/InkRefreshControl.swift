import SwiftUI
import UIKit

/// Pull-to-refresh drawn as ink: the pull grows a stroke, the threshold closes
/// it into a ring, the sync sends a blot around it, and the result stays
/// readable for a moment instead of vanishing with the spinner.
///
/// Replaces `.refreshable` on Heute, Trends and Verlauf so all three share one
/// animation, one haptic and one wording for "synced" and "no connection".
struct InkRefreshScroll<Content: View>: View {
    /// Runs the refresh and reports what this pull achieved.
    let action: () async -> InkRefreshOutcome
    @ViewBuilder var content: Content

    @State private var model = InkRefreshModel()
    @State private var pull: CGFloat = 0
    @State private var gestureIsLive = false
    @State private var work: Task<Void, Never>?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static var space: String { "inkRefresh" }

    private var revealed: CGFloat {
        model.isActive
            ? InkRefreshModel.activeHeight
            : min(max(pull, 0), InkRefreshModel.activeHeight)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                // Why height 0 and outside the padding: the probe has to report
                // the true top of the content, and the padding below moves the
                // content down during a sync without moving the measurement.
                GeometryReader { geo in
                    Color.clear.preference(
                        key: InkPullKey.self,
                        value: geo.frame(in: .named(Self.space)).minY)
                }
                .frame(height: 0)

                content
                    .padding(.top, model.isActive ? InkRefreshModel.activeHeight : 0)
            }
        }
        .coordinateSpace(name: Self.space)
        .overlay(alignment: .top) { indicator }
        .onPreferenceChange(InkPullKey.self) { handlePull($0) }
        .simultaneousGesture(
            DragGesture(minimumDistance: 10)
                .onChanged { _ in gestureIsLive = true }
                .onEnded { _ in release() }
        )
        .animation(reduceMotion ? nil : .spring(response: 0.34, dampingFraction: 0.86),
                   value: model.isActive)
        // Why an explicit action: a pull gesture is unreachable with VoiceOver,
        // Switch Control and Voice Control, and the native `.refreshable` this
        // replaces exposed one. Without it the screens become unrefreshable for
        // exactly the people who cannot pull.
        .accessibilityAction(named: Text("Aktualisieren")) { triggerFromAssistiveTechnology() }
        .onDisappear { work?.cancel() }
    }

    /// Drawn into the strip the pull opens, clipped to it.
    ///
    /// Why the explicit clip: an overlay is not bounded by the scroll view, so
    /// an unclipped indicator paints over the header during a partial pull.
    private var indicator: some View {
        ZStack(alignment: .top) {
            Color.clear
            InkRefreshIndicator(model: model)
                .padding(.top, 12)
        }
        .frame(height: max(revealed, 0), alignment: .top)
        .clipped()
        .opacity(model.isActive ? 1 : Double(min(1, revealed / 28)))
        .allowsHitTesting(false)
    }

    private func handlePull(_ offset: CGFloat) {
        // Safety net for an OS that never delivers the simultaneous drag: an
        // armed pull that has sprung all the way back means the finger is gone,
        // and committing here beats leaving a control that never fires. The
        // latch keeps this dormant as soon as the gesture has proven itself.
        if !gestureIsLive, model.isArmed, offset <= 2 {
            release()
            return
        }
        pull = offset
        if model.pull(offset) { InkHaptics.armed() }
    }

    private func release() {
        guard model.release() else { return }
        run()
    }

    private func triggerFromAssistiveTechnology() {
        guard !model.isActive else { return }
        model.pull(InkRefreshModel.threshold)
        guard model.release() else { return }
        run()
    }

    private func run() {
        work?.cancel()
        work = Task { @MainActor in
            let outcome = await action()
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .easeOut(duration: 0.25)) {
                model.finish(outcome)
            }
            InkHaptics.settled(outcome)
            try? await Task.sleep(
                nanoseconds: UInt64(InkRefreshModel.settleSeconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .spring(response: 0.34, dampingFraction: 0.86)) {
                model.dismiss()
            }
        }
    }
}

private struct InkPullKey: PreferenceKey {
    static var defaultValue: CGFloat { 0 }
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

// MARK: - Indicator

struct InkRefreshIndicator: View {
    let model: InkRefreshModel

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var spin: Double = 0

    private static let diameter: CGFloat = 26
    private static let line: CGFloat = 2.2

    var body: some View {
        VStack(spacing: 7) {
            glyph.frame(width: Self.diameter, height: Self.diameter)
            caption
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Abgleich"))
        .accessibilityValue(captionText)
    }

    @ViewBuilder private var glyph: some View {
        switch model.phase {
        case .settled(.updated):
            ZStack {
                ring(theme.success, progress: 1)
                Image(systemName: "checkmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(theme.success)
            }
            .transition(.scale(scale: 0.7).combined(with: .opacity))

        case .settled(.offline):
            // Why a broken ring rather than an error icon: the sync failed, the
            // stored data did not, and a torn stroke says "interrupted" where a
            // warning triangle says "something is wrong with your data".
            Circle()
                .stroke(theme.warning,
                        style: StrokeStyle(lineWidth: Self.line, lineCap: .round,
                                           dash: [3, 5]))
                .transition(.opacity)

        case .refreshing:
            ZStack {
                ring(theme.accent.opacity(0.22), progress: 1)
                Circle()
                    .fill(theme.accent)
                    .frame(width: 7, height: 7)
                    .offset(y: -(Self.diameter - Self.line) / 2)
                    .rotationEffect(.degrees(spin))
            }
            .onAppear { startSpin() }

        default:
            // A round cap at zero progress reads as a single ink dot, which is
            // what the stroke grows out of.
            ring(theme.accent, progress: max(0.001, model.ringProgress))
                .scaleEffect(reduceMotion ? 1 : 0.62 + 0.38 * model.ringProgress)
        }
    }

    private func ring(_ color: Color, progress: Double) -> some View {
        Circle()
            .trim(from: 0, to: progress)
            .stroke(color, style: StrokeStyle(lineWidth: Self.line, lineCap: .round))
            .rotationEffect(.degrees(-90))
    }

    private var caption: some View {
        Text(captionText)
            .font(.caption2)
            .foregroundStyle(captionColor)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .padding(.horizontal, 12)
    }

    private var captionColor: Color {
        switch model.status {
        case .updated: return theme.successInk
        case .offline: return theme.warning
        default: return theme.secondaryInk
        }
    }

    private var captionText: String {
        switch model.status {
        case .hint: return String(localized: "Zum Aktualisieren ziehen")
        case .release: return String(localized: "Loslassen zum Abgleichen")
        case .syncing: return String(localized: "Schreibzeit wird abgeglichen …")
        case .updated(let at):
            let time = at.formatted(date: .omitted, time: .shortened)
            return String(localized: "Alles aktuell · \(time)")
        case .offline:
            return String(localized: "Keine Verbindung · Daten bleiben erhalten")
        }
    }

    private func startSpin() {
        guard !reduceMotion else { return }
        spin = 0
        withAnimation(.linear(duration: 0.95).repeatForever(autoreverses: false)) {
            spin = 360
        }
    }
}

// MARK: - Haptics

enum InkHaptics {
    /// Fired once when the stroke closes into a ring.
    static func armed() {
        UIImpactFeedbackGenerator(style: .soft).impactOccurred()
    }

    static func settled(_ outcome: InkRefreshOutcome) {
        let generator = UINotificationFeedbackGenerator()
        switch outcome {
        case .updated: generator.notificationOccurred(.success)
        case .offline: generator.notificationOccurred(.warning)
        }
    }
}

extension InkRefreshModel {
    /// Builds a model in a given phase. Preview- and test-facing only.
    static func staged(_ build: (inout InkRefreshModel) -> Void) -> InkRefreshModel {
        var model = InkRefreshModel()
        build(&model)
        return model
    }
}

#Preview("Phasen") {
    VStack(spacing: 20) {
        InkRefreshIndicator(model: .staged { $0.pull(InkRefreshModel.threshold * 0.45) })
        InkRefreshIndicator(model: .staged { $0.pull(InkRefreshModel.threshold) })
        InkRefreshIndicator(model: .staged {
            $0.pull(InkRefreshModel.threshold)
            _ = $0.release()
        })
        InkRefreshIndicator(model: .staged {
            $0.pull(InkRefreshModel.threshold)
            _ = $0.release()
            $0.finish(.updated(at: Date()))
        })
        InkRefreshIndicator(model: .staged {
            $0.pull(InkRefreshModel.threshold)
            _ = $0.release()
            $0.finish(.offline)
        })
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}

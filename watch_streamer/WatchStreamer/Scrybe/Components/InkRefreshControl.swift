import SwiftUI
import UIKit

/// A reliable system pull-to-refresh with a branded ink result.
///
/// iOS owns the drag gesture and its scroll arbitration. Once the system
/// spinner retracts, the ink result briefly confirms whether the Watch was
/// reached. The previous custom drag recognizer competed with `ScrollView` and
/// could fail to release on device even though its state machine tested green.
struct InkRefreshScroll<Content: View>: View {
    /// Runs the refresh and reports what this pull achieved.
    let action: () async -> InkRefreshOutcome
    /// Shown only in the transient completion capsule. This keeps the useful
    /// timestamp without permanently duplicating the Watch status below the
    /// daily ring.
    var lastWritingAt: Date? = nil
    @ViewBuilder var content: Content

    @State private var model = InkRefreshModel()
    @State private var dismissWork: Task<Void, Never>?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ScrollView {
            content
        }
        .refreshable { await refresh() }
        .overlay(alignment: .top) {
            if model.isActive {
                InkRefreshIndicator(model: model, lastWritingAt: lastWritingAt)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(.regularMaterial, in: Capsule(style: .continuous))
                    .shadow(color: .black.opacity(0.08), radius: 12, y: 5)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .allowsHitTesting(false)
            }
        }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: model.phase)
        .onDisappear { dismissWork?.cancel() }
    }

    private func refresh() async {
        dismissWork?.cancel()
        guard model.beginSystemRefresh() else { return }
        let outcome = await action()
        guard !Task.isCancelled else {
            // Why not a bare return: that would strand the model in
            // `.refreshing`, which no later pull can leave.
            model.abandon()
            return
        }
        model.finish(outcome)
        InkHaptics.settled(outcome)
        dismissWork = Task { @MainActor in
            try? await Task.sleep(
                nanoseconds: UInt64(InkRefreshModel.settleSeconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .spring(response: 0.34, dampingFraction: 0.86)) {
                model.dismiss()
            }
        }
    }
}

// MARK: - Indicator

struct InkRefreshIndicator: View {
    let model: InkRefreshModel
    var lastWritingAt: Date? = nil

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var spin: Double = 0

    private static let diameter: CGFloat = 20
    private static let line: CGFloat = 2.2

    var body: some View {
        HStack(spacing: 8) {
            glyph.frame(width: Self.diameter, height: Self.diameter)
            caption
        }
        .fixedSize(horizontal: true, vertical: false)
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
                    .font(.system(size: 9, weight: .bold))
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
                ring(theme.track, progress: 1)
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
            if let lastWritingAt {
                let time = lastWritingAt.formatted(date: .omitted, time: .shortened)
                return String(localized: "Zuletzt geschrieben \(time)")
            }
            let time = at.formatted(date: .omitted, time: .shortened)
            return String(localized: "Alles aktuell · \(time)")
        case .offline:
            return String(localized: "Keine Verbindung zur Uhr")
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

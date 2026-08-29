import SwiftUI
import WatchKit

private enum WatchScrybeStyle {
    static let goalKey = "scrybe.dailyGoalSeconds"
    static let defaultGoalSeconds: Double = 2 * 60 * 60

    // Mirrors the iPhone dark theme on the Watch's always-dark canvas.
    static let accent = Color(red: 0.55, green: 0.56, blue: 0.84)
    static let goalReached = Color(red: 0.88, green: 0.48, blue: 0.31)
}

struct WatchInkRing: View {
    let fraction: Double
    let writingSeconds: Double
    let goalSeconds: Double
    let tint: Color

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var progress: Double { max(0, min(1, fraction)) }
    private var progressPercent: Int { Int((progress * 100).rounded()) }

    var body: some View {
        ZStack {
            Circle()
                .stroke(.secondary.opacity(0.2), lineWidth: 8)

            Circle()
                .trim(from: 0, to: progress)
                .stroke(tint, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.5), value: progress)

            VStack(spacing: 4) {
                Text(Self.clock(writingSeconds))
                    .font(.system(.title2, design: .serif).weight(.semibold))
                    .monospacedDigit()
                    .contentTransition(.numericText())

                Text("heute")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Schreibzeit heute")
        .accessibilityValue(
            "\(Self.accessibleDuration(writingSeconds)), \(progressPercent) Prozent von \(Self.accessibleDuration(goalSeconds))"
        )
    }

    private static func clock(_ seconds: Double) -> String {
        let totalMinutes = max(0, Int(seconds) / 60)
        return "\(totalMinutes / 60):\(String(format: "%02d", totalMinutes % 60))"
    }

    private static func accessibleDuration(_ seconds: Double) -> String {
        let totalMinutes = max(0, Int(seconds) / 60)
        let hours = totalMinutes / 60
        let minutes = totalMinutes % 60
        if hours == 0 { return "\(minutes) Minuten" }
        if minutes == 0 { return "\(hours) Stunden" }
        return "\(hours) Stunden und \(minutes) Minuten"
    }
}

struct WatchView: View {
    @StateObject private var motion = MotionManager()
    @ObservedObject private var passive = PassiveTracker.shared
    @AppStorage(WatchScrybeStyle.goalKey) private var storedGoalSeconds = 0.0

    private var goalSeconds: Double {
        storedGoalSeconds > 0 ? storedGoalSeconds : WatchScrybeStyle.defaultGoalSeconds
    }

    private var progress: Double {
        guard goalSeconds > 0 else { return 0 }
        return passive.writingSecondsToday / goalSeconds
    }

    private var goalMet: Bool { progress >= 1 }

    var body: some View {
        NavigationStack {
            ViewThatFits(in: .vertical) {
                mainContent
                ScrollView { mainContent }
            }
            .tint(WatchScrybeStyle.accent)
        }
    }

    private var mainContent: some View {
        VStack(spacing: 8) {
            ring
            statusControl
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 12)
        .padding(.bottom, 4)
    }

    private var ring: some View {
        GeometryReader { proxy in
            let side = min(112, max(96, proxy.size.width - 40))
            WatchInkRing(
                fraction: progress,
                writingSeconds: passive.writingSecondsToday,
                goalSeconds: goalSeconds,
                tint: goalMet ? WatchScrybeStyle.goalReached : WatchScrybeStyle.accent
            )
            .frame(width: side, height: side)
            .frame(maxWidth: .infinity)
        }
        .frame(height: 112)
    }

    @ViewBuilder
    private var statusControl: some View {
        if motion.isRunning || passive.isCycling {
            trackingStatusRow
        } else if passive.isEnabled {
            NavigationLink {
                WatchTrackingOptionsView(passive: passive)
            } label: {
                trackingStatusRow
            }
            .buttonStyle(.plain)
        } else {
            Button {
                WKInterfaceDevice.current().play(.start)
                passive.enable()
            } label: {
                trackingStatusRow
            }
            .buttonStyle(.plain)
        }
    }

    private var trackingStatusRow: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle()
                    .stroke(.secondary.opacity(0.5), lineWidth: 1)
                if statusDotIsOn {
                    Circle().fill(statusDotColor)
                }
            }
            .frame(width: 8, height: 8)
            .accessibilityHidden(true)

            Text(statusText)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)

            if !motion.isRunning && !passive.isCycling {
                Image(systemName: passive.isEnabled ? "chevron.right" : "plus")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var statusText: String {
        if motion.isRunning { return "Aufnahme läuft" }
        if passive.isCycling { return "Wird aktualisiert" }
        if case .failed = passive.state { return "Tracking prüfen" }
        if passive.isEnabled { return "Tracking aktiv" }
        return "Tracking ist aus"
    }

    private var statusDotIsOn: Bool {
        motion.isRunning || passive.isCycling || passive.isEnabled
    }

    private var statusDotColor: Color {
        if case .failed = passive.state { return .orange }
        if motion.isRunning { return .green }
        return WatchScrybeStyle.accent
    }
}

private struct WatchTrackingOptionsView: View {
    @ObservedObject var passive: PassiveTracker

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                if passive.isCycling {
                    ProgressView("Wird aktualisiert")
                } else {
                    Button("Jetzt aktualisieren") {
                        WKInterfaceDevice.current().play(.click)
                        Task { await passive.runCycle() }
                    }
                }

                Button("Tracking deaktivieren", role: .destructive) {
                    WKInterfaceDevice.current().play(.stop)
                    passive.disable()
                }

                Label("Noch nicht auf echter Watch validiert", systemImage: "exclamationmark.triangle")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .accessibilityElement(children: .combine)
            }
            .padding(.horizontal, 8)
        }
        .navigationTitle("Tracking")
    }
}

#Preview("Tracking") {
    WatchView()
}

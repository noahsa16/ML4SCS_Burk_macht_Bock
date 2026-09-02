import SwiftUI
import WatchKit

private enum WatchScrybeStyle {
    static let goalKey = ScrybeGoal.defaultsKey
    static let defaultGoalSeconds = ScrybeGoal.defaultSeconds

    // Mirrors the iPhone dark theme on the Watch's always-dark canvas.
    static let accent = Color(red: 0.55, green: 0.56, blue: 0.84)
    static let goalReached = Color(red: 0.88, green: 0.48, blue: 0.31)
}

/// The creature in progress, drawn stroke by stroke as on the phone's focus
/// page. Same density-matched pen as `CreatureCanvas`, minus the theme: the
/// Watch canvas is always dark, so the ink is the ring's own palette.
struct WatchCreatureGlyph: View {
    let creature: WatchCreatureSnapshot
    let ink: Color

    var body: some View {
        Canvas { context, size in
            let strokes = Marginalia.strokes(forSpecies: creature.speciesId)
            guard !strokes.isEmpty else { return }
            let side = min(size.width, size.height)
            context.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
            context.scaleBy(x: side / 100, y: side / 100)
            let base = max(0.9, 2.6 - CGFloat(strokes.count) * 0.03)
            let lineWidth = base * (side < 100 ? 1.6 : 1)
            for path in strokes.prefix(creature.strokesDrawn) {
                context.stroke(path, with: .color(ink), lineWidth: lineWidth)
            }
        }
        .accessibilityHidden(true)
    }
}

struct WatchInkRing: View {
    let fraction: Double
    let writingSeconds: Double
    let goalSeconds: Double
    let tint: Color
    /// Shown inside the ring when the phone has a creature with at least one
    /// earned stroke; an entry with credited time but nothing visible would
    /// read as broken, not as "in progress".
    var creature: WatchCreatureSnapshot?

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

            VStack(spacing: 2) {
                if let creature, creature.strokesDrawn > 0 {
                    WatchCreatureGlyph(creature: creature, ink: .secondary)
                        .frame(width: 34, height: 34)
                }

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
        .accessibilityValue(accessibilityValueText)
    }

    private var accessibilityValueText: String {
        var text = "\(Self.accessibleDuration(writingSeconds)), \(progressPercent) Prozent von \(Self.accessibleDuration(goalSeconds))"
        if let creature, creature.strokesDrawn > 0 {
            text += ", Kreatur zu \(Int((creature.fraction * 100).rounded())) Prozent gezeichnet"
        }
        return text
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
    @ObservedObject private var creature = WatchCreatureStore.shared
    @AppStorage(WatchScrybeStyle.goalKey) private var storedGoalSeconds = 0.0

    private var goalSeconds: Double {
        storedGoalSeconds > 0 ? storedGoalSeconds : WatchScrybeStyle.defaultGoalSeconds
    }

    private var progress: Double {
        guard goalSeconds > 0 else { return 0 }
        return passive.writingSecondsToday / goalSeconds
    }

    private var goalMet: Bool { progress >= 1 }

    /// Height the bottom status row occupies: its 44 pt tap target plus the
    /// breathing room the ring must keep clear of it.
    private static let statusRowHeight: CGFloat = 56

    var body: some View {
        NavigationStack {
            GeometryReader { proxy in
                // Why the status row is subtracted: it is pinned to the bottom,
                // so centring the ring in the *full* height pushed it down into
                // the row on shorter watches. The ring owns the centre of the
                // space that is actually free.
                let free = max(0, proxy.size.height - Self.statusRowHeight)
                let side = max(88, min(104, proxy.size.width - 40, free - 16))

                ZStack {
                    WatchInkRing(
                        fraction: progress,
                        writingSeconds: passive.writingSecondsToday,
                        goalSeconds: goalSeconds,
                        tint: goalMet
                            ? WatchScrybeStyle.goalReached
                            : WatchScrybeStyle.accent,
                        creature: creature.current
                    )
                    .frame(width: side, height: side)
                    .position(x: proxy.size.width / 2, y: free / 2)

                    VStack {
                        Spacer()
                        statusControl
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 12)
                }
            }
            .tint(WatchScrybeStyle.accent)
        }
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
                .lineLimit(1)
                .minimumScaleFactor(0.75)

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

                phaseList

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

    /// What the last cycle actually found.
    ///
    /// Why on the watch and not only on the phone: a cycle that reports a bare
    /// daily total cannot distinguish "found nothing just now" from "found
    /// something two hours ago", which is exactly what one needs to know while
    /// testing detection on the wrist.
    @ViewBuilder
    private var phaseList: some View {
        let recent = passive.todayPhases.suffix(5).reversed()
        VStack(alignment: .leading, spacing: 4) {
            Text("Erkannt heute")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            if recent.isEmpty {
                Text("Noch keine Schreibphase")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else {
                ForEach(Array(recent), id: \.startMs) { phase in
                    HStack {
                        Text(Self.clock(phase.startMs))
                            .font(.caption2.monospacedDigit())
                        Spacer(minLength: 8)
                        Text("\(Int(phase.seconds.rounded())) s")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private static func clock(_ ms: Int64) -> String {
        Date(timeIntervalSince1970: Double(ms) / 1000)
            .formatted(date: .omitted, time: .shortened)
    }
}

#Preview("Tracking") {
    WatchView()
}

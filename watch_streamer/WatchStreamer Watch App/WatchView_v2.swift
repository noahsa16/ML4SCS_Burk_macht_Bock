// WatchView_v2.swift
// FocusTrack — Apple Watch UI
// Streaming via iPhone bridge (WatchConnectivity) only.
//
// Requirements: watchOS 9+, Swift 5.9+

import SwiftUI
import WatchKit
import Combine
import Foundation

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Design tokens (watchOS is always dark)
// ─────────────────────────────────────────────────────────────────────────────

private enum WT {
    static let green  = Color(red: 0.188, green: 0.820, blue: 0.345) // #30D158
    static let red    = Color(red: 1.000, green: 0.271, blue: 0.227) // #FF453A
    static let orange = Color(red: 1.000, green: 0.624, blue: 0.039) // #FF9F0A
    static let yellow = Color(red: 1.000, green: 0.839, blue: 0.039) // #FFD60A
    static let blue   = Color(red: 0.039, green: 0.518, blue: 1.000) // #0A84FF
    static let accent = orange                                        // orange as accent

    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Animated pulsing dot
// ─────────────────────────────────────────────────────────────────────────────

struct WTPulseDot: View {
    let color: Color
    var pulse: Bool = true

    var body: some View {
        Circle().fill(color).frame(width: 5, height: 5)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Connection pill
// ─────────────────────────────────────────────────────────────────────────────

struct WTConnPill: View {
    let label: String
    let ok: Bool

    var body: some View {
        HStack(spacing: 4) {
            WTPulseDot(color: ok ? WT.green : WT.orange, pulse: ok)
            Text(label)
                .font(WT.sans(10, weight: .medium))
                .foregroundColor(.secondary)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Stats row
// ─────────────────────────────────────────────────────────────────────────────

struct WTStatsRow: View {
    let label: String
    let value: String
    var color:  Color = .primary

    var body: some View {
        HStack {
            Text(label)
                .font(WT.sans(11))
                .foregroundColor(.secondary)
            Spacer()
            Text(value)
                .font(WT.mono(12, weight: .semibold))
                .foregroundColor(color)
                .monospacedDigit()
        }
        .padding(.vertical, 2)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.white.opacity(0.08))
                .frame(height: 0.5)
        }
    }
}

struct WTWatchNetworkMap: View {
    @ObservedObject var motion: MotionManager

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                node("Watch", ok: true, icon: "applewatch")
                link(ok: motion.isReachable, label: "poll")
                node("Phone", ok: motion.isReachable, icon: "iphone")
            }
            info("Command poll", motion.lastCommandPollStatus,
                 color: motion.isReachable ? WT.green : WT.orange)
            info("Command ID", motion.lastCommandId ?? "none",
                 color: motion.lastCommandId == nil ? Color.white.opacity(0.45) : WT.green)
            info("Upload", motion.uploadMode,
                 color: motion.uploadMode.hasPrefix("Bridge") ? WT.green : WT.orange)
            info("Recovery", motion.isReachable ? "automatic" : "open iPhone app",
                 color: motion.isReachable ? WT.green : WT.orange)
        }
    }

    private func node(_ title: String, ok: Bool, icon: String) -> some View {
        VStack(spacing: 3) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(ok ? WT.green : WT.orange)
                .frame(width: 28, height: 28)
                .background((ok ? WT.green : WT.orange).opacity(0.14))
                .clipShape(Circle())
            Text(title)
                .font(WT.sans(9, weight: .semibold))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private func link(ok: Bool, label: String) -> some View {
        VStack(spacing: 3) {
            Capsule()
                .fill(ok ? WT.green.opacity(0.6) : Color.white.opacity(0.16))
                .frame(width: 42, height: 3)
            Text(label)
                .font(WT.mono(8))
                .foregroundColor(ok ? WT.green : .secondary)
        }
    }

    private func info(_ label: String, _ value: String, color: Color) -> some View {
        HStack {
            Text(label)
                .font(WT.sans(9))
                .foregroundColor(.secondary)
            Spacer()
            Text(value)
                .font(WT.mono(9, weight: .medium))
                .foregroundColor(color)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – IMU mini sparkline (Canvas)
// ─────────────────────────────────────────────────────────────────────────────

struct WTSparkline: View {
    let samples: [Double]

    var body: some View {
        Canvas { ctx, size in
            guard samples.count > 1 else { return }
            let W = size.width, H = size.height
            var path = Path()
            for (i, v) in samples.enumerated() {
                let x = CGFloat(i) / CGFloat(samples.count - 1) * W
                let y = H/2 - CGFloat(v / 1.0) * (H/2 - 2)
                if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                else       { path.addLine(to: CGPoint(x: x, y: y)) }
            }
            ctx.stroke(path, with: .color(WT.accent), lineWidth: 1.5)
        }
        .frame(height: 32)
        .background(Color.white.opacity(0.04))
        .cornerRadius(6)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – PAGE 1: Record
// ─────────────────────────────────────────────────────────────────────────────

struct WTRecordPage: View {
    @ObservedObject var motion: MotionManager
    @State private var elapsed = 0
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    // ── Derived state ────────────────────────────────────────────────
    private var isRecording: Bool { motion.isRunning }
    private var isReady: Bool     { !motion.isRunning && motion.isReachable }

    private var stateColor: Color {
        if isRecording { return WT.green }
        if isReady     { return WT.blue  }
        return WT.orange
    }
    private var stateIcon: String {
        if isRecording { return "waveform" }
        if isReady     { return "checkmark.circle" }
        return "exclamationmark.circle"
    }
    private var stateLabel: String {
        if isRecording { return "REC" }
        if isReady     { return "READY" }
        return "WAITING"
    }
    private var contextLine: String {
        if let sid = motion.serverSessionId { return sid }
        if isReady   { return "start from website" }
        return "open iPhone app"
    }
    private var pollLabel: String {
        guard motion.isReachable else { return "no poll" }
        return motion.lastCommandPollStatus == "Phone replied" ? "live" : "polling…"
    }

    var body: some View {
        VStack(spacing: 0) {

            // ── State indicator ──────────────────────────────────────────
            ZStack {
                Circle()
                    .fill(stateColor.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: stateIcon)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(stateColor)
            }
            .frame(height: 54)
            .onChange(of: motion.isRunning) { running in
                if !running { elapsed = 0 }
            }

            // ── State label + timer ──────────────────────────────────────
            HStack(spacing: 5) {
                Text(stateLabel)
                    .font(WT.mono(11, weight: .bold))
                    .foregroundColor(stateColor)
                    .kerning(0.6)
                if isRecording {
                    Text(String(format: "%02d:%02d", elapsed / 60, elapsed % 60))
                        .font(WT.mono(11))
                        .foregroundColor(.secondary)
                        .monospacedDigit()
                }
            }
            .padding(.top, 2)

            // ── Context line ─────────────────────────────────────────────
            Text(contextLine)
                .font(WT.sans(9))
                .foregroundColor(motion.serverSessionId != nil ? WT.accent : .secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .padding(.top, 1)

            Spacer(minLength: 4)

            // ── Connection status bar ────────────────────────────────────
            HStack(spacing: 0) {
                connCell(
                    icon:  "iphone",
                    label: motion.isReachable ? "reachable" : "offline",
                    ok:    motion.isReachable
                )
                Rectangle().fill(Color.white.opacity(0.14)).frame(width: 0.5)
                connCell(
                    icon:  "arrow.2.circlepath",
                    label: pollLabel,
                    ok:    motion.isReachable
                )
                if let id = motion.lastCommandId, !id.isEmpty {
                    Rectangle().fill(Color.white.opacity(0.14)).frame(width: 0.5)
                    connCell(
                        icon:  "terminal",
                        label: String(id.prefix(8)),
                        ok:    true
                    )
                }
            }
            .background(Color.white.opacity(0.07))
            .cornerRadius(8)
            .padding(.bottom, 6)

            // ── Start / Stop button ──────────────────────────────────────
            Button {
                WKInterfaceDevice.current().play(motion.isRunning ? .stop : .start)
                if motion.isRunning { motion.stop() }
                else                { motion.start() }
            } label: {
                Label(motion.isRunning ? "Stop" : "Start",
                      systemImage: motion.isRunning ? "stop.fill" : "record.circle")
                    .font(WT.sans(13, weight: .bold))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(motion.isRunning ? WT.red : (isReady ? WT.green : WT.orange))
            .padding(.bottom, 2)
        }
        .padding(.horizontal, 10)
        // Timer: berechne elapsed aus runStartedAt statt zu inkrementieren —
        // korrekt auch nach Watch-Sleep.
        .onReceive(timer) { now in
            guard motion.isRunning, let start = motion.runStartedAt else { return }
            elapsed = Int(now.timeIntervalSince(start))
        }
    }

    @ViewBuilder
    private func connCell(icon: String, label: String, ok: Bool) -> some View {
        HStack(spacing: 3) {
            WTPulseDot(color: ok ? WT.green : WT.orange, pulse: ok)
            VStack(alignment: .leading, spacing: 0) {
                Image(systemName: icon)
                    .font(.system(size: 7, weight: .semibold))
                    .foregroundColor(.secondary)
                Text(label)
                    .font(WT.mono(8))
                    .foregroundColor(ok ? WT.green : WT.orange)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 5)
        .padding(.horizontal, 3)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – PAGE 2: Stats
// ─────────────────────────────────────────────────────────────────────────────

struct WTStatsPage: View {
    @ObservedObject var motion: MotionManager

    private var isActive: Bool { motion.isRunning }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("Stats")
                    .font(WT.sans(11, weight: .bold))
                    .foregroundColor(.secondary)
                    .textCase(.uppercase)
                    .kerning(0.8)
                    .padding(.bottom, 6)

                WTStatsRow(
                    label: "Rate",
                    value: isActive ? String(format: "%.1f Hz", motion.actualSampleRateHz) : "—",
                    color: isActive ? WT.green : .secondary
                )
                WTStatsRow(
                    label: "Delivered",
                    value: motion.deliveredSampleCount.formatted()
                )
                WTStatsRow(
                    label: "Queued",
                    value: (motion.queuedSampleCount + motion.backgroundQueuedSampleCount).formatted(),
                    color: (motion.queuedSampleCount + motion.backgroundQueuedSampleCount) > 0 ? WT.orange : .primary
                )

                if motion.droppedSampleCount > 0 {
                    WTStatsRow(label: "Dropped", value: motion.droppedSampleCount.formatted(), color: WT.orange)
                }
                if motion.failedBatchCount > 0 {
                    WTStatsRow(label: "Failed",  value: motion.failedBatchCount.formatted(),   color: WT.red)
                }

                Divider().padding(.vertical, 5)

                WTStatsRow(
                    label: "|acc|",
                    value: isActive ? String(format: "%.2f", motion.lastAccelerationMagnitude) : "—",
                    color: .secondary
                )
                WTStatsRow(
                    label: "|gyro|",
                    value: isActive ? String(format: "%.2f", motion.lastGyroscopeMagnitude) : "—",
                    color: .secondary
                )

                // Mini sparkline — only when active
                // NOTE: In production, feed real acc samples from MotionManager
                // For now shows a placeholder when running
                if isActive {
                    WTSparkline(samples: generateSparkSamples())
                        .padding(.top, 8)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
        }
    }

    private func generateSparkSamples() -> [Double] {
        return (0..<40).map { i in
            let d = Double(i)
            return sin(d * 0.35) * 0.5 + sin(d * 0.8) * 0.25
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – PAGE 3: Settings
// ─────────────────────────────────────────────────────────────────────────────

struct WTSettingsPage: View {
    @ObservedObject var motion: MotionManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                WTWatchNetworkMap(motion: motion)
                    .padding(.bottom, 4)
                infoRow("Transport",   "Phone Bridge",
                        color: WT.blue)
                infoRow("Status",      motion.uploadMode,
                        color: motion.uploadMode.hasPrefix("Bridge") ? WT.green : WT.orange)
                infoRow("BG Session",  motion.workoutStatus,
                        color: motion.workoutStatus.contains("active") ? WT.green : .secondary)
                infoRow("Phone",       motion.isReachable ? "Reachable" : "Offline",
                        color: motion.isReachable ? WT.green : WT.orange)
            }
            .padding(.horizontal, 12)
            .padding(.top, 2)
        }
    }

    @ViewBuilder
    private func infoRow(_ label: String, _ value: String, color: Color = .primary) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(WT.sans(9, weight: .medium))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .kerning(0.5)
            Text(value)
                .font(WT.mono(11))
                .foregroundColor(color)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Root WatchView
// ─────────────────────────────────────────────────────────────────────────────

struct WatchView: View {
    @StateObject private var motion = MotionManager()

    var body: some View {
        TabView {
            // Page 1 — Record (primary)
            WTRecordPage(motion: motion)
                .tag(0)

            // Page 2 — Stats
            WTStatsPage(motion: motion)
                .tag(1)

            // Page 3 — Settings
            WTSettingsPage(motion: motion)
                .tag(2)
        }
        .tabViewStyle(.page)
        .indexViewStyle(.page)
        // Orange accent for interactive elements
        .tint(WT.accent)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Preview
// ─────────────────────────────────────────────────────────────────────────────

#Preview("Record") {
    WTRecordPage(motion: MotionManager())
}

#Preview("Stats") {
    WTStatsPage(motion: MotionManager())
}

#Preview("Settings") {
    WTSettingsPage(motion: MotionManager())
}

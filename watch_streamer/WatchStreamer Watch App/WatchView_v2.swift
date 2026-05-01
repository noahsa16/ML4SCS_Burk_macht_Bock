// WatchView_v2.swift
// FocusTrack — Apple Watch UI (redesigned)
// Matches the web dashboard design language adapted for watchOS:
// dark background, monospace data, orange accent, compact card rows.
//
// Integration:
//   1. Add this file to the WatchKit Extension target in Xcode
//   2. Delete (or rename) old WatchView.swift
//   3. MotionManager.swift + StreamMode enum — NO changes needed
//      StreamMode.allCases must include rawValues: "Auto", "iPhone", "Direct HTTP"
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
    @State private var dim = false

    var body: some View {
        Circle().fill(color).frame(width: 5, height: 5)
            .opacity(pulse && dim ? 0.2 : 1)
            .onAppear {
                guard pulse else { return }
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    dim = true
                }
            }
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
    @State private var ripple = false
    @State private var elapsed = 0
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var accentColor: Color { motion.isRunning ? WT.green : .secondary }

    var body: some View {
        VStack(spacing: 0) {

            // ── Ripple + Icon ─────────────────────────────────────────────
            ZStack {
                // Ripple rings
                if motion.isRunning {
                    ForEach([0, 1], id: \.self) { i in
                        Circle()
                            .stroke(WT.green.opacity(0.3), lineWidth: 1.5)
                            .frame(width: 68, height: 68)
                            .scaleEffect(ripple ? 1.7 : 1.0)
                            .opacity(ripple ? 0 : 0.8)
                            .animation(
                                .easeOut(duration: 1.6)
                                    .repeatForever(autoreverses: false)
                                    .delay(Double(i) * 0.6),
                                value: ripple
                            )
                    }
                }
                // Fill circle
                Circle()
                    .fill(motion.isRunning ? WT.green.opacity(0.18) : Color.white.opacity(0.06))
                    .frame(width: 54, height: 54)
                // Icon
                Image(systemName: motion.isRunning ? "waveform" : "waveform.slash")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundColor(accentColor)
            }
            .frame(height: 72)
            .onChange(of: motion.isRunning) { running in
                ripple = running
            }
            .onAppear { ripple = motion.isRunning }

            // ── Status ────────────────────────────────────────────────────
            Text(motion.isRunning ? "Recording" : motion.status)
                .font(WT.sans(14, weight: .semibold))
                .foregroundColor(motion.isRunning ? WT.green : .primary)
                .lineLimit(1).minimumScaleFactor(0.8)

            // Session ID
            if let sid = motion.serverSessionId {
                Text(sid)
                    .font(WT.mono(9, weight: .medium))
                    .foregroundColor(WT.accent)
                    .lineLimit(1)
                    .padding(.top, 1)
            }

            // Duration
            if motion.isRunning {
                Text(String(format: "%02d:%02d", elapsed / 60, elapsed % 60))
                    .font(WT.mono(12))
                    .foregroundColor(.secondary)
                    .padding(.top, 2)
            }

            Spacer()

            // ── Connection pills ──────────────────────────────────────────
            HStack(spacing: 14) {
                WTConnPill(label: "Phone",  ok: motion.isReachable)
                WTConnPill(label: "Server", ok: motion.serverReachable)
            }
            .padding(.bottom, 8)

            // ── Start / Stop button ───────────────────────────────────────
            Button {
                WKInterfaceDevice.current().play(motion.isRunning ? .stop : .start)
                if motion.isRunning { motion.stop(); elapsed = 0 }
                else                { motion.start() }
            } label: {
                Label(
                    motion.isRunning ? "Stop"  : "Start",
                    systemImage: motion.isRunning ? "stop.fill" : "record.circle"
                )
                .font(WT.sans(14, weight: .bold))
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(motion.isRunning ? WT.red : WT.green)
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 4)
        .onReceive(timer) { _ in if motion.isRunning { elapsed += 1 } }
        .onAppear { motion.refreshServerStatus() }
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

                // ── Stream mode picker ────────────────────────────────────
                VStack(alignment: .leading, spacing: 4) {
                    Text("Stream via")
                        .font(WT.sans(11, weight: .bold))
                        .foregroundColor(.secondary)
                        .textCase(.uppercase)
                        .kerning(0.6)

                    Picker("", selection: $motion.preferredMode) {
                        ForEach(StreamMode.allCases, id: \.self) { mode in
                            Text(mode.rawValue).tag(mode)
                        }
                    }
                    .pickerStyle(.wheel)
                    .frame(height: 64)
                    .tint(WT.accent)
                }

                Divider()

                // ── Status info ───────────────────────────────────────────
                infoRow("Active mode",  motion.uploadMode,
                        color: motion.uploadMode == "Direct" ? WT.green : WT.orange)
                infoRow("BG Session",   motion.workoutStatus,
                        color: motion.workoutStatus.contains("active") ? WT.green : .secondary)
                infoRow("Phone",        motion.isReachable ? "Reachable" : "Offline",
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

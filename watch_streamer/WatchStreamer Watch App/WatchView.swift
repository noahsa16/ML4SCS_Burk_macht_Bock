import SwiftUI
import WatchKit

struct WatchView: View {
    @StateObject private var motion = MotionManager()
    @State private var pulse = false

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {

                // ── Recording indicator ────────────────────────────────────
                ZStack {
                    Circle()
                        .fill(motion.isRunning ? Color.green.opacity(0.2) : Color.gray.opacity(0.1))
                        .frame(width: 56, height: 56)
                        .scaleEffect(pulse ? 1.15 : 1.0)
                        .animation(
                            motion.isRunning
                                ? .easeInOut(duration: 0.9).repeatForever(autoreverses: true)
                                : .default,
                            value: pulse
                        )
                    Image(systemName: motion.isRunning ? "waveform" : "waveform.slash")
                        .font(.system(size: 22, weight: .medium))
                        .foregroundStyle(motion.isRunning ? .green : .secondary)
                }
                .padding(.top, 4)
                .onChange(of: motion.isRunning) { _, running in
                    pulse = running
                }

                Text(motion.isRunning ? "Recording" : motion.status)
                    .font(.headline)
                    .foregroundStyle(motion.isRunning ? .green : .primary)

                if let sid = motion.serverSessionId {
                    Text(sid)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.orange)
                }

                Text(motion.isReachable ? "Phone ✓" : "Phone —")
                    .font(.caption2)
                    .foregroundStyle(motion.isReachable ? .green : .orange)

                Divider()

                // ── Stats ──────────────────────────────────────────────────
                VStack(spacing: 4) {
                    stat("Hz", motion.actualSampleRateHz)
                    stat("|acc|", motion.lastAccelerationMagnitude)
                    stat("|gyro|", motion.lastGyroscopeMagnitude)
                    stat("Delivered", motion.deliveredSampleCount)
                    stat("Queued",    motion.queuedSampleCount + motion.backgroundQueuedSampleCount)
                    if motion.droppedSampleCount > 0 {
                        stat("Dropped ⚠", motion.droppedSampleCount)
                    }
                    if motion.failedBatchCount > 0 {
                        stat("Failed", motion.failedBatchCount)
                    }
                }

                Divider()

                // ── Controls (manual override) ─────────────────────────────
                HStack(spacing: 12) {
                    Button("Start") {
                        WKInterfaceDevice.current().play(.start)
                        motion.start()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.green)
                    .disabled(motion.isRunning)

                    Button("Stop") {
                        WKInterfaceDevice.current().play(.stop)
                        motion.stop()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .disabled(!motion.isRunning)
                }
                .font(.caption)
                .padding(.bottom, 4)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 8)
        }
        .onAppear { pulse = motion.isRunning }
    }

    private func stat(_ title: String, _ value: Int) -> some View {
        HStack {
            Text(title).foregroundStyle(.secondary)
            Spacer()
            Text("\(value)").monospacedDigit()
        }
        .font(.caption2)
    }

    private func stat(_ title: String, _ value: Double) -> some View {
        HStack {
            Text(title).foregroundStyle(.secondary)
            Spacer()
            Text(value, format: .number.precision(.fractionLength(2)))
                .monospacedDigit()
        }
        .font(.caption2)
    }
}

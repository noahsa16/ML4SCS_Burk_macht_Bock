import SwiftUI

struct WatchView: View {
    @StateObject private var motion = MotionManager()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text(motion.status)
                    .font(.headline)
                    .lineLimit(2)
                Text(motion.isReachable ? "Phone reachable" : "Phone not reachable")
                    .font(.caption)
                    .foregroundStyle(motion.isReachable ? .green : .orange)

                Divider()

                stat("Sampled", motion.sampleCount)
                stat("Delivered", motion.deliveredSampleCount)
                stat("Queued", motion.queuedSampleCount + motion.backgroundQueuedSampleCount)
                stat("Failed", motion.failedBatchCount)
                stat("Dropped", motion.droppedSampleCount)

                HStack {
                    Button("Start") { motion.start() }
                        .disabled(motion.isRunning)
                    Button("Stop") { motion.stop() }
                        .disabled(!motion.isRunning)
                }
                .padding(.top, 4)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
    }

    private func stat(_ title: String, _ value: Int) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text("\(value)")
                .monospacedDigit()
        }
        .font(.caption)
    }
}

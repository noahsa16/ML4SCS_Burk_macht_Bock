import SwiftUI

struct WatchView: View {
    @StateObject private var motion = MotionManager()

    var body: some View {
        VStack(spacing: 12) {
            Text("\(motion.sampleCount) samples")
            Button("Start") { motion.start() }
            Button("Stop")  { motion.stop() }
        }
    }
}

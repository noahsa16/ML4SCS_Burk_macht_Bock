import SwiftUI

struct iPhoneView: View {
    @StateObject private var bridge = PhoneBridge()

    var body: some View {
        VStack(spacing: 16) {
            Text(bridge.isConnected ? "Connected" : "Not connected")
                .font(.headline)
            Text("\(bridge.sampleCount) samples received")
        }
    }
}

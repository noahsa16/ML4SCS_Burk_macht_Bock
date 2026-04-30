import SwiftUI

struct iPhoneView: View {
    @StateObject private var bridge = PhoneBridge()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(bridge.isConnected ? "Connected" : "Not connected")
                .font(.headline)

            stat("Received", bridge.receivedSampleCount)
            stat("Uploaded", bridge.uploadedSampleCount)
            stat("Queued batches", bridge.queuedBatchCount)
            stat("Upload failures", bridge.failedUploadCount)

            Text(PhoneBridge.serverAddress)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            if !bridge.lastError.isEmpty {
                Text(bridge.lastError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func stat(_ title: String, _ value: Int) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text("\(value)")
                .monospacedDigit()
        }
    }
}

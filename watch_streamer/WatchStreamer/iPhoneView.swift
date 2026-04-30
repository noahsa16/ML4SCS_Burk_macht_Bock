import SwiftUI

struct iPhoneView: View {
    @StateObject private var bridge = PhoneBridge()
    @ObservedObject  private var server = ServerCommandListener.shared
    @AppStorage("serverIP") private var serverIP = "192.168.178.147"
    @State private var editingIP = false

    var body: some View {
        NavigationStack {
            List {
                // ── Connection ─────────────────────────────────────────────
                Section("Connection") {
                    labelRow("Server",
                             server.isConnected ? "Connected ✅" : "Disconnected ❌",
                             server.isConnected ? .green : .red)

                    labelRow("Watch",
                             bridge.isConnected ? "Reachable ✅" : "Not reachable ❌",
                             bridge.isConnected ? .green : .red)

                    HStack {
                        Text("Server IP").foregroundStyle(.secondary)
                        Spacer()
                        if editingIP {
                            TextField("e.g. 192.168.1.10", text: $serverIP)
                                .multilineTextAlignment(.trailing)
                                .keyboardType(.numbersAndPunctuation)
                                .onSubmit { editingIP = false; server.connect() }
                        } else {
                            Text(serverIP).onTapGesture { editingIP = true }
                        }
                        Button(editingIP ? "Save" : "Edit") {
                            if editingIP { server.connect() }
                            editingIP.toggle()
                        }
                        .font(.caption).foregroundStyle(.blue)
                    }
                }

                Section("Command Bridge") {
                    labelRow("Last Watch command", server.lastWatchCommandStatus)
                    Text("Browser session commands are mirrored to the Watch and acknowledged back to the server.")
                        .foregroundStyle(.secondary)
                        .font(.caption)
                }

                // ── Active session ─────────────────────────────────────────
                Section("Active Session") {
                    if let sid = server.currentSessionId {
                        labelRow("Session ID", sid)
                        labelRow("Person", server.currentPersonId ?? "—")
                        labelRow("Watch streaming", "Active ✅", .green)
                    } else {
                        Text("No active session — control from browser dashboard")
                            .foregroundStyle(.secondary).font(.subheadline)
                    }
                }

                // ── Counters ───────────────────────────────────────────────
                Section("Upload Stats") {
                    countRow("Received",       bridge.receivedSampleCount)
                    countRow("Uploaded",        bridge.uploadedSampleCount)
                    countRow("Queued batches",  bridge.queuedBatchCount)
                    countRow("Upload failures", bridge.failedUploadCount)
                }

                if !bridge.lastError.isEmpty {
                    Section("Last Error") {
                        Text(bridge.lastError).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("FocusTrack")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func labelRow(_ label: String, _ value: String, _ color: Color = .primary) -> some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).foregroundStyle(color).multilineTextAlignment(.trailing)
        }
    }

    private func countRow(_ label: String, _ value: Int) -> some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text("\(value)").monospacedDigit()
        }
    }
}

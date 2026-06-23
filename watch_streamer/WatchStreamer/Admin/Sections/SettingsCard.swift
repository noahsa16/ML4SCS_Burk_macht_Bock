import SwiftUI

struct SettingsCard: View {
    @AppStorage("serverIP") private var serverIP = ServerConfig.defaultIP
    @AppStorage("requestedHz") private var requestedHz = 50.0
    @AppStorage("batchSize") private var batchSize = 10
    @AppStorage(ScrybeSettings.pinKey) private var adminPIN = ScrybeSettings.defaultPIN
    @Environment(\.scrybe) private var theme

    var body: some View {
        AdminCard(title: "Einstellungen") {
            field("Server-IP", text: $serverIP) {
                PhoneBridge.shared.syncServerIP(serverIP)
            }
            HStack {
                Text("Rate").foregroundStyle(theme.ink)
                Spacer()
                Picker("Rate", selection: $requestedHz) {
                    Text("50 Hz").tag(50.0)
                    Text("100 Hz").tag(100.0)
                }.pickerStyle(.segmented).frame(width: 160).labelsHidden()
            }
            Stepper("Batch \(batchSize)", value: $batchSize, in: 1...50)
                .foregroundStyle(theme.ink)
            field("Admin-PIN", text: $adminPIN) {}
        }
    }

    @ViewBuilder private func field(_ label: String, text: Binding<String>, onCommit: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(theme.sepia)
            TextField(label, text: text, onCommit: onCommit)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
        }
    }
}

import SwiftUI

struct SensorProbeCard: View {
    @Environment(\.scrybe) private var theme
    @ObservedObject private var server = ServerCommandListener.shared

    var body: some View {
        AdminCard(title: "Sensor-Probe") {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    probeButton("1 h", seconds: 3600)
                    probeButton("12 h", seconds: 43_200)
                }
                actionButton("Auswerten", systemImage: "chart.bar.doc.horizontal") {
                    server.fetchSensorProbeReport()
                }
                if let verdict = server.sensorProbeVerdict {
                    result(verdict)
                }
                if let readDuration = server.sensorProbeReadDuration {
                    Text(String(format: "Lesevorgang: %.1f s", readDuration))
                        .font(.caption)
                        .foregroundStyle(theme.ink.opacity(0.7))
                }
                if let raw = server.sensorProbeRaw {
                    Text(raw)
                        .font(.caption2)
                        .foregroundStyle(theme.ink.opacity(0.5))
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func probeButton(_ title: String, seconds: Double) -> some View {
        actionButton(title, systemImage: "record.circle") {
            server.startSensorProbe(durationSeconds: seconds)
        }
    }

    private func actionButton(_ title: String, systemImage: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundStyle(theme.accent)
                .scrybeSurface(cornerRadius: 12, tint: theme.accent.opacity(0.10), interactive: true)
        }
    }

    private func result(_ v: SensorProbeVerdict) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(v.passed ? "bestanden" : "durchgefallen")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(v.passed ? theme.accent : theme.danger)
            Text(String(format: "Rate %.2f Hz · Coverage %.1f %% · lange Intervalle %.2f %%",
                        v.effectiveRateHz, v.coverage * 100, v.longIntervalShare * 100))
                .font(.caption)
                .foregroundStyle(theme.ink.opacity(0.7))
            if !v.failures.isEmpty {
                Text("Fehlschläge: " + v.failures.map(\.rawValue).joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(theme.danger)
            }
        }
    }
}

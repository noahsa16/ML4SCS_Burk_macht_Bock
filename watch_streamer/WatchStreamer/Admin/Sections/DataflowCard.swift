import SwiftUI
import Combine

struct DataflowCard: View {
    @ObservedObject private var bridge = PhoneBridge.shared
    @Environment(\.scrybe) private var theme
    @State private var backlog: [Int] = []

    private var tone: Color {
        if bridge.droppedBatchCount > 0 { return theme.danger }
        if bridge.queuedBatchCount > 0 { return theme.warning }
        return theme.success
    }

    var body: some View {
        AdminCard(title: "Datenfluss") {
            HStack {
                stat("In Queue", bridge.queuedBatchCount, tone)
                Spacer()
                stat("Hochgeladen", bridge.uploadedSampleCount, theme.ink)
                Spacer()
                stat("Verworfen", bridge.droppedBatchCount, bridge.droppedBatchCount > 0 ? theme.danger : theme.ink)
            }
            if bridge.droppedBatchCount > 0 {
                Label("Daten verloren", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(theme.danger)
            }
            Sparkline(values: backlog, color: tone).frame(height: 28)
        }
        .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { _ in
            backlog.append(bridge.queuedBatchCount)
            if backlog.count > 60 { backlog.removeFirst(backlog.count - 60) }
        }
    }

    @ViewBuilder private func stat(_ title: String, _ value: Int, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(value)")
                .font(.title3.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(color)
            Text(title).font(.caption2).foregroundStyle(theme.secondaryInk)
        }
        .accessibilityElement(children: .combine)
    }
}

struct Sparkline: View {
    /// Unbounded counts; normalised against the series maximum.
    let values: [Int]
    let color: Color

    var body: some View {
        SparklineShape(normalised: SparklineShape.normalisedByMaximum(values))
            .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
            .accessibilityHidden(true)
    }
}

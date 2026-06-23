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
            Text(title).font(.caption2).foregroundStyle(theme.sepia)
        }
        .accessibilityElement(children: .combine)
    }
}

struct Sparkline: View {
    let values: [Int]
    let color: Color

    var body: some View {
        GeometryReader { geo in
            let maxV = max(values.max() ?? 1, 1)
            Path { p in
                guard values.count > 1 else { return }
                let stepX = geo.size.width / CGFloat(values.count - 1)
                for (i, v) in values.enumerated() {
                    let x = CGFloat(i) * stepX
                    let y = geo.size.height * (1 - CGFloat(v) / CGFloat(maxV))
                    if i == 0 { p.move(to: CGPoint(x: x, y: y)) }
                    else { p.addLine(to: CGPoint(x: x, y: y)) }
                }
            }
            .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
        .accessibilityHidden(true)
    }
}

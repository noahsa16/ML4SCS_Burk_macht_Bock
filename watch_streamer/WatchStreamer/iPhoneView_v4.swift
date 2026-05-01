

import SwiftUI
import Combine

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Color helpers
// ─────────────────────────────────────────────────────────────────────────────

private extension Color {
    init(r: Double, g: Double, b: Double, a: Double = 1) {
        self.init(red: r, green: g, blue: b, opacity: a)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Design tokens
// ─────────────────────────────────────────────────────────────────────────────

struct FTTheme {
    let bg, surface, surface2: Color
    let border, border2: Color
    let text, text2, text3: Color
    let accent, green, red, yellow, blue: Color
    let accentDim, greenDim, redDim: Color

    static let light = FTTheme(
        bg:        Color(r:0.960, g:0.945, b:0.920),
        surface:   Color(r:0.995, g:0.990, b:0.982),
        surface2:  Color(r:0.980, g:0.972, b:0.958),
        border:    Color(r:0.900, g:0.886, b:0.862),
        border2:   Color(r:0.868, g:0.848, b:0.820),
        text:      Color(r:0.145, g:0.132, b:0.108),
        text2:     Color(r:0.420, g:0.405, b:0.378),
        text3:     Color(r:0.615, g:0.600, b:0.576),
        accent:    Color(r:0.780, g:0.420, b:0.175),
        green:     Color(r:0.240, g:0.540, b:0.260),
        red:       Color(r:0.720, g:0.215, b:0.145),
        yellow:    Color(r:0.730, g:0.610, b:0.120),
        blue:      Color(r:0.200, g:0.400, b:0.800),
        accentDim: Color(r:0.780, g:0.420, b:0.175, a:0.12),
        greenDim:  Color(r:0.240, g:0.540, b:0.260, a:0.12),
        redDim:    Color(r:0.720, g:0.215, b:0.145, a:0.10)
    )

    static let dark = FTTheme(
        bg:        Color(r:0.120, g:0.112, b:0.098),
        surface:   Color(r:0.168, g:0.158, b:0.142),
        surface2:  Color(r:0.210, g:0.200, b:0.182),
        border:    Color(r:0.272, g:0.260, b:0.240),
        border2:   Color(r:0.345, g:0.330, b:0.308),
        text:      Color(r:0.935, g:0.925, b:0.908),
        text2:     Color(r:0.735, g:0.720, b:0.698),
        text3:     Color(r:0.560, g:0.548, b:0.528),
        accent:    Color(r:0.890, g:0.560, b:0.275),
        green:     Color(r:0.385, g:0.730, b:0.405),
        red:       Color(r:0.840, g:0.335, b:0.240),
        yellow:    Color(r:0.850, g:0.740, b:0.225),
        blue:      Color(r:0.400, g:0.600, b:1.000),
        accentDim: Color(r:0.890, g:0.560, b:0.275, a:0.15),
        greenDim:  Color(r:0.385, g:0.730, b:0.405, a:0.14),
        redDim:    Color(r:0.840, g:0.335, b:0.240, a:0.12)
    )
}

private struct ThemeKey: EnvironmentKey {
    static let defaultValue = FTTheme.light
}
extension EnvironmentValues {
    var ft: FTTheme {
        get { self[ThemeKey.self] }
        set { self[ThemeKey.self] = newValue }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Typography helpers
// ─────────────────────────────────────────────────────────────────────────────

private enum FT {
    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Log store
// ─────────────────────────────────────────────────────────────────────────────

struct FTLogEntry: Identifiable {
    let id   = UUID()
    let date = Date()
    let tag:      String
    let tagColor: Color
    let message:  String

    var timeString: String {
        let f = DateFormatter(); f.dateFormat = "HH:mm:ss"; return f.string(from: date)
    }
}

@MainActor
final class FTLogStore: ObservableObject {
    static let shared = FTLogStore()
    @Published private(set) var entries: [FTLogEntry] = []

    func add(_ tag: String, _ message: String, color: Color) {
        entries.insert(FTLogEntry(tag: tag, tagColor: color, message: message), at: 0)
        if entries.count > 60 { entries = Array(entries.prefix(60)) }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – IMU data store (shared between Dashboard + Session tabs)
// ─────────────────────────────────────────────────────────────────────────────

@MainActor
final class IMUDataStore: ObservableObject {
    static let shared = IMUDataStore()
    @Published var accSamples:  [Double] = Array(repeating: 0, count: 120)
    @Published var gyroSamples: [Double] = Array(repeating: 0, count: 120)

    func pushBatch(accValues: [Double], gyroValues: [Double]) {
        var newAcc  = accSamples  + accValues
        var newGyro = gyroSamples + gyroValues
        if newAcc.count  > 120 { newAcc  = Array(newAcc.suffix(120))  }
        if newGyro.count > 120 { newGyro = Array(newGyro.suffix(120)) }
        accSamples  = newAcc
        gyroSamples = newGyro
    }

    func startStreaming() {}

    func stopStreaming() {
        accSamples  = Array(repeating: 0, count: 120)
        gyroSamples = Array(repeating: 0, count: 120)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Micro components
// ─────────────────────────────────────────────────────────────────────────────

struct FTDot: View {
    let color: Color
    var pulse: Bool = false
    @State private var dim = false

    var body: some View {
        Circle().fill(color).frame(width: 7, height: 7)
            .opacity(pulse && dim ? 0.28 : 1)
            .onAppear {
                guard pulse else { return }
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    dim = true
                }
            }
    }
}

struct FTBadge: View {
    @Environment(\.ft) var t
    let label: String
    let ok:    Bool

    var body: some View {
        HStack(spacing: 4) {
            FTDot(color: ok ? t.green : t.red, pulse: ok)
            Text(label)
                .font(FT.mono(10, weight: .bold))
                .textCase(.uppercase)
                .kerning(0.5)
        }
        .foregroundColor(ok ? t.green : t.red)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background((ok ? t.green : t.red).opacity(0.12))
        .cornerRadius(4)
    }
}

struct FTSLabel: View {
    @Environment(\.ft) var t
    let text: String
    var body: some View {
        Text(text).font(FT.sans(10, weight: .semibold))
            .textCase(.uppercase).kerning(0.6)
            .foregroundColor(t.text2)
    }
}

struct FTCard<Content: View>: View {
    @Environment(\.ft) var t
    var accent: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(spacing: 0) { content() }
            .background(t.surface)
            .cornerRadius(10)
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(accent ? t.accent.opacity(0.35) : t.border, lineWidth: 1))
    }
}

struct FTCardHeader: View {
    @Environment(\.ft) var t
    let title: String
    var trailing: AnyView? = nil

    var body: some View {
        HStack {
            Text(title).font(FT.sans(11, weight: .semibold))
                .textCase(.uppercase).kerning(0.5)
                .foregroundColor(t.text2)
            Spacer()
            trailing
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .overlay(alignment: .bottom) {
            Rectangle().fill(t.border).frame(height: 1)
        }
    }
}

// Stat cell used in grids
struct FTStatCell: View {
    @Environment(\.ft) var t
    let label: String
    let value: String
    var color:  Color? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FTSLabel(text: label)
            Text(value)
                .font(FT.mono(17, weight: .semibold))
                .foregroundColor(color ?? t.text)
                .monospacedDigit()
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – IMU Chart (SwiftUI Canvas)
// ─────────────────────────────────────────────────────────────────────────────

struct IMUChart: View {
    @Environment(\.ft) var t
    @ObservedObject var store = IMUDataStore.shared
    var active: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Legend row
            HStack {
                Text("LIVE IMU · Acc + Gyro")
                    .font(FT.mono(9, weight: .medium))
                    .kerning(0.8)
                    .textCase(.uppercase)
                    .foregroundColor(t.text3)
                Spacer()
                HStack(spacing: 12) {
                    legendItem(color: t.accent, label: "Acc")
                    legendItem(color: t.yellow, label: "Gyro")
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 6)

            // Canvas chart
            Canvas { ctx, size in
                let W = size.width, H = size.height
                let MAX = 120

                // Background
                ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(t.bg))

                // Grid lines
                for i in 1...3 {
                    let y = H * CGFloat(i) / 4
                    var p = Path(); p.move(to: CGPoint(x: 0, y: y))
                    p.addLine(to: CGPoint(x: W, y: y))
                    ctx.stroke(p, with: .color(t.border), lineWidth: 0.5)
                }
                // Centre line dashed
                var cp = Path(); cp.move(to: CGPoint(x: 0, y: H/2))
                cp.addLine(to: CGPoint(x: W, y: H/2))
                ctx.stroke(cp, with: .color(t.border.opacity(0.5)),
                           style: StrokeStyle(lineWidth: 0.5, dash: [3, 5]))

                func drawSeries(_ data: [Double], color: Color, width: CGFloat) {
                    guard data.count > 1 else { return }
                    var path = Path()
                    for (i, v) in data.enumerated() {
                        let x = CGFloat(i) / CGFloat(MAX - 1) * W
                        let y = H/2 - (v / 1.2) * (H/2 - 4)
                        if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                        else       { path.addLine(to: CGPoint(x: x, y: y)) }
                    }
                    ctx.stroke(path, with: .color(color), lineWidth: width)
                }

                drawSeries(store.gyroSamples, color: t.yellow.opacity(0.8), width: 1.2)
                drawSeries(store.accSamples,  color: t.accent,              width: 1.8)

                if !active {
                    // Idle overlay text
                    let msg = "— waiting for session —"
                    ctx.draw(Text(msg).font(FT.mono(10)).foregroundColor(t.text3.opacity(0.6)),
                             at: CGPoint(x: W/2, y: H/2), anchor: .center)
                }
            }
            .frame(height: 80)
            .background(t.bg)
        }
    }

    private func legendItem(color: Color, label: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 1).fill(color).frame(width: 16, height: 2)
            Text(label).font(FT.mono(9)).foregroundColor(t.text3)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Connection half view
// ─────────────────────────────────────────────────────────────────────────────

struct ConnectionHalf: View {
    @Environment(\.ft) var t
    let label:  String
    let ok:     Bool
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            FTSLabel(text: label)
            HStack(spacing: 5) {
                FTDot(color: ok ? t.green : t.red, pulse: ok)
                Text(ok ? (label == "Server" ? "CONNECTED" : "REACHABLE") : "OFFLINE")
                    .font(FT.mono(11, weight: .bold))
                    .foregroundColor(ok ? t.green : t.red)
            }
            Text(detail).font(FT.mono(10)).foregroundColor(t.text3)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – System log card
// ─────────────────────────────────────────────────────────────────────────────

struct FTLogCard: View {
    @Environment(\.ft) var t
    @ObservedObject private var store = FTLogStore.shared
    var maxEntries = 6

    var body: some View {
        FTCard {
            FTCardHeader(title: "System Events", trailing: AnyView(
                FTDot(color: t.green, pulse: true)
            ))

            VStack(spacing: 0) {
                if store.entries.isEmpty {
                    Text("Waiting for events…")
                        .font(FT.mono(11)).italic().foregroundColor(t.text3)
                        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    ForEach(Array(store.entries.prefix(maxEntries).enumerated()), id: \.element.id) { idx, entry in
                        HStack(alignment: .top, spacing: 6) {
                            Text(entry.timeString)
                                .font(FT.mono(10)).foregroundColor(t.text3)
                                .frame(width: 56, alignment: .leading)
                            Text(entry.tag)
                                .font(FT.mono(10, weight: .bold)).kerning(0.4)
                                .foregroundColor(entry.tagColor)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(entry.tagColor.opacity(0.12))
                                .cornerRadius(2)
                            Text(entry.message)
                                .font(FT.mono(10)).foregroundColor(t.text2)
                                .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.horizontal, 12).padding(.vertical, 4)
                        if idx < min(maxEntries, store.entries.count) - 1 {
                            Rectangle().fill(t.border.opacity(0.5)).frame(height: 1)
                                .padding(.leading, 74)
                        }
                    }
                }
            }
            .background(t.bg)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Error banner
// ─────────────────────────────────────────────────────────────────────────────

struct FTErrorBanner: View {
    @Environment(\.ft) var t
    let message: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(t.red).font(.system(size: 13))
            VStack(alignment: .leading, spacing: 3) {
                Text("Error").font(FT.sans(10, weight: .semibold))
                    .textCase(.uppercase).kerning(0.6).foregroundColor(t.red)
                Text(message).font(FT.mono(11)).foregroundColor(t.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        .padding(12)
        .background(t.red.opacity(0.08)).cornerRadius(10)
        .overlay(RoundedRectangle(cornerRadius: 10)
            .stroke(t.red.opacity(0.2), lineWidth: 1))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 1: Dashboard
// ─────────────────────────────────────────────────────────────────────────────

struct DashboardTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var bridge  = PhoneBridge.shared
    @ObservedObject private var server  = ServerCommandListener.shared
    @ObservedObject private var imu     = IMUDataStore.shared
    @AppStorage("serverIP") private var serverIP = "192.168.178.147"

    private var received: Int { bridge.receivedSampleCount }
    private var uploaded: Int { bridge.uploadedSampleCount }
    private var queued:   Int { bridge.queuedBatchCount }
    private var failed:   Int { bridge.failedUploadCount }
    private var pct: Double {
        received > 0 ? min(1, Double(uploaded) / Double(received)) : 0
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {

                // ── IMU Chart card ──────────────────────────────────────────
                FTCard {
                    IMUChart(active: server.currentSessionId != nil)
                    // Mini stats row
                    HStack(spacing: 0) {
                        miniStat("Hz",        server.currentSessionId != nil ? "50 Hz" : "— Hz",
                                 color: server.currentSessionId != nil ? t.green : t.text3)
                        Rectangle().fill(t.border).frame(width: 1)
                        miniStat("Batch",     server.currentSessionId != nil ? "10 smpl" : "—")
                        Rectangle().fill(t.border).frame(width: 1)
                        miniStat("Transport", "WCSession")
                    }
                    .overlay(alignment: .top) { Rectangle().fill(t.border).frame(height: 1) }
                }

                // ── Session banner ──────────────────────────────────────────
                let hasSession = server.currentSessionId != nil
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            FTDot(color: hasSession ? t.green : t.text3, pulse: hasSession)
                            Text(hasSession ? "Session Active" : "No Session")
                                .font(FT.mono(10, weight: .bold))
                                .textCase(.uppercase).kerning(0.6)
                                .foregroundColor(hasSession ? t.green : t.text3)
                        }
                        if let sid = server.currentSessionId {
                            HStack(spacing: 4) {
                                Text(sid).font(FT.mono(12)).foregroundColor(t.text)
                                if let pid = server.currentPersonId {
                                    Text("·").foregroundColor(t.text3)
                                    Text(pid).font(FT.mono(12, weight: .semibold))
                                        .foregroundColor(t.accent)
                                }
                            }
                            .lineLimit(1)
                        } else {
                            Text("Control from browser dashboard")
                                .font(FT.sans(12)).italic().foregroundColor(t.text3)
                        }
                    }
                    Spacer()
                    if hasSession {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(t.text3)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(hasSession ? t.greenDim : t.surface)
                .cornerRadius(10)
                .overlay(RoundedRectangle(cornerRadius: 10)
                    .stroke(hasSession ? t.green.opacity(0.25) : t.border, lineWidth: 1))

                // ── Connections card ────────────────────────────────────────
                FTCard {
                    HStack(spacing: 0) {
                        ConnectionHalf(label: "Server", ok: server.isConnected,
                                       detail: server.isConnected ? "ws://…:8000/ws" : "Connection refused")
                        Rectangle().fill(t.border).frame(width: 1)
                        ConnectionHalf(label: "Apple Watch", ok: bridge.isConnected,
                                       detail: bridge.isConnected ? "WatchConnectivity" : "Not reachable")
                    }
                    .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }
                    // IP row
                    HStack(spacing: 8) {
                        Text("Server IP").font(FT.sans(10, weight: .semibold))
                            .textCase(.uppercase).kerning(0.6).foregroundColor(t.text3)
                        Text(serverIP).font(FT.mono(11)).foregroundColor(t.text)
                        Spacer()
                    }
                    .padding(.horizontal, 12).padding(.vertical, 9)
                }

                // ── Upload stats ────────────────────────────────────────────
                FTCard {
                    FTCardHeader(title: "Upload Stats")
                    HStack(spacing: 0) {
                        FTStatCell(label: "Received", value: received.formatted())
                        Rectangle().fill(t.border).frame(width: 1)
                        FTStatCell(label: "Uploaded", value: uploaded.formatted(), color: t.green)
                        Rectangle().fill(t.border).frame(width: 1)
                        FTStatCell(label: "Queued",   value: "\(queued)",  color: queued > 0 ? t.yellow : t.text3)
                        Rectangle().fill(t.border).frame(width: 1)
                        FTStatCell(label: "Failed",   value: "\(failed)",  color: failed > 0 ? t.red    : t.text3)
                    }
                    .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }
                    // Progress bar
                    VStack(spacing: 5) {
                        HStack {
                            Text("Upload rate").font(FT.mono(10)).foregroundColor(t.text3)
                            Spacer()
                            Text("\(Int(pct * 100))%").font(FT.mono(10)).foregroundColor(t.text3)
                        }
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 2).fill(t.border)
                                RoundedRectangle(cornerRadius: 2)
                                    .fill(pct > 0 ? t.green : t.text3)
                                    .frame(width: geo.size.width * pct)
                                    .animation(.easeInOut(duration: 0.8), value: pct)
                            }
                        }.frame(height: 4)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 10)
                }

                // ── Last command ────────────────────────────────────────────
                let cmd = server.lastWatchCommandStatus
                HStack(spacing: 8) {
                    Text("Last cmd").font(FT.sans(10, weight: .semibold))
                        .textCase(.uppercase).kerning(0.6).foregroundColor(t.text3)
                        .fixedSize()
                    Text(cmd).font(FT.mono(11))
                        .foregroundColor(cmd.contains("acknowledged") ? t.green :
                                        cmd == "No command sent"      ? t.text3 : t.red)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(t.surface).cornerRadius(10)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(t.border, lineWidth: 1))

                // ── Error banner ────────────────────────────────────────────
                if !bridge.lastError.isEmpty {
                    FTErrorBanner(message: bridge.lastError)
                }

                // Footer
                HStack {
                    Text("WatchStreamer · PhoneBridge")
                    Spacer()
                    Text("v1.0")
                }
                .font(FT.mono(9)).foregroundColor(t.text3).padding(.top, 4)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(t.bg)
        .onAppear {
            if server.currentSessionId != nil { IMUDataStore.shared.startStreaming() }
        }
        .onReceive(server.$currentSessionId) { sid in
            if sid != nil { IMUDataStore.shared.startStreaming() }
            else          { IMUDataStore.shared.stopStreaming()  }
        }
    }

    @ViewBuilder
    private func miniStat(_ label: String, _ value: String, color: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            FTSLabel(text: label)
            Text(value).font(FT.mono(11, weight: .semibold))
                .foregroundColor(color ?? t.text)
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 2: Session
// ─────────────────────────────────────────────────────────────────────────────

struct SessionTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var imu    = IMUDataStore.shared
    @State private var elapsed: Int    = 0
    private var timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var hasSession: Bool { server.currentSessionId != nil }

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {

                // ── Session info card ───────────────────────────────────────
                FTCard(accent: hasSession) {
                    FTCardHeader(title: "Session", trailing: AnyView(
                        Group {
                            if hasSession { FTBadge(label: "Streaming", ok: true) }
                            else {
                                Text("no session").font(FT.mono(10)).foregroundColor(t.text3)
                            }
                        }
                    ))

                    if hasSession, let sid = server.currentSessionId {
                        HStack(spacing: 0) {
                            VStack(alignment: .leading, spacing: 4) {
                                FTSLabel(text: "Session ID")
                                Text(sid).font(FT.mono(12, weight: .semibold))
                                    .foregroundColor(t.text).lineLimit(1)
                            }
                            .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                            Rectangle().fill(t.border).frame(width: 1)
                            VStack(alignment: .leading, spacing: 4) {
                                FTSLabel(text: "Person")
                                Text(server.currentPersonId ?? "—")
                                    .font(FT.mono(14, weight: .bold)).foregroundColor(t.accent)
                            }
                            .padding(12).frame(maxWidth: 110, alignment: .leading)
                        }
                        .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }

                        HStack(spacing: 0) {
                            metricCell("Duration",    String(format: "%02d:%02d", elapsed/60, elapsed%60))
                            Rectangle().fill(t.border).frame(width: 1)
                            metricCell("Sample rate", "50 Hz",  color: t.green)
                            Rectangle().fill(t.border).frame(width: 1)
                            metricCell("Batch",       "10 smpl")
                        }
                        .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }
                    } else {
                        Text("No active session.\nSessions are started from the browser dashboard.\nWhen a session starts, the Watch begins streaming IMU data.")
                            .font(FT.sans(12)).italic().foregroundColor(t.text3)
                            .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                            .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }
                    }
                }

                // ── IMU Chart ───────────────────────────────────────────────
                FTCard {
                    IMUChart(active: hasSession)
                }

                // ── Sample pipeline ─────────────────────────────────────────
                FTCard {
                    FTCardHeader(title: "Sample Pipeline")
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 0) {
                        FTStatCell(label: "Received", value: bridge.receivedSampleCount.formatted())
                        FTStatCell(label: "Uploaded", value: bridge.uploadedSampleCount.formatted(), color: t.green)
                        FTStatCell(label: "Queued",   value: "\(bridge.queuedBatchCount)",  color: bridge.queuedBatchCount > 0 ? t.yellow : t.text3)
                        FTStatCell(label: "Failed",   value: "\(bridge.failedUploadCount)", color: bridge.failedUploadCount > 0 ? t.red    : t.text3)
                    }
                    .overlay {
                        // Grid dividers
                        GeometryReader { geo in
                            let w = geo.size.width, h = geo.size.height
                            Path { p in
                                p.move(to:    CGPoint(x: w/2, y: 0))
                                p.addLine(to: CGPoint(x: w/2, y: h))
                                p.move(to:    CGPoint(x: 0, y: h/2))
                                p.addLine(to: CGPoint(x: w, y: h/2))
                            }
                            .stroke(t.border, lineWidth: 1)
                        }
                    }
                }

                // ── System log ──────────────────────────────────────────────
                FTLogCard(maxEntries: 8)

                // Footer
                HStack {
                    Text("WatchStreamer · PhoneBridge")
                    Spacer(); Text("v1.0")
                }
                .font(FT.mono(9)).foregroundColor(t.text3).padding(.top, 4)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(t.bg)
        .onReceive(timer) { _ in if hasSession { elapsed += 1 } }
        .onChange(of: server.currentSessionId) { sid in if sid == nil { elapsed = 0 } }
    }

    @ViewBuilder
    private func metricCell(_ label: String, _ value: String, color: Color? = nil) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            FTSLabel(text: label)
            Text(value).font(FT.mono(16, weight: .semibold))
                .foregroundColor(color ?? t.text)
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 3: Settings
// ─────────────────────────────────────────────────────────────────────────────

struct SettingsTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @AppStorage("serverIP")     private var serverIP   = "192.168.178.147"
    @AppStorage("ft_showStats") private var showStats  = true
    @AppStorage("ft_showLog")   private var showLog    = true
    @State private var editingIP = false
    @FocusState private var ipFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {

                // ── Network ─────────────────────────────────────────────────
                sectionHeader("Network")
                FTCard {
                    // IP editor
                    VStack(alignment: .leading, spacing: 6) {
                        FTSLabel(text: "Server IP")
                        if editingIP {
                            HStack(spacing: 8) {
                                TextField("192.168.x.x", text: $serverIP)
                                    .font(FT.mono(14)).foregroundColor(t.text)
                                    .keyboardType(.numbersAndPunctuation)
                                    .focused($ipFocused).onSubmit { save() }
                                    .padding(.horizontal, 8).padding(.vertical, 5)
                                    .background(t.surface2).cornerRadius(6)
                                    .overlay(RoundedRectangle(cornerRadius: 6)
                                        .stroke(t.accent, lineWidth: 1))
                                Button("Save", action: save)
                                    .font(FT.sans(12, weight: .semibold))
                                    .foregroundColor(.white)
                                    .padding(.horizontal, 12).padding(.vertical, 6)
                                    .background(t.accent).cornerRadius(6)
                            }
                        } else {
                            HStack {
                                Text(serverIP).font(FT.mono(14)).foregroundColor(t.text)
                                Spacer()
                                Button("Edit") { editingIP = true; ipFocused = true }
                                    .font(FT.sans(12, weight: .semibold))
                                    .foregroundColor(t.accent)
                                    .padding(.horizontal, 10).padding(.vertical, 4)
                                    .background(t.accentDim).cornerRadius(5)
                                    .overlay(RoundedRectangle(cornerRadius: 5)
                                        .stroke(t.accent.opacity(0.25), lineWidth: 1))
                            }
                        }
                    }
                    .padding(14)
                    .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }

                    // Connection status + reconnect
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Connection").font(FT.sans(13)).foregroundColor(t.text)
                            Text(server.isConnected ? "WebSocket connected" : "Disconnected")
                                .font(FT.mono(10))
                                .foregroundColor(server.isConnected ? t.green : t.red)
                        }
                        Spacer()
                        Button("Reconnect") { server.connect() }
                            .font(FT.sans(12, weight: .semibold)).foregroundColor(.white)
                            .padding(.horizontal, 14).padding(.vertical, 7)
                            .background(t.accent).cornerRadius(6)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 12)
                }

                // ── Display ──────────────────────────────────────────────────
                sectionHeader("Display")
                FTCard {
                    toggleRow("Upload Stats", sub: "Show sample counters on dashboard",
                              value: $showStats)
                    toggleRow("System Log",   sub: "Show live event feed",
                              value: $showLog)
                }

                // ── Apple Watch ──────────────────────────────────────────────
                sectionHeader("Apple Watch")
                FTCard {
                    VStack(spacing: 0) {
                        deviceRow("Status",     bridge.isConnected ? "Reachable" : "Offline",
                                  color: bridge.isConnected ? t.green : t.red)
                        deviceRow("IMU rate",   server.currentSessionId != nil ? "50 Hz" : "— Hz")
                        deviceRow("Batch size", server.currentSessionId != nil ? "10 samples" : "—")
                        deviceRow("Transport",  "WatchConnectivity")
                        deviceRow("Last data",  server.currentSessionId != nil ? "just now" : "—", isLast: true)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 4)
                }

                // Footer
                HStack {
                    Text("WatchStreamer · PhoneBridge")
                    Spacer(); Text("v1.0")
                }
                .font(FT.mono(9)).foregroundColor(t.text3)
                .padding(.horizontal, 16).padding(.top, 20)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(t.bg)
    }

    private func save() {
        editingIP = false; ipFocused = false
        bridge.syncServerIP(serverIP)
        server.connect()
    }

    @ViewBuilder
    private func sectionHeader(_ text: String) -> some View {
        Text(text).font(FT.mono(10, weight: .semibold))
            .textCase(.uppercase).kerning(0.8)
            .foregroundColor(t.text3)
            .padding(.horizontal, 4).padding(.top, 20).padding(.bottom, 8)
    }

    @ViewBuilder
    private func toggleRow(_ label: String, sub: String, value: Binding<Bool>) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(FT.sans(14)).foregroundColor(t.text)
                Text(sub).font(FT.sans(11)).foregroundColor(t.text3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Toggle("", isOn: value).labelsHidden()
                .tint(t.green)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }
    }

    @ViewBuilder
    private func deviceRow(_ label: String, _ value: String,
                           color: Color? = nil, isLast: Bool = false) -> some View {
        HStack {
            Text(label).font(FT.sans(12)).foregroundColor(t.text2)
            Spacer()
            Text(value).font(FT.mono(12, weight: .medium))
                .foregroundColor(color ?? t.text)
        }
        .padding(.vertical, 6)
        .overlay(alignment: .bottom) {
            if !isLast { Rectangle().fill(t.border).frame(height: 1) }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Root view with TabView
// ─────────────────────────────────────────────────────────────────────────────

struct iPhoneView: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @AppStorage("serverIP") private var serverIP = "192.168.178.147"
    @Environment(\.colorScheme) private var scheme

    private var theme: FTTheme { scheme == .dark ? .dark : .light }

    var body: some View {
        TabView {
            DashboardTab()
                .tabItem {
                    Label("Dashboard", systemImage: "square.grid.2x2")
                }

            SessionTab()
                .tabItem {
                    Label("Session", systemImage: "record.circle")
                }
                .badge(server.currentSessionId != nil ? "●" : nil)

            SettingsTab()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
        .accentColor(theme.accent)
        .environment(\.ft, theme)
        .preferredColorScheme(.none)
        .onAppear { bridge.syncServerIP(serverIP) }
        // Feed log store from server events
        .onReceive(server.$isConnected) { ok in
            Task { @MainActor in
                FTLogStore.shared.add("WS",
                    ok ? "connected → ws://\(serverIP):8000/ws" : "disconnected",
                    color: ok ? theme.green : theme.red)
            }
        }
        .onReceive(server.$lastWatchCommandStatus) { cmd in
            guard !cmd.isEmpty, cmd != "No command sent" else { return }
            let ok = cmd.contains("acknowledged")
            Task { @MainActor in
                FTLogStore.shared.add(ok ? "ACK" : "ERR", cmd,
                    color: ok ? theme.yellow : theme.red)
            }
        }
        .onReceive(server.$currentSessionId) { sid in
            Task { @MainActor in
                if let sid { FTLogStore.shared.add("SESSION", "start → \(sid)", color: theme.green) }
                else       { FTLogStore.shared.add("SESSION", "stopped",        color: theme.yellow) }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Preview
// ─────────────────────────────────────────────────────────────────────────────

#Preview("Light") { iPhoneView().preferredColorScheme(.light) }
#Preview("Dark")  { iPhoneView().preferredColorScheme(.dark)  }

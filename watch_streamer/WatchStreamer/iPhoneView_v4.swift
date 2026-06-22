

import SwiftUI
import Combine
#if canImport(UIKit)
import UIKit
#endif

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Color helpers
// ─────────────────────────────────────────────────────────────────────────────

private extension Color {
    init(r: Double, g: Double, b: Double, a: Double = 1) {
        self.init(red: r, green: g, blue: b, opacity: a)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Design tokens (Phase 1 — sRGB-Mirror der oklch-Tokens aus dashboard.html)
// ─────────────────────────────────────────────────────────────────────────────

struct FTTheme {
    let bg, surface, surface2: Color
    let border, border2: Color
    let text, text2, text3: Color
    let accent, accentHover: Color
    let green, red, yellow, blue: Color
    let accentDim, greenDim, redDim, yellowDim: Color

    static let light = FTTheme(
        bg:          Color(r:0.961, g:0.949, b:0.929),
        surface:     Color(r:0.997, g:0.992, b:0.984),
        surface2:    Color(r:0.985, g:0.974, b:0.957),
        border:      Color(r:0.890, g:0.870, b:0.840),
        border2:     Color(r:0.850, g:0.825, b:0.788),
        text:        Color(r:0.155, g:0.135, b:0.110),
        text2:       Color(r:0.435, g:0.410, b:0.378),
        text3:       Color(r:0.625, g:0.605, b:0.575),
        accent:      Color(r:0.778, g:0.420, b:0.178),
        accentHover: Color(r:0.700, g:0.370, b:0.150),
        green:       Color(r:0.290, g:0.555, b:0.295),
        red:         Color(r:0.770, g:0.260, b:0.180),
        yellow:      Color(r:0.735, g:0.610, b:0.155),
        blue:        Color(r:0.220, g:0.430, b:0.820),
        accentDim:   Color(r:0.778, g:0.420, b:0.178, a:0.12),
        greenDim:    Color(r:0.290, g:0.555, b:0.295, a:0.12),
        redDim:      Color(r:0.770, g:0.260, b:0.180, a:0.10),
        yellowDim:   Color(r:0.735, g:0.610, b:0.155, a:0.14)
    )

    static let dark = FTTheme(
        bg:          Color(r:0.135, g:0.122, b:0.105),
        surface:     Color(r:0.200, g:0.183, b:0.160),
        surface2:    Color(r:0.255, g:0.235, b:0.208),
        border:      Color(r:0.325, g:0.305, b:0.280),
        border2:     Color(r:0.420, g:0.395, b:0.365),
        text:        Color(r:0.935, g:0.918, b:0.890),
        text2:       Color(r:0.745, g:0.720, b:0.685),
        text3:       Color(r:0.585, g:0.560, b:0.525),
        accent:      Color(r:0.910, g:0.585, b:0.290),
        accentHover: Color(r:0.965, g:0.660, b:0.350),
        green:       Color(r:0.430, g:0.755, b:0.450),
        red:         Color(r:0.880, g:0.385, b:0.275),
        yellow:      Color(r:0.870, g:0.745, b:0.235),
        blue:        Color(r:0.450, g:0.620, b:1.000),
        accentDim:   Color(r:0.910, g:0.585, b:0.290, a:0.16),
        greenDim:    Color(r:0.430, g:0.755, b:0.450, a:0.14),
        redDim:      Color(r:0.880, g:0.385, b:0.275, a:0.13),
        yellowDim:   Color(r:0.870, g:0.745, b:0.235, a:0.15)
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

enum FTRadius {
    static let xs: CGFloat   = 4
    static let sm: CGFloat   = 6
    static let md: CGFloat   = 10
    static let pill: CGFloat = 999
}

enum FTSpace {
    static let cardPad: CGFloat   = 18
    static let heroPad: CGFloat   = 22
    static let pageH: CGFloat     = 16
    static let pageV: CGFloat     = 14
    static let stack: CGFloat     = 12
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Typography helpers
// ─────────────────────────────────────────────────────────────────────────────

enum FT {
    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Haptics
// ─────────────────────────────────────────────────────────────────────────────

enum FTHaptics {
    #if canImport(UIKit)
    static func light()   { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func medium()  { UIImpactFeedbackGenerator(style: .medium).impactOccurred() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
    static func error()   { UINotificationFeedbackGenerator().notificationOccurred(.error) }
    #else
    static func light()   {}
    static func medium()  {}
    static func success() {}
    static func warning() {}
    static func error()   {}
    #endif
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
// MARK: – Atomic micro components
// ─────────────────────────────────────────────────────────────────────────────

struct FTDot: View {
    let color: Color
    var pulse: Bool = false
    var size: CGFloat = 7
    @State private var dim = false

    var body: some View {
        Circle().fill(color).frame(width: size, height: size)
            .opacity(pulse && dim ? 0.28 : 1)
            .onAppear {
                guard pulse else { return }
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    dim = true
                }
            }
    }
}

struct FTPill: View {
    @Environment(\.ft) var t
    enum Tone { case ok, warn, err, neutral }
    let label: String
    var tone: Tone = .neutral
    var pulse: Bool = false

    private var color: Color {
        switch tone {
        case .ok:      return t.green
        case .warn:    return t.yellow
        case .err:     return t.red
        case .neutral: return t.text3
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            FTDot(color: color, pulse: pulse, size: 6)
            Text(label)
                .font(FT.mono(10, weight: .semibold))
                .textCase(.uppercase)
                .kerning(0.5)
                .foregroundColor(t.text2)
        }
        .padding(.horizontal, 9).padding(.vertical, 4)
        .background(t.surface2)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(t.border, lineWidth: 1))
    }
}

struct FTBadge: View {
    @Environment(\.ft) var t
    let label: String
    let ok:    Bool

    var body: some View {
        HStack(spacing: 5) {
            FTDot(color: ok ? t.green : t.red, pulse: ok, size: 6)
            Text(label)
                .font(FT.mono(10, weight: .bold))
                .textCase(.uppercase)
                .kerning(0.5)
        }
        .foregroundColor(ok ? t.green : t.red)
        .padding(.horizontal, 9).padding(.vertical, 4)
        .background((ok ? t.green : t.red).opacity(0.12))
        .clipShape(Capsule())
    }
}

struct FTLiveIndicator: View {
    @Environment(\.ft) var t

    var body: some View {
        HStack(spacing: 5) {
            FTDot(color: t.red, pulse: true, size: 7)
            Text("REC")
                .font(FT.sans(10, weight: .bold))
                .kerning(1.0)
                .foregroundColor(t.red)
        }
    }
}

struct FTSLabel: View {
    @Environment(\.ft) var t
    let text: String
    var body: some View {
        Text(text).font(FT.sans(10, weight: .semibold))
            .textCase(.uppercase).kerning(0.6)
            .foregroundColor(t.text3)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Cards (default / hero)
// ─────────────────────────────────────────────────────────────────────────────

struct FTCard<Content: View>: View {
    @Environment(\.ft) var t
    var accent: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(spacing: 0) { content() }
            .background(t.surface)
            .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
            .overlay(RoundedRectangle(cornerRadius: FTRadius.md)
                .stroke(accent ? t.accent.opacity(0.35) : t.border, lineWidth: 1))
    }
}

struct FTHeroCard<Content: View>: View {
    @Environment(\.ft) var t
    var live: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(spacing: 0) { content() }
            .background(t.surface)
            .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
            .overlay(alignment: .top) {
                LinearGradient(colors: live
                                ? [Color.clear, t.accent, t.accent, Color.clear]
                                : [t.border2, t.border2],
                               startPoint: .leading, endPoint: .trailing)
                    .frame(height: 2)
                    .animation(.easeInOut(duration: 0.3), value: live)
            }
            .overlay(RoundedRectangle(cornerRadius: FTRadius.md)
                .stroke(t.border, lineWidth: 1))
    }
}

struct FTCardHeader: View {
    @Environment(\.ft) var t
    let title: String
    var subtitle: String? = nil
    var trailing: AnyView? = nil

    var body: some View {
        HStack {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(title).font(FT.sans(11, weight: .semibold))
                    .textCase(.uppercase).kerning(0.5)
                    .foregroundColor(t.text2)
                if let subtitle {
                    Text(subtitle).font(FT.sans(11)).foregroundColor(t.text3)
                }
            }
            Spacer()
            trailing
        }
        .padding(.horizontal, FTSpace.cardPad)
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) {
            Rectangle().fill(t.border).frame(height: 1)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Hero values + stat boxes
// ─────────────────────────────────────────────────────────────────────────────

struct FTHeroValue: View {
    @Environment(\.ft) var t
    let value: String
    var color: Color? = nil
    var size: CGFloat = 28

    var body: some View {
        Group {
            if #available(iOS 16.0, *) {
                Text(value)
                    .contentTransition(.numericText(countsDown: false))
                    .animation(.easeOut(duration: 0.35), value: value)
            } else {
                Text(value)
            }
        }
        .font(FT.sans(size, weight: .semibold))
        .kerning(-0.5)
        .monospacedDigit()
        .foregroundColor(color ?? t.text)
        .lineLimit(1)
        .minimumScaleFactor(0.7)
    }
}

struct FTStatBox: View {
    @Environment(\.ft) var t
    let label: String
    let value: String
    var color: Color? = nil
    var size: CGFloat = 26

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            FTHeroValue(value: value, color: color, size: size)
            Text(label).font(FT.mono(10, weight: .semibold))
                .textCase(.uppercase).kerning(0.6)
                .foregroundColor(t.text3)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(t.surface2)
        .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
        .overlay(RoundedRectangle(cornerRadius: FTRadius.sm)
            .stroke(t.border, lineWidth: 1))
    }
}

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
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Empty state
// ─────────────────────────────────────────────────────────────────────────────

struct FTEmptyState: View {
    @Environment(\.ft) var t
    let glyph: String
    let title: String
    let hint:  String

    var body: some View {
        VStack(spacing: 4) {
            Text(glyph)
                .font(.system(size: 38, weight: .medium, design: .monospaced))
                .italic()
                .foregroundColor(t.accent.opacity(0.55))
                .padding(.bottom, 10)
            Text(title)
                .font(FT.sans(15, weight: .semibold))
                .foregroundColor(t.text2)
            Text(hint)
                .font(FT.sans(12))
                .foregroundColor(t.text3)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
                .padding(.horizontal, 24)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – IMU Chart (SwiftUI Canvas)
// ─────────────────────────────────────────────────────────────────────────────

struct IMUChart: View {
    @Environment(\.ft) var t
    @ObservedObject var store = IMUDataStore.shared
    var active: Bool
    var height: CGFloat = 96

    var body: some View {
        VStack(spacing: 0) {
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
            .padding(.vertical, 8)

            ZStack {
                Canvas { ctx, size in
                    let W = size.width, H = size.height
                    let MAX = 120

                    ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(t.bg))

                    for i in 1...3 {
                        let y = H * CGFloat(i) / 4
                        var p = Path(); p.move(to: CGPoint(x: 0, y: y))
                        p.addLine(to: CGPoint(x: W, y: y))
                        ctx.stroke(p, with: .color(t.border), lineWidth: 0.5)
                    }
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
                }

                if !active {
                    Text("⏸  waiting for session")
                        .font(FT.mono(10))
                        .foregroundColor(t.text3.opacity(0.65))
                }
            }
            .frame(height: height)
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
// MARK: – Connectivity console
// ─────────────────────────────────────────────────────────────────────────────

struct FTNetworkNode: View {
    @Environment(\.ft) var t
    let title: String
    let subtitle: String
    let icon: String
    let ok: Bool
    let warn: Bool

    private var color: Color {
        ok ? t.green : (warn ? t.yellow : t.red)
    }

    var body: some View {
        VStack(spacing: 7) {
            ZStack {
                Circle().fill(t.surface2).frame(width: 42, height: 42)
                    .overlay(Circle().stroke(color.opacity(0.55), lineWidth: 1.5))
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(color)
            }
            Text(title)
                .font(FT.sans(11, weight: .semibold))
                .foregroundColor(t.text)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Text(subtitle)
                .font(FT.mono(9))
                .foregroundColor(t.text3)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
    }
}

struct FTNetworkLink: View {
    @Environment(\.ft) var t
    let ok: Bool
    let label: String
    @State private var phase = false

    var body: some View {
        VStack(spacing: 4) {
            Capsule()
                .fill(ok ? t.green.opacity(0.24) : t.border2)
                .frame(height: 4)
                .overlay(alignment: phase ? .trailing : .leading) {
                    if ok {
                        Circle()
                            .fill(t.green)
                            .frame(width: 8, height: 8)
                            .shadow(color: t.green.opacity(0.45), radius: 4)
                    }
                }
                .onAppear {
                    withAnimation(.easeInOut(duration: 1.15).repeatForever(autoreverses: true)) {
                        phase.toggle()
                    }
                }
            Text(label)
                .font(FT.mono(8, weight: .medium))
                .kerning(0.4)
                .foregroundColor(ok ? t.green : t.text3)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(width: 52)
    }
}

struct FTDiagRow: View {
    @Environment(\.ft) var t
    let label: String
    let value: String
    let ok: Bool
    var warn: Bool = false

    private var color: Color {
        ok ? t.green : (warn ? t.yellow : t.red)
    }

    var body: some View {
        HStack(spacing: 8) {
            FTDot(color: color, pulse: ok, size: 6)
            Text(label).font(FT.sans(11)).foregroundColor(t.text2)
            Spacer(minLength: 8)
            Text(value)
                .font(FT.mono(10, weight: .medium))
                .foregroundColor(color)
                .lineLimit(2)
                .multilineTextAlignment(.trailing)
                .minimumScaleFactor(0.75)
        }
        .padding(.vertical, 6)
        .overlay(alignment: .bottom) {
            Rectangle().fill(t.border.opacity(0.55)).frame(height: 1)
        }
    }
}

struct FTConnectivityConsole: View {
    @Environment(\.ft) var t
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var airpods = AirPodsMotionManager.shared
    @AppStorage("ft_showConnectivityDetails") private var showDetails = true
    @State private var confirmClearSpill = false
    var compact = false

    private var serverOk: Bool { server.isConnected }
    private var phoneOk: Bool { bridge.isConnected }
    private var phonePaired: Bool { bridge.isBridgeCapable }
    private var watchPollOk: Bool { server.watchPolling }
    private var uploadOk: Bool { bridge.failedUploadCount == 0 && bridge.lastError.isEmpty }
    private var streamOk: Bool { server.watchRunning || bridge.receivedSampleCount > 0 }
    private var airpodsOk: Bool { airpods.isHeadphonesConnected }

    private var pollAgeText: String {
        guard let age = server.watchPollAgeMs else { return "no poll" }
        return age < 1000 ? "\(age) ms" : String(format: "%.1f s", Double(age) / 1000.0)
    }

    var body: some View {
        FTCard {
            FTCardHeader(title: "Connectivity",
                         subtitle: overallOk ? nil : "needs attention",
                         trailing: AnyView(
                FTPill(label: overallOk ? "Live" : "Check",
                       tone: overallOk ? .ok : .err,
                       pulse: overallOk)
            ))

            HStack(spacing: 0) {
                FTNetworkNode(title: "Website", subtitle: serverOk ? "WS online" : "WS down",
                              icon: "display", ok: serverOk, warn: false)
                FTNetworkLink(ok: serverOk, label: "ws")
                FTNetworkNode(title: "iPhone",
                              subtitle: phoneOk ? "reachable" : (phonePaired ? "paired · offline" : "not paired"),
                              icon: "iphone", ok: phoneOk, warn: phonePaired && !phoneOk)
                FTNetworkLink(ok: phoneOk && watchPollOk, label: "poll")
                FTNetworkNode(title: "Watch", subtitle: watchPollOk ? pollAgeText : "no poll",
                              icon: "applewatch", ok: watchPollOk, warn: phoneOk)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 14)
            .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }

            if showDetails || !compact {
                VStack(spacing: 0) {
                    FTDiagRow(label: "Server WebSocket",
                              value: serverOk ? "connected" : "not connected",
                              ok: serverOk)
                    FTDiagRow(label: "Watch reachable",
                              value: phoneOk ? "reachable (WCSession live)"
                                  : (phonePaired ? "paired · not reachable (4 s grace)" : "not paired / app missing"),
                              ok: phoneOk,
                              warn: phonePaired && !phoneOk)
                    FTDiagRow(label: "Watch command poll",
                              value: watchPollOk ? "\(pollAgeText) ago" : "no command_poll received",
                              ok: watchPollOk,
                              warn: phoneOk)
                    FTDiagRow(label: "Watch state",
                              value: server.watchRunning ? "running · \(server.watchSessionId)" : "idle",
                              ok: server.watchRunning || server.currentSessionId == nil,
                              warn: server.currentSessionId != nil)
                    FTDiagRow(label: "Samples",
                              value: "\(server.watchSampleCount) watch · \(bridge.uploadedSampleCount) uploaded",
                              ok: streamOk || server.currentSessionId == nil,
                              warn: server.currentSessionId != nil)
                    FTDiagRow(label: "Upload queue",
                              value: "\(bridge.queuedBatchCount) queued · \(bridge.failedUploadCount) failed",
                              ok: uploadOk,
                              warn: bridge.queuedBatchCount > 0)
                    if bridge.droppedBatchCount > 0 {
                        FTDiagRow(label: "Dropped (queue cap)",
                                  value: "\(bridge.droppedBatchCount) batches",
                                  ok: false, warn: true)
                    }
                    if !server.lastWatchCommandStatus.isEmpty {
                        FTDiagRow(label: "Last command",
                                  value: server.lastWatchCommandStatus,
                                  ok: server.lastWatchCommandStatus.contains("confirmed") ||
                                      server.lastWatchCommandStatus.contains("acknowledged"),
                                  warn: server.lastWatchCommandStatus.contains("waiting"))
                    }
                    if let commandId = server.currentCommandId, !commandId.isEmpty {
                        FTDiagRow(label: "Expected command ID",
                                  value: commandId,
                                  ok: server.watchLastCommandId == commandId,
                                  warn: server.watchLastCommandId != commandId)
                    }
                    if !server.watchLastCommandId.isEmpty {
                        FTDiagRow(label: "Watch confirmed ID",
                                  value: server.watchLastCommandId,
                                  ok: server.currentCommandId == nil || server.watchLastCommandId == server.currentCommandId)
                    }
                    if !bridge.lastError.isEmpty {
                        FTDiagRow(label: "Last error",
                                  value: bridge.lastError,
                                  ok: false)
                    }
                    FTDiagRow(label: "AirPods motion",
                              value: !airpods.isAvailable ? "unavailable on this device"
                                  : (airpods.isHeadphonesConnected
                                     ? (airpods.isStreaming ? "streaming · \(airpods.sampleCount) samples"
                                                            : "paired · idle")
                                     : (airpods.isStreaming ? "listening · waiting for AirPods"
                                                            : "not paired")),
                              ok: airpods.isHeadphonesConnected,
                              warn: airpods.isStreaming && !airpods.isHeadphonesConnected)
                    if airpods.queuedBatchCount > 0 || airpods.failedUploadCount > 0 {
                        FTDiagRow(label: "AirPods upload",
                                  value: "\(airpods.queuedBatchCount) queued · \(airpods.failedUploadCount) failed · \(airpods.uploadedCount) uploaded",
                                  ok: airpods.failedUploadCount == 0,
                                  warn: airpods.queuedBatchCount > 0)
                    }
                    if !airpods.lastError.isEmpty {
                        FTDiagRow(label: "AirPods error",
                                  value: airpods.lastError,
                                  ok: false)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
            }

            if !compact {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        FTSLabel(text: "Repair actions")
                        Spacer()
                        Toggle("Details", isOn: $showDetails)
                            .font(FT.sans(11))
                            .foregroundColor(t.text2)
                            .tint(t.green)
                            .onChange(of: showDetails) { _ in FTHaptics.light() }
                    }
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                        repairButton("Reconnect server", icon: "arrow.triangle.2.circlepath") {
                            FTHaptics.light(); server.reconnectAndRefresh()
                        }
                        repairButton("Reactivate bridge", icon: "applewatch.radiowaves.left.and.right") {
                            FTHaptics.light(); bridge.reactivateSession()
                        }
                        repairButton("Resync watch", icon: "arrow.up.arrow.down") {
                            FTHaptics.light(); bridge.resyncWatchContext()
                        }
                        repairButton("Retry uploads", icon: "tray.and.arrow.up") {
                            FTHaptics.light(); bridge.retryUploadQueue()
                        }
                        repairButton("Clear errors", icon: "xmark.circle") {
                            FTHaptics.light(); bridge.clearDiagnostics()
                        }
                        repairButton("Send buffered data", icon: "tray.and.arrow.up.fill") {
                            FTHaptics.light(); server.drainWatchSpill()
                        }
                        repairButton("Discard buffer", icon: "trash") {
                            FTHaptics.warning(); confirmClearSpill = true
                        }
                    }
                }
                .padding(14)
            }
        }
        .alert("Discard buffer?", isPresented: $confirmClearSpill) {
            Button("Discard", role: .destructive) {
                FTHaptics.light(); server.clearWatchSpill()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Permanently deletes the buffered measurement backlog on the watch. "
                 + "The watch ignores this command during an active recording.")
        }
    }

    private func repairButton(_ title: String,
                              icon: String,
                              action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                Text(title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            .font(FT.sans(11, weight: .semibold))
            .foregroundColor(t.accent)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 8)
            .padding(.vertical, 9)
            .background(t.accentDim)
            .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
            .overlay(RoundedRectangle(cornerRadius: FTRadius.sm)
                .stroke(t.accent.opacity(0.22), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private var overallOk: Bool {
        serverOk && phoneOk && (watchPollOk || server.currentSessionId == nil)
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
                FTDot(color: t.green, pulse: true, size: 6)
            ))

            VStack(spacing: 0) {
                if store.entries.isEmpty {
                    FTEmptyState(glyph: "{ }",
                                 title: "No events yet",
                                 hint:  "Connect to the server, start a session, or trigger a repair action — events stream here in real time.")
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
                                .cornerRadius(FTRadius.xs)
                            Text(entry.message)
                                .font(FT.mono(10)).foregroundColor(t.text2)
                                .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.horizontal, 12).padding(.vertical, 5)
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
        .background(t.red.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
        .overlay(RoundedRectangle(cornerRadius: FTRadius.md)
            .stroke(t.red.opacity(0.2), lineWidth: 1))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Phase 3 — Session quality models
// ─────────────────────────────────────────────────────────────────────────────

struct SessionQualityRow: Decodable, Identifiable {
    let session_id: String
    let person_id: String?
    let status: String?
    let duration_seconds: Double?
    let watch: WatchBlock?
    let ml_readiness: ScoreBlock?
    let recording_health: ScoreBlock?

    var id: String { session_id }
    var personOrAnon: String {
        if let p = person_id, !p.isEmpty { return p }
        return "Anonymous"
    }

    struct WatchBlock: Decodable {
        let rows: Int?
        let estimated_hz: Double?
    }
    struct ScoreBlock: Decodable {
        let status: String?
        let score: Double?
    }
}

struct SessionsQualityResponse: Decodable {
    let sessions: [SessionQualityRow]
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Phase 3 — Sessions history store
// ─────────────────────────────────────────────────────────────────────────────

@MainActor
final class SessionsHistoryStore: ObservableObject {
    static let shared = SessionsHistoryStore()

    @Published private(set) var sessions: [SessionQualityRow] = []
    @Published private(set) var isLoading = false
    @Published private(set) var lastError: String?
    @Published private(set) var lastFetched: Date?

    private var inflightTask: Task<Void, Never>?

    func refresh(force: Bool = false) {
        if !force, let last = lastFetched, Date().timeIntervalSince(last) < 10 {
            return
        }
        inflightTask?.cancel()
        inflightTask = Task { [weak self] in
            await self?.performFetch()
        }
    }

    private func performFetch() async {
        isLoading = true
        defer { isLoading = false }

        guard let url = URL(string: PhoneBridge.serverBaseURL + "/sessions/quality") else {
            lastError = "Invalid server URL"
            return
        }
        do {
            var req = URLRequest(url: url)
            req.timeoutInterval = 8
            let (data, response) = try await URLSession.shared.data(for: req)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                lastError = "HTTP \(http.statusCode)"
                return
            }
            let decoded = try JSONDecoder().decode(SessionsQualityResponse.self, from: data)
            self.sessions = decoded.sessions
            self.lastError = nil
            self.lastFetched = Date()
        } catch is CancellationError {
            // ok
        } catch {
            lastError = error.localizedDescription
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Phase 3 — Live quality store
// ─────────────────────────────────────────────────────────────────────────────

@MainActor
final class LiveQualityStore: ObservableObject {
    static let shared = LiveQualityStore()

    @Published private(set) var driftMs: Double?
    @Published private(set) var watchHz: Double?
    @Published private(set) var coveragePct: Double?
    @Published private(set) var watchRows: Int?
    @Published private(set) var lastError: String?
    @Published private(set) var lastUpdated: Date?

    private var pollTask: Task<Void, Never>?
    private var currentSessionId: String?

    func startPolling(sessionId: String) {
        guard currentSessionId != sessionId else { return }
        stopPolling()
        currentSessionId = sessionId

        pollTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            while !Task.isCancelled {
                await self?.fetchOnce(sessionId: sessionId)
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
        currentSessionId = nil
        driftMs = nil
        watchHz = nil
        coveragePct = nil
        watchRows = nil
        lastError = nil
        lastUpdated = nil
    }

    private func fetchOnce(sessionId: String) async {
        guard let url = URL(string: PhoneBridge.serverBaseURL + "/sessions/\(sessionId)/validation") else {
            return
        }
        do {
            var req = URLRequest(url: url)
            req.timeoutInterval = 6
            let (data, response) = try await URLSession.shared.data(for: req)
            let httpStatus = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(httpStatus),
                  let parsed = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            else {
                self.lastError = "validation HTTP \(httpStatus)"
                return
            }

            // Defensive Extraktion über Helfer — hält die Optional-Chains
            // einfach genug, dass SourceKit nicht aussteigt.
            self.driftMs     = Self.doubleAt(parsed, "drift", "estimated_ms")
            self.watchHz     = Self.doubleAt(parsed, "watch", "estimated_hz")
            self.watchRows   = Self.intAt(parsed,    "watch", "rows")
            self.coveragePct = Self.doubleAt(parsed, "coverage", "percent")
            self.lastError   = nil
            self.lastUpdated = Date()
        } catch is CancellationError {
            // ok
        } catch {
            self.lastError = error.localizedDescription
        }
    }

    private static func doubleAt(_ root: [String: Any], _ k1: String, _ k2: String) -> Double? {
        let inner = root[k1] as? [String: Any]
        return inner?[k2] as? Double
    }
    private static func intAt(_ root: [String: Any], _ k1: String, _ k2: String) -> Int? {
        let inner = root[k1] as? [String: Any]
        return inner?[k2] as? Int
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Phase 3 — Sessions history card
// ─────────────────────────────────────────────────────────────────────────────

struct FTSessionsHistoryCard: View {
    @Environment(\.ft) var t
    @ObservedObject private var store = SessionsHistoryStore.shared
    var maxRows = 5

    var body: some View {
        FTCard {
            FTCardHeader(title: "Recent sessions", trailing: AnyView(
                HStack(spacing: 8) {
                    if store.isLoading {
                        ProgressView().scaleEffect(0.7)
                    } else if let last = store.lastFetched {
                        Text(timeAgo(last))
                            .font(FT.mono(9)).foregroundColor(t.text3)
                    }
                    Button(action: {
                        FTHaptics.light()
                        store.refresh(force: true)
                    }) {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(t.accent)
                            .padding(5)
                            .background(t.accentDim)
                            .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
                    }
                    .buttonStyle(.plain)
                }
            ))

            if let err = store.lastError, store.sessions.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Could not load sessions")
                        .font(FT.sans(12, weight: .semibold)).foregroundColor(t.red)
                    Text(err).font(FT.mono(10)).foregroundColor(t.text3)
                        .lineLimit(2)
                }
                .padding(14).frame(maxWidth: .infinity, alignment: .leading)
            } else if store.sessions.isEmpty {
                if store.isLoading {
                    Text("Loading…").font(FT.sans(12)).italic().foregroundColor(t.text3)
                        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    FTEmptyState(glyph: "//",
                                 title: "No sessions yet",
                                 hint:  "Start a session from the browser dashboard. After it ends, it'll show up here with quality info.")
                }
            } else {
                VStack(spacing: 0) {
                    let visible = Array(store.sessions.prefix(maxRows))
                    ForEach(visible) { row in
                        FTSessionHistoryRow(row: row)
                            .overlay(alignment: .bottom) {
                                if row.id != visible.last?.id {
                                    Rectangle().fill(t.border).frame(height: 1)
                                }
                            }
                    }
                }
            }
        }
        .onAppear { store.refresh() }
    }

    private func timeAgo(_ date: Date) -> String {
        let s = Int(Date().timeIntervalSince(date))
        if s < 60   { return "\(s)s ago" }
        if s < 3600 { return "\(s/60)m ago" }
        return "\(s/3600)h ago"
    }
}

struct FTSessionHistoryRow: View {
    @Environment(\.ft) var t
    let row: SessionQualityRow

    private var mlTone: Color {
        switch row.ml_readiness?.status ?? "" {
        case "ok":   return t.green
        case "warn": return t.yellow
        case "bad":  return t.red
        default:     return t.text3
        }
    }

    private var samplesText: String {
        guard let n = row.watch?.rows else { return "—" }
        if n >= 10_000 { return String(format: "%.1fk", Double(n)/1000) }
        return "\(n)"
    }

    private var hzText: String {
        guard let hz = row.watch?.estimated_hz, hz > 1 else { return "—" }
        return "\(Int(hz.rounded())) Hz"
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Rectangle().fill(mlTone).frame(width: 3)

            VStack(alignment: .leading, spacing: 3) {
                Text(row.personOrAnon)
                    .font(FT.sans(13, weight: .semibold))
                    .foregroundColor(t.text)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text(row.session_id).font(FT.mono(10)).foregroundColor(t.text3)
                    if let dur = row.duration_seconds, dur > 0 {
                        Text("·").foregroundColor(t.text3)
                        Text(formatDuration(dur))
                            .font(FT.mono(10)).foregroundColor(t.text3)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            VStack(alignment: .trailing, spacing: 3) {
                Text(samplesText)
                    .font(FT.mono(11, weight: .semibold)).foregroundColor(t.text)
                Text(hzText).font(FT.mono(9)).foregroundColor(t.text3)
            }
            .frame(width: 56, alignment: .trailing)

            FTPill(label: row.ml_readiness?.status ?? "?",
                   tone: pillTone)
        }
        .padding(.vertical, 10)
        .padding(.trailing, 12)
    }

    private var pillTone: FTPill.Tone {
        switch row.ml_readiness?.status ?? "" {
        case "ok":   return .ok
        case "warn": return .warn
        case "bad":  return .err
        default:     return .neutral
        }
    }

    private func formatDuration(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        if s < 60 { return "\(s)s" }
        return "\(s/60)m \(String(format: "%02d", s%60))s"
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Phase 3 — Live quality card
// ─────────────────────────────────────────────────────────────────────────────

struct FTLiveQualityCard: View {
    @Environment(\.ft) var t
    @ObservedObject private var live = LiveQualityStore.shared

    private var hasData: Bool {
        live.driftMs != nil || live.watchHz != nil || live.coveragePct != nil
    }

    var body: some View {
        FTCard(accent: hasData) {
            FTCardHeader(title: "Live quality", trailing: AnyView(
                Group {
                    if hasData {
                        FTPill(label: "live", tone: .ok, pulse: true)
                    } else if live.lastError != nil {
                        FTPill(label: "n/a", tone: .err)
                    } else {
                        Text("warming up")
                            .font(FT.mono(10)).italic().foregroundColor(t.text3)
                    }
                }
            ))

            HStack(spacing: 0) {
                qualityCell("Drift", driftText, color: driftColor)
                Rectangle().fill(t.border).frame(width: 1)
                qualityCell("Hz", hzText, color: hzColor)
                Rectangle().fill(t.border).frame(width: 1)
                qualityCell("Coverage", coverageText, color: coverageColor)
            }

            if let err = live.lastError {
                Text(err).font(FT.mono(9)).foregroundColor(t.text3)
                    .padding(.horizontal, 14).padding(.bottom, 8)
                    .lineLimit(1)
            } else if let last = live.lastUpdated {
                Text("updated \(secondsAgo(last)) ago · poll every 5 s")
                    .font(FT.mono(9)).foregroundColor(t.text3)
                    .padding(.horizontal, 14).padding(.bottom, 8)
            }
        }
    }

    @ViewBuilder
    private func qualityCell(_ label: String, _ value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            FTSLabel(text: label)
            Text(value)
                .font(FT.mono(15, weight: .semibold))
                .foregroundColor(color)
                .monospacedDigit()
                .lineLimit(1).minimumScaleFactor(0.7)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var driftText: String {
        guard let d = live.driftMs else { return "—" }
        return abs(d) < 1000 ? "\(Int(d.rounded())) ms" : String(format: "%.1f s", d/1000)
    }
    private var driftColor: Color {
        guard let d = live.driftMs.map({ abs($0) }) else { return t.text3 }
        return d < 50 ? t.green : (d < 200 ? t.yellow : t.red)
    }

    private var hzText: String {
        guard let hz = live.watchHz, hz > 1 else { return "—" }
        return "\(Int(hz.rounded()))"
    }
    private var hzColor: Color {
        guard let hz = live.watchHz else { return t.text3 }
        return (hz >= 40 && hz <= 60) ? t.green : t.yellow
    }

    private var coverageText: String {
        guard let c = live.coveragePct else { return "—" }
        return "\(Int(c.rounded()))%"
    }
    private var coverageColor: Color {
        guard let c = live.coveragePct else { return t.text3 }
        return c >= 95 ? t.green : (c >= 80 ? t.yellow : t.red)
    }

    private func secondsAgo(_ date: Date) -> String {
        let s = Int(Date().timeIntervalSince(date))
        return "\(s)s"
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Recording health
// ─────────────────────────────────────────────────────────────────────────────

/// Recording-health banner: separates "the link is up" from "data is actually
/// flowing". Green only when the watch is polling AND uploads are advancing — the
/// state a session leader needs to trust the recording at a glance.
struct FTRecordingHealth: View {
    @Environment(\.ft) var t
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var health = RecordingHealthStore.shared

    private enum Health: Equatable { case idle, healthy, warning, error }

    private var hasSession: Bool { server.currentSessionId != nil }
    private var pollFresh:  Bool { server.watchPolling }
    private var dataFlowing: Bool { health.dataFlowing }
    private var wsUp: Bool { server.isConnected }

    private var state: Health {
        guard hasSession else { return .idle }
        if dataFlowing && pollFresh { return .healthy }
        if !dataFlowing && !pollFresh && !wsUp { return .error }
        return .warning
    }

    private var color: Color {
        switch state {
        case .idle:    return t.text3
        case .healthy: return t.green
        case .warning: return t.yellow
        case .error:   return t.red
        }
    }

    private var title: String {
        switch state {
        case .idle:    return "Ready"
        case .healthy: return "Recording healthy"
        case .warning: return "Needs attention"
        case .error:   return "Recording stalled"
        }
    }

    private var reason: String {
        switch state {
        case .idle:    return "No active session — start one from the dashboard"
        case .healthy: return "Data reaching server · watch polling"
        case .warning:
            if !dataFlowing { return "No data reaching server" }
            if !pollFresh   { return "Watch not polling" }
            return "Link up — waiting for data"
        case .error:    return "No data, watch not polling, command channel down"
        }
    }

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle().fill(color.opacity(0.16)).frame(width: 46, height: 46)
                FTDot(color: color, pulse: state == .healthy, size: 18)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(FT.sans(16, weight: .bold))
                    .foregroundColor(t.text)
                Text(reason)
                    .font(FT.mono(11))
                    .foregroundColor(t.text2)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 5) {
                miniFlag("WS", ok: wsUp)
                miniFlag("DATA", ok: dataFlowing)
                miniFlag("WATCH", ok: pollFresh)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity)
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
        .overlay(RoundedRectangle(cornerRadius: FTRadius.md)
            .stroke(color.opacity(0.32), lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Recording health: \(title). \(reason)")
    }

    private func miniFlag(_ label: String, ok: Bool) -> some View {
        HStack(spacing: 4) {
            Text(label)
                .font(FT.mono(8, weight: .semibold))
                .kerning(0.4)
                .foregroundColor(t.text3)
            FTDot(color: ok ? t.green : t.text3.opacity(0.5), size: 5)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 1: Dashboard
// ─────────────────────────────────────────────────────────────────────────────

struct DashboardTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var bridge  = PhoneBridge.shared
    @ObservedObject private var server  = ServerCommandListener.shared

    private var hasSession: Bool { server.currentSessionId != nil }
    private var received: Int { bridge.receivedSampleCount }
    private var uploaded: Int { bridge.uploadedSampleCount }
    private var queued:   Int { bridge.queuedBatchCount }
    private var failed:   Int { bridge.failedUploadCount }
    private var pct: Double {
        received > 0 ? min(1, Double(uploaded) / Double(received)) : 0
    }

    private var hzString: String {
        guard hasSession else { return "—" }
        let hz = server.watchActualHz
        return hz > 1 ? "\(Int(hz.rounded()))" : "•"
    }

    var body: some View {
        ScrollView {
            VStack(spacing: FTSpace.stack) {

                // ── HERO: IMU live chart + chart-stats ──────────────────────
                FTRecordingHealth()

                FTHeroCard(live: hasSession) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("Live recording")
                            .font(FT.sans(13, weight: .semibold))
                            .textCase(.uppercase).kerning(0.5)
                            .foregroundColor(t.text2)
                        if hasSession { FTLiveIndicator() }
                        Spacer()
                        FTPill(label: hasSession ? "Streaming" : "Idle",
                               tone: hasSession ? .ok : .neutral,
                               pulse: hasSession)
                    }
                    .padding(.horizontal, FTSpace.heroPad)
                    .padding(.top, 18).padding(.bottom, 4)

                    IMUChart(active: hasSession, height: 110)
                        .padding(.horizontal, 4)

                    HStack(spacing: 10) {
                        FTStatBox(label: "Received", value: received.formatted())
                        FTStatBox(label: "Uploaded", value: uploaded.formatted(),
                                  color: uploaded > 0 ? t.green : nil)
                        FTStatBox(label: "Hz", value: hzString,
                                  color: hasSession ? t.accent : nil)
                    }
                    .padding(.horizontal, FTSpace.heroPad)
                    .padding(.vertical, 16)
                }

                // ── Session pill row ────────────────────────────────────────
                sessionPillRow

                // ── Connectivity console ───────────────────────────────────
                FTConnectivityConsole(compact: true)

                // ── Sessions history (Phase 3) ──────────────────────────────
                FTSessionsHistoryCard(maxRows: 5)

                // ── Upload pipeline ─────────────────────────────────────────
                FTCard {
                    FTCardHeader(title: "Upload pipeline",
                                 trailing: AnyView(
                        FTPill(label: "\(Int(pct * 100))%",
                               tone: pct > 0.95 ? .ok : (pct > 0 ? .warn : .neutral),
                               pulse: pct > 0)
                    ))
                    HStack(spacing: 0) {
                        FTStatCell(label: "Queued", value: "\(queued)",
                                   color: queued > 0 ? t.yellow : t.text3)
                        Rectangle().fill(t.border).frame(width: 1)
                        FTStatCell(label: "Failed", value: "\(failed)",
                                   color: failed > 0 ? t.red : t.text3)
                        Rectangle().fill(t.border).frame(width: 1)
                        FTStatCell(label: "Dropped", value: "\(bridge.droppedBatchCount)",
                                   color: bridge.droppedBatchCount > 0 ? t.red : t.text3)
                    }
                    .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }

                    VStack(spacing: 6) {
                        HStack {
                            Text("Throughput").font(FT.mono(10)).foregroundColor(t.text3)
                            Spacer()
                            Text("\(uploaded.formatted()) of \(received.formatted())")
                                .font(FT.mono(10)).foregroundColor(t.text3)
                        }
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(t.border).frame(height: 4)
                                Capsule()
                                    .fill(pct > 0 ? t.green : t.text3)
                                    .frame(width: geo.size.width * pct, height: 4)
                                    .animation(.easeInOut(duration: 0.6), value: pct)
                            }
                        }.frame(height: 4)
                    }
                    .padding(.horizontal, FTSpace.cardPad).padding(.vertical, 12)
                }

                // ── Last command ────────────────────────────────────────────
                lastCommandRow

                // ── Error banner ────────────────────────────────────────────
                if !bridge.lastError.isEmpty {
                    FTErrorBanner(message: bridge.lastError)
                }

                footer
            }
            .padding(.horizontal, FTSpace.pageH).padding(.vertical, FTSpace.pageV)
        }
        .background(t.bg)
        .onAppear {
            if hasSession { IMUDataStore.shared.startStreaming() }
        }
        .onReceive(server.$currentSessionId) { sid in
            if sid != nil { IMUDataStore.shared.startStreaming() }
            else          { IMUDataStore.shared.stopStreaming()  }
        }
    }

    private var sessionPillRow: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    FTDot(color: hasSession ? t.green : t.text3, pulse: hasSession, size: 7)
                    Text(hasSession ? "Session active" : "No session")
                        .font(FT.mono(10, weight: .bold))
                        .textCase(.uppercase).kerning(0.6)
                        .foregroundColor(hasSession ? t.green : t.text3)
                }
                if let sid = server.currentSessionId {
                    HStack(spacing: 5) {
                        Text(sid).font(FT.mono(12)).foregroundColor(t.text)
                        if let pid = server.currentPersonId {
                            Text("·").foregroundColor(t.text3)
                            Text(pid).font(FT.mono(12, weight: .semibold))
                                .foregroundColor(t.accent)
                        }
                    }
                    .lineLimit(1)
                } else {
                    Text("Start sessions from the browser dashboard")
                        .font(FT.sans(12)).italic().foregroundColor(t.text3)
                }
            }
            Spacer()
        }
        .padding(.horizontal, 14).padding(.vertical, 11)
        .background(hasSession ? t.greenDim : t.surface)
        .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
        .overlay(RoundedRectangle(cornerRadius: FTRadius.md)
            .stroke(hasSession ? t.green.opacity(0.28) : t.border, lineWidth: 1))
    }

    private var lastCommandRow: some View {
        let cmd = server.lastWatchCommandStatus
        let tone: Color = cmd.contains("acknowledged") || cmd.contains("confirmed") ? t.green :
                          cmd.contains("waiting")      ? t.yellow :
                          cmd == "No command sent"      ? t.text3 : t.red
        return HStack(spacing: 8) {
            Text("Last cmd").font(FT.sans(10, weight: .semibold))
                .textCase(.uppercase).kerning(0.6).foregroundColor(t.text3)
                .fixedSize()
            Text(cmd).font(FT.mono(11))
                .foregroundColor(tone)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(t.surface)
        .clipShape(RoundedRectangle(cornerRadius: FTRadius.md))
        .overlay(RoundedRectangle(cornerRadius: FTRadius.md).stroke(t.border, lineWidth: 1))
    }

    private var footer: some View {
        HStack {
            Text("WatchStreamer · PhoneBridge")
            Spacer()
            Text("v1.1")
        }
        .font(FT.mono(9)).foregroundColor(t.text3).padding(.top, 4)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 2: Session
// ─────────────────────────────────────────────────────────────────────────────

struct SessionTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @State private var elapsed: Int    = 0
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var hasSession: Bool { server.currentSessionId != nil }
    private var hzString: String {
        guard hasSession else { return "—" }
        let hz = server.watchActualHz
        return hz > 1 ? "\(Int(hz.rounded()))" : "•"
    }

    var body: some View {
        ScrollView {
            VStack(spacing: FTSpace.stack) {

                // ── HERO session card ──────────────────────────────────────
                FTHeroCard(live: hasSession) {
                    if hasSession, let sid = server.currentSessionId {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                FTLiveIndicator()
                                Spacer()
                                FTPill(label: "Streaming", tone: .ok, pulse: true)
                            }

                            VStack(alignment: .leading, spacing: 2) {
                                Text(server.currentPersonId ?? "Anonymous")
                                    .font(FT.sans(22, weight: .bold))
                                    .kerning(-0.4)
                                    .foregroundColor(server.currentPersonId == nil
                                                     ? t.text2 : t.text)
                                    .ftItalic(server.currentPersonId == nil)
                                Text(sid)
                                    .font(FT.mono(11, weight: .medium))
                                    .kerning(0.4)
                                    .foregroundColor(t.text3)
                            }

                            HStack(alignment: .firstTextBaseline, spacing: 4) {
                                Text(String(format: "%02d:%02d", elapsed/60, elapsed%60))
                                    .font(FT.mono(34, weight: .semibold))
                                    .kerning(1.2)
                                    .foregroundColor(t.text)
                                    .monospacedDigit()
                                    .ftNumericTransition()
                                Text("ELAPSED")
                                    .font(FT.mono(9, weight: .semibold))
                                    .kerning(0.6)
                                    .foregroundColor(t.text3)
                                    .padding(.leading, 8)
                            }
                        }
                        .padding(FTSpace.heroPad)
                    } else {
                        FTEmptyState(glyph: "/",
                                     title: "No active session",
                                     hint:  "Start a session from the browser dashboard. The watch begins streaming IMU data and stats appear here live.")
                    }
                }

                // ── 2x2 Hero stat grid ──────────────────────────────────────
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 10),
                                    GridItem(.flexible(), spacing: 10)],
                          spacing: 10) {
                    FTStatBox(label: "Received",
                              value: bridge.receivedSampleCount.formatted())
                    FTStatBox(label: "Uploaded",
                              value: bridge.uploadedSampleCount.formatted(),
                              color: bridge.uploadedSampleCount > 0 ? t.green : nil)
                    FTStatBox(label: "Sample rate",
                              value: hasSession ? "\(hzString) Hz" : "— Hz",
                              color: hasSession ? t.accent : nil)
                    FTStatBox(label: "Pipeline",
                              value: "\(bridge.queuedBatchCount)Q · \(bridge.failedUploadCount)F",
                              color: bridge.failedUploadCount > 0 ? t.red
                                  : bridge.queuedBatchCount > 0 ? t.yellow : nil,
                              size: 20)
                }

                // ── IMU chart ───────────────────────────────────────────────
                FTCard {
                    IMUChart(active: hasSession, height: 110)
                }

                // ── Live quality (Phase 3) ──────────────────────────────────
                if hasSession {
                    FTLiveQualityCard()
                }

                // ── Error banner ───────────────────────────────────────────
                if !bridge.lastError.isEmpty {
                    FTErrorBanner(message: bridge.lastError)
                }

                // ── System log ──────────────────────────────────────────────
                FTLogCard(maxEntries: 8)

                footer
            }
            .padding(.horizontal, FTSpace.pageH).padding(.vertical, FTSpace.pageV)
        }
        .background(t.bg)
        .onReceive(timer) { _ in if hasSession { elapsed += 1 } }
        .onChange(of: server.currentSessionId) { sid in if sid == nil { elapsed = 0 } }
    }

    private var footer: some View {
        HStack {
            Text("WatchStreamer · PhoneBridge")
            Spacer(); Text("v1.1")
        }
        .font(FT.mono(9)).foregroundColor(t.text3).padding(.top, 4)
    }
}

private extension Text {
    /// Kondicional-italic (eigener Name, um nicht mit SwiftUI's iOS 16
    /// `italic(_ isActive:)` zu kollidieren).
    func ftItalic(_ on: Bool) -> Text {
        on ? self.italic() : self
    }

    /// numericText-Transition mit Pre-iOS-16 Fallback.
    @ViewBuilder
    func ftNumericTransition() -> some View {
        if #available(iOS 16.0, *) {
            self.contentTransition(.numericText(countsDown: false))
        } else {
            self
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – TAB 3: Settings
// ─────────────────────────────────────────────────────────────────────────────

struct SettingsTab: View {
    @Environment(\.ft) var t
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var health = RecordingHealthStore.shared
    @AppStorage("serverIP")     private var serverIP   = ServerConfig.defaultIP
    @AppStorage("ft_showStats") private var showStats  = true
    @AppStorage("ft_showLog")   private var showLog    = true
    // H3 — Motion-Config. Wird von ServerCommandListener.watchPayload aus
    // UserDefaults gelesen und über den 1-s-Watch-Poll an die Watch getragen.
    @AppStorage("requestedHz")  private var requestedHz = 50.0
    @AppStorage("batchSize")    private var batchSize   = 10
    @State private var editingIP = false
    @FocusState private var ipFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {

                sectionHeader("Network")
                FTCard {
                    VStack(alignment: .leading, spacing: 8) {
                        FTSLabel(text: "Server IP")
                        if editingIP {
                            HStack(spacing: 8) {
                                TextField("192.168.x.x", text: $serverIP)
                                    .font(FT.mono(14)).foregroundColor(t.text)
                                    .keyboardType(.numbersAndPunctuation)
                                    .autocorrectionDisabled()
                                    .textInputAutocapitalization(.never)
                                    .focused($ipFocused).onSubmit { save() }
                                    .padding(.horizontal, 10).padding(.vertical, 8)
                                    .background(t.surface2)
                                    .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
                                    .overlay(RoundedRectangle(cornerRadius: FTRadius.sm)
                                        .stroke(t.accent, lineWidth: 1.5))
                                Button("Save") {
                                    FTHaptics.success()
                                    save()
                                }
                                .font(FT.sans(13, weight: .semibold))
                                .foregroundColor(.white)
                                .padding(.horizontal, 14).padding(.vertical, 8)
                                .background(t.accent)
                                .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
                            }
                        } else {
                            HStack {
                                Text(serverIP).font(FT.mono(14)).foregroundColor(t.text)
                                Spacer()
                                Button("Edit") {
                                    FTHaptics.light()
                                    editingIP = true; ipFocused = true
                                }
                                .font(FT.sans(12, weight: .semibold))
                                .foregroundColor(t.accent)
                                .padding(.horizontal, 12).padding(.vertical, 6)
                                .background(t.accentDim)
                                .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
                                .overlay(RoundedRectangle(cornerRadius: FTRadius.sm)
                                    .stroke(t.accent.opacity(0.25), lineWidth: 1))
                            }
                        }
                    }
                    .padding(14)
                    .overlay(alignment: .bottom) { Rectangle().fill(t.border).frame(height: 1) }

                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Command channel").font(FT.sans(13, weight: .medium))
                                .foregroundColor(t.text)
                            HStack(spacing: 5) {
                                FTDot(color: server.isConnected ? t.green : t.red,
                                      pulse: server.isConnected, size: 6)
                                Text(server.isConnected ? "WebSocket connected" : "WebSocket disconnected")
                                    .font(FT.mono(10))
                                    .foregroundColor(server.isConnected ? t.green : t.red)
                            }
                            // Why: the WebSocket is only the command channel; watch
                            // data travels over a separate HTTP path. Surface both so
                            // a dead WS is never read as "the recording is dead".
                            HStack(spacing: 5) {
                                FTDot(color: health.dataFlowing ? t.green : t.text3,
                                      pulse: health.dataFlowing, size: 6)
                                Text("Data \(health.dataFlowing ? "flowing" : "idle") · \(bridge.uploadedSampleCount.formatted()) uploaded")
                                    .font(FT.mono(10))
                                    .foregroundColor(health.dataFlowing ? t.green : t.text3)
                            }
                        }
                        Spacer()
                        Button("Reconnect") {
                            FTHaptics.medium()
                            server.connect()
                        }
                        .font(FT.sans(12, weight: .semibold)).foregroundColor(.white)
                        .padding(.horizontal, 16).padding(.vertical, 8)
                        .background(t.accent)
                        .clipShape(RoundedRectangle(cornerRadius: FTRadius.sm))
                    }
                    .padding(.horizontal, 14).padding(.vertical, 12)
                }

                sectionHeader("Connectivity Console")
                FTConnectivityConsole(compact: false)

                sectionHeader("Display")
                FTCard {
                    toggleRow("Upload stats", sub: "Show sample counters on dashboard",
                              value: $showStats)
                    toggleRow("System log",   sub: "Show live event feed",
                              value: $showLog)
                }

                sectionHeader("Apple Watch")
                FTCard {
                    VStack(spacing: 0) {
                        deviceRow("Status",
                                  bridge.isConnected ? "Reachable"
                                      : (bridge.isBridgeCapable ? "Paired · offline" : "Not paired"),
                                  color: bridge.isConnected ? t.green
                                      : (bridge.isBridgeCapable ? t.yellow : t.red))
                        deviceRow("IMU rate",
                                  server.watchActualHz > 1 ? "\(Int(server.watchActualHz.rounded())) Hz (measured)"
                                      : "\(Int(requestedHz)) Hz (set)")
                        deviceRow("Batch size", "\(batchSize) samples")
                        deviceRow("Transport",  "WatchConnectivity")
                        deviceRow("Last data",  server.currentSessionId != nil ? "just now" : "—", isLast: true)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 6)
                }

                sectionHeader("Motion — Watch")
                FTCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            FTSLabel(text: "Sample rate")
                            Spacer()
                            Picker("", selection: $requestedHz) {
                                Text("50 Hz").tag(50.0)
                                Text("100 Hz").tag(100.0)
                            }
                            .pickerStyle(.segmented)
                            .frame(width: 150)
                        }
                        HStack {
                            FTSLabel(text: "Batch size")
                            Spacer()
                            // Range up to 80: covers the 100 Hz sweet spot (40)
                            // + tunnel reserve (50–60). The watch clamps to
                            // 1...200 anyway; >80 would only add monitor lag
                            // (N/Hz buffer time) without upload benefit.
                            Stepper("\(batchSize) samples",
                                    value: $batchSize, in: 5...80, step: 5)
                                .font(FT.mono(13)).foregroundColor(t.text)
                        }
                        Text("Applies from the next recording — the watch picks up the values over the 1 s poll. At 100 Hz: batch 40 recommended (keeps upload throughput; larger = more live-monitor lag).")
                            .font(FT.mono(9)).foregroundColor(t.text3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(14)
                }

                HStack {
                    Text("WatchStreamer · PhoneBridge")
                    Spacer(); Text("v1.1")
                }
                .font(FT.mono(9)).foregroundColor(t.text3)
                .padding(.horizontal, 4).padding(.top, 24)
            }
            .padding(.horizontal, FTSpace.pageH).padding(.vertical, FTSpace.pageV)
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
            .padding(.horizontal, 4).padding(.top, 22).padding(.bottom, 8)
    }

    @ViewBuilder
    private func toggleRow(_ label: String, sub: String, value: Binding<Bool>) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(FT.sans(14, weight: .medium)).foregroundColor(t.text)
                Text(sub).font(FT.sans(11)).foregroundColor(t.text3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Toggle("", isOn: value).labelsHidden()
                .tint(t.green)
                .onChange(of: value.wrappedValue) { _ in FTHaptics.light() }
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
        .padding(.vertical, 7)
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
    @AppStorage("serverIP") private var serverIP = ServerConfig.defaultIP
    @Environment(\.colorScheme) private var scheme
    @State private var lastFailHaptic: Int = 0
    @State private var lastWSConnected: Bool? = nil
    @State private var lastBridgeConnected: Bool? = nil
    @State private var lastPollLogged: String? = nil

    private var theme: FTTheme { scheme == .dark ? .dark : .light }

    var body: some View {
        TabView {
            DashboardTab()
                .tabItem { Label("Dashboard", systemImage: "square.grid.2x2") }

            SessionTab()
                .tabItem { Label("Session", systemImage: "record.circle") }
                .badge(server.currentSessionId != nil ? "●" : nil)

            SettingsTab()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .tint(theme.accent)
        .environment(\.ft, theme)
        .preferredColorScheme(.none)
        .onAppear { bridge.syncServerIP(serverIP) }
        .onReceive(server.$isConnected) { ok in
            // Why: isConnected re-emits on every received WS frame (~1 Hz). Log and
            // buzz only on an actual up/down transition, else the event feed floods
            // with "connected" and pushes real events out of the 60-entry cap.
            guard lastWSConnected != ok else { return }
            lastWSConnected = ok
            Task { @MainActor in
                FTLogStore.shared.add("WS",
                    ok ? "connected → ws://\(serverIP):8000/ws" : "disconnected",
                    color: ok ? theme.green : theme.red)
            }
            if ok { FTHaptics.success() } else { FTHaptics.warning() }
        }
        .onReceive(server.$lastWatchCommandStatus) { cmd in
            guard !cmd.isEmpty, cmd != "No command sent" else { return }
            let ok = cmd.contains("acknowledged") || cmd.contains("confirmed")
            Task { @MainActor in
                FTLogStore.shared.add(ok ? "ACK" : "CMD", cmd,
                    color: ok ? theme.green : theme.yellow)
            }
        }
        .onReceive(server.$lastWatchPollStatus) { poll in
            // Why: re-emits ~1 Hz with the same string; log only when it changes.
            guard poll != "No Watch poll yet", poll != lastPollLogged else { return }
            lastPollLogged = poll
            Task { @MainActor in
                FTLogStore.shared.add("POLL", poll, color: theme.blue)
            }
        }
        .onReceive(server.$currentSessionId) { sid in
            Task { @MainActor in
                if let sid {
                    FTLogStore.shared.add("SESSION", "start → \(sid)", color: theme.green)
                    LiveQualityStore.shared.startPolling(sessionId: sid)
                } else {
                    FTLogStore.shared.add("SESSION", "stopped", color: theme.yellow)
                    LiveQualityStore.shared.stopPolling()
                    SessionsHistoryStore.shared.refresh(force: true)
                }
            }
            if sid != nil { FTHaptics.success() } else { FTHaptics.medium() }
        }
        .onReceive(bridge.$isConnected) { ok in
            if lastBridgeConnected != ok {
                lastBridgeConnected = ok
                if !ok { FTHaptics.warning() }
            }
        }
        .onReceive(bridge.$failedUploadCount) { count in
            // Haptic only on first failure of a new outage; reset when count returns to 0.
            if count == 0 {
                lastFailHaptic = 0
            } else if lastFailHaptic == 0 && !bridge.lastError.isEmpty {
                lastFailHaptic = count
                FTHaptics.error()
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Preview
// ─────────────────────────────────────────────────────────────────────────────

#Preview("Light") { iPhoneView().preferredColorScheme(.light) }
#Preview("Dark")  { iPhoneView().preferredColorScheme(.dark)  }

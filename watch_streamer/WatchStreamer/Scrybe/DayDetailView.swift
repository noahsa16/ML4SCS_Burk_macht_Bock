import SwiftUI

struct DayDetailView: View {
    let date: String

    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var isToday: Bool { date == focus.today?.date }
    private var dayDTO: FocusDayDTO? { focus.history?.days.first { $0.date == date } }
    private var stretches: [FocusStretchDTO] {
        isToday ? (focus.today?.stretches ?? []) : (focus.dayCache[date]?.stretches ?? [])
    }
    private var totalSeconds: Double {
        dayDTO?.writingSeconds ?? stretches.reduce(0) { $0 + $1.durationS }
    }
    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: totalSeconds, goalSeconds: goalSeconds).isMet
    }

    // Day writing-intensity timeline: stretches concatenated with a 0 between
    // them so between-session pauses read as dips toward the threshold.
    private var daySamples: [Double] {
        var out: [Double] = []
        for s in stretches { out.append(contentsOf: s.intensitySamples); out.append(0) }
        if !out.isEmpty { out.removeLast() }
        return out
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                if !stretches.isEmpty {
                    curveCard
                    sessionsCard
                } else {
                    Text("Keine Schreibphasen an diesem Tag.")
                        .font(.footnote).foregroundStyle(theme.secondaryInk)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { theme.paper.ignoresSafeArea() }
        .navigationTitle(DateFormatting.dayMonth(iso: date))
        .navigationBarTitleDisplayMode(.inline)
        .task { if !isToday { await focus.loadDay(date) } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(TimeFormatting.human(seconds: totalSeconds))
                .font(.system(.largeTitle, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
                .contentTransition(.numericText())
            if isMet {
                Label("Tagesziel erreicht", systemImage: "checkmark.seal")
                    .font(.subheadline).foregroundStyle(theme.successInk)
            }
        }
    }

    private var curveCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Schreibintensität").font(.headline).foregroundStyle(theme.ink)
            IntensityCurve(samples: daySamples)
            Text("\(stretches.count) Schreibphasen")
                .font(.caption).foregroundStyle(theme.secondaryInk)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }

    private var sessionsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Schreibphasen").font(.headline).foregroundStyle(theme.ink)
            ForEach(stretches) { s in
                StretchRow(stretch: s)
                if s.id != stretches.last?.id {
                    Divider().background(theme.hairline)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }
}

private struct StretchRow: View {
    let stretch: FocusStretchDTO
    @Environment(\.scrybe) private var theme

    private var start: String { StretchClock.hhmm(stretch.startMs) }
    private var end: String { StretchClock.hhmm(stretch.endMs) }
    private var duration: String { TimeFormatting.human(seconds: stretch.durationS) }
    private var a11y: String { "\(start) bis \(end), \(duration)" }

    var body: some View {
        HStack(spacing: 8) {
            Text(start).monospacedDigit()
            Text("–")
            Text(end).monospacedDigit()
            Spacer()
            MiniSparkline(samples: stretch.intensitySamples)
            Text(duration).foregroundStyle(theme.secondaryInk)
        }
        .font(.callout)
        .foregroundStyle(theme.ink)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(a11y)
    }
}

/// Wall-clock HH:mm for an inference-log millisecond timestamp.
enum StretchClock {
    // Why: called once per session row per body pass; a fresh DateFormatter
    // each time is the most expensive part of rendering the History list.
    private static let lock = NSLock()
    private static var cached: (identifier: String, formatter: DateFormatter)?

    private static func formatter() -> DateFormatter {
        let locale = ScrybeSettings.localeOverride ?? .current
        lock.lock()
        defer { lock.unlock() }
        if let cached, cached.identifier == locale.identifier { return cached.formatter }
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = .current
        f.dateFormat = "HH:mm"
        cached = (locale.identifier, f)
        return f
    }

    static func hhmm(_ ms: Int) -> String {
        formatter().string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}

#Preview {
    NavigationStack {
        DayDetailView(date: "2026-06-22").scrybeTheme()
    }
}

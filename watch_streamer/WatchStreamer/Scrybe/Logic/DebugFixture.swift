#if DEBUG
import Foundation

/// Simulator seeding for visual checks of Trends, Fokus and Profil, which
/// are empty on a fresh install and cannot be filled without a Watch.
///
/// Launch with `-scrybeFixture` to ingest twenty days of synthetic writing
/// and a few creatures once; add `-scrybeInitialTab trends|focus` to land
/// on a tab and `-scrybeInitialSpan month` to open Trends on the month view.
/// Debug builds only — the release binary does not contain this.
///
///     xcrun simctl launch booted ML4SCS.WatchStreamer -scrybeFixture -scrybeInitialTab trends -scrybeInitialSpan month
enum DebugFixture {
    private static let seededKey = "scrybe.debugFixtureSeeded"

    static var isRequested: Bool { CommandLine.arguments.contains("-scrybeFixture") }

    /// `-scrybeInitialTab profile` opens the profile sheet over Heute.
    static var opensProfile: Bool {
        UserDefaults.standard.string(forKey: "scrybeInitialTab") == "profile"
    }

    static var initialTab: RootPagerView.Tab? {
        switch UserDefaults.standard.string(forKey: "scrybeInitialTab") {
        case "trends": return .trends
        case "focus": return .focus
        case "today": return .today
        default: return nil
        }
    }

    static var initialSpan: TrendPaging.Span? {
        UserDefaults.standard.string(forKey: "scrybeInitialSpan") == "month" ? .month : nil
    }

    /// Minutes written per day, newest last. Zeros are rest days; the mix
    /// gives the charts a peak, a streak and a comparison window.
    private static let minutesPerDay: [Int] = [
        14, 8, 0, 19, 37, 5, 8, 22, 11, 0, 15, 41, 6, 0, 25, 9, 33, 12, 0, 18,
    ]

    @MainActor
    static func seedIfRequested() async {
        guard isRequested, !UserDefaults.standard.bool(forKey: seededKey) else { return }
        UserDefaults.standard.set(true, forKey: seededKey)

        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        var batch: [PassiveDecision] = []
        for (index, minutes) in minutesPerDay.enumerated() where minutes > 0 {
            let back = minutesPerDay.count - 1 - index
            guard let day = calendar.date(byAdding: .day, value: -back, to: today) else { continue }
            // Two sittings a day, late morning and evening, so the time-of-day
            // chart and the day pages both have shape.
            let sittings: [(hour: Int, share: Double)] = [(10 + back % 3, 0.6), (19 - back % 2, 0.4)]
            for sitting in sittings {
                let start = day.addingTimeInterval(Double(sitting.hour) * 3600 + Double(back * 97 % 1200))
                let seconds = Double(minutes) * 60 * sitting.share
                var t = start.timeIntervalSince1970
                let end = t + seconds
                var i = 0
                while t < end {
                    let startMs = Int64(t * 1000)
                    batch.append(PassiveDecision(startMs: startMs, endMs: startMs + 5000,
                                                 logit: Float(1.2 + 0.8 * sin(Double(i) * 0.3)),
                                                 writing: true, creditSeconds: 2.5))
                    t += 2.5
                    i += 1
                }
            }
        }
        await FocusStore.shared.ingest(batch)
        // Two finished creatures and one about half drawn.
        BestiaryStore.shared.addWritingSeconds(2 * Bestiary.secondsPerCreature + 810,
                                               now: today.addingTimeInterval(-86_400 * 3))
    }
}
#endif

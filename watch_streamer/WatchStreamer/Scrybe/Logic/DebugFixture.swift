#if DEBUG
import Foundation

/// Simulator seeding for visual checks of Trends, Fokus and Profil, which
/// are empty on a fresh install and cannot be filled without a Watch.
///
/// Launch with `-scrybeFixture` to ingest twenty days of synthetic writing
/// and a few creatures once; add `-scrybeInitialTab trends|focus` to land
/// on a tab and `-scrybeInitialSpan month` to open Trends on the month view.
/// `-scrybeFixtureDays 90` seeds a months-long history instead, for product
/// footage that has to look like a long-standing account.
/// `-scrybeDemoSession 30` starts the focus tab's scripted session at that
/// tempo, the same one the admin panel's "Fokus-Sitzung vorführen" runs.
/// Debug builds only — the release binary does not contain this.
///
///     xcrun simctl launch booted ML4SCS.WatchStreamer -scrybeFixture -scrybeInitialTab trends -scrybeInitialSpan month
///     xcrun simctl launch booted ML4SCS.WatchStreamer -scrybeFixture -scrybeFixtureDays 90
///     xcrun simctl launch booted ML4SCS.WatchStreamer -scrybeDemoSession 30
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

    /// Session seconds per wall-clock second for `-scrybeDemoSession`, or
    /// `nil` when the argument is absent or not a number.
    static var demoSessionSpeed: Double? {
        let value = UserDefaults.standard.double(forKey: "scrybeDemoSession")
        return value > 0 ? value : nil
    }

    /// A screen that only opens by tapping: `-scrybeInitialScreen history`
    /// pushes Verlauf, `day` the newest day, `bestiary` the collection,
    /// `duration` the length sheet, `outcome` a refused start, `admin` the
    /// operator panel and `adminGate` its PIN screen. The screens behind a
    /// tab or the profile need the matching `-scrybeInitialTab` alongside.
    enum Screen: String {
        case history, day, bestiary, duration, outcome, admin, adminGate
    }

    static var initialScreen: Screen? {
        UserDefaults.standard.string(forKey: "scrybeInitialScreen")
            .flatMap(Screen.init(rawValue:))
    }

    /// `-scrybeOnboardingPage 2` opens the first-run flow on that page.
    static var onboardingPage: Int? {
        guard UserDefaults.standard.object(forKey: "scrybeOnboardingPage") != nil else { return nil }
        return UserDefaults.standard.integer(forKey: "scrybeOnboardingPage")
    }

    /// Today as the `yyyy-MM-dd` key the day pages are addressed by.
    static var todayKey: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    static var initialSpan: TrendPaging.Span? {
        UserDefaults.standard.string(forKey: "scrybeInitialSpan") == "month" ? .month : nil
    }

    /// Days of history to seed. Capped at the store's own 90-day retention,
    /// past which a seeded day would be pruned on the first refresh anyway.
    static var fixtureDays: Int {
        let requested = UserDefaults.standard.integer(forKey: "scrybeFixtureDays")
        return requested > 0 ? min(requested, 90) : minutesPerDay.count
    }

    /// Day goal the seeded history is shaped against. The shipped default is
    /// two hours, which no plausible handwriting day meets, so every seeded
    /// day would read as a missed goal and both streaks would be zero.
    private static let seededGoalSeconds: Double = 45 * 60

    /// Minutes written per day, newest last. Zeros are rest days; the mix
    /// gives the charts a peak, a streak and a comparison window.
    private static let minutesPerDay: [Int] = [
        14, 8, 0, 19, 37, 5, 8, 22, 11, 0, 15, 41, 6, 0, 25, 9, 33, 12, 0, 18,
    ]

    @MainActor
    static func seedIfRequested() async {
        let days = fixtureDays
        // Keyed by length so switching `-scrybeFixtureDays` on an installed
        // simulator app seeds again rather than silently keeping the old run.
        // The two histories then overlap; delete the app between lengths.
        let key = "\(seededKey).\(days)"
        guard isRequested, !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)
        seedSettings()

        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        let minutes = days <= minutesPerDay.count
            ? Array(minutesPerDay.suffix(days))
            : generatedMinutes(days: days, endingOn: today, calendar: calendar)

        var batch: [PassiveDecision] = []
        for (index, dayMinutes) in minutes.enumerated() where dayMinutes > 0 {
            let back = minutes.count - 1 - index
            guard let day = calendar.date(byAdding: .day, value: -back, to: today) else { continue }
            batch += decisions(on: day, minutes: dayMinutes, back: back)
            // A creature grows out of deliberate sessions, not out of the day's
            // passive total, so only some days credit the collection.
            if back % 5 == 0 {
                BestiaryStore.shared.addWritingSeconds(Double(dayMinutes) * 60 * 0.7, now: day)
            }
        }
        await FocusStore.shared.ingest(batch)
        if days <= minutesPerDay.count {
            // Two finished creatures and one about half drawn.
            BestiaryStore.shared.addWritingSeconds(2 * Bestiary.secondsPerCreature + 810,
                                                   now: today.addingTimeInterval(-86_400 * 3))
        }
    }

    /// Settings an account this old would have long since made, so the footage
    /// does not open on the first-run flow or on an unreachable day goal.
    private static func seedSettings() {
        let defaults = UserDefaults.standard
        defaults.set(true, forKey: ScrybeSettings.onboardingDoneKey)
        defaults.set(seededGoalSeconds, forKey: ScrybeSettings.goalKey)
        defaults.set(25, forKey: ScrybeSettings.focusDurationKey)
        // The reminder stays off on purpose: switching it on asks for the
        // notification permission, and that system alert lands in the middle
        // of whatever is being filmed.
    }

    /// Minutes per day for a history longer than the fixed array, newest last.
    ///
    /// Shaped rather than random, so a recording can be repeated: weekends
    /// thin out, the early weeks are lighter than the recent ones, two
    /// multi-day gaps sit in the middle, and one older run plus the current
    /// one keep the longest streak ahead of the running one.
    private static func generatedMinutes(days: Int, endingOn today: Date,
                                         calendar: Calendar) -> [Int] {
        let goalMinutes = Int(seededGoalSeconds / 60)
        var out: [Int] = []
        for index in 0..<days {
            let back = days - 1 - index
            guard let day = calendar.date(byAdding: .day, value: -back, to: today) else { continue }
            let weekday = calendar.component(.weekday, from: day)
            let isWeekend = weekday == 1 || weekday == 7

            // Someone who kept at it: the habit grows over the window.
            let progress = Double(index) / Double(max(days - 1, 1))
            var minutes = (22 + 34 * progress) * (isWeekend ? 0.4 : 1.0)
            minutes *= 0.75 + 0.5 * fraction(index)

            // Two breaks — a week away and a long weekend.
            if (34...40).contains(back) || (12...14).contains(back) { minutes = 0 }
            // An older run and the current one, so longest > current.
            if (48...61).contains(back) { minutes = max(minutes, Double(goalMinutes + 4)) }
            if (1...9).contains(back) { minutes = max(minutes, Double(goalMinutes + 3)) }
            // Today is deliberately still short of the goal: the ring on Heute
            // reads as a day in progress rather than a finished one.
            if back == 0 { minutes = Double(goalMinutes) * 0.42 }

            out.append(Int(minutes.rounded()))
        }
        return out
    }

    /// Deterministic 0..<1 noise, so the same launch arguments always produce
    /// the same charts.
    private static func fraction(_ i: Int) -> Double {
        let x = sin(Double(i) * 12.9898) * 43_758.5453
        return x - x.rounded(.down)
    }

    /// One day of writing windows, in two or three sittings.
    ///
    /// Days still inside the raw retention keep the tracker's real 2.5 s
    /// stride; older ones are coarser, because they are rolled up into a day
    /// summary on the first refresh and only their totals, stretches and
    /// hourly buckets survive — all of which a 30 s window reproduces at a
    /// twelfth of the objects.
    private static func decisions(on day: Date, minutes: Int, back: Int) -> [PassiveDecision] {
        let stride = back < FocusArchive.rawRetentionDays ? 2.5 : 30.0
        let sittings: [(hour: Int, share: Double)] = minutes >= 30
            ? [(9 + back % 3, 0.45), (14 + back % 2, 0.2), (19 - back % 2, 0.35)]
            : [(10 + back % 3, 0.6), (19 - back % 2, 0.4)]

        var out: [PassiveDecision] = []
        for sitting in sittings {
            // Minutes into the hour vary per day and per sitting, so a scroll
            // through Verlauf does not show the same clock times every day.
            let jitter = fraction(back * 7 + sitting.hour) * 2_700
            let start = day.addingTimeInterval(Double(sitting.hour) * 3600 + jitter)
            let seconds = Double(minutes) * 60 * sitting.share
            var t = start.timeIntervalSince1970
            let end = t + seconds
            var i = 0
            while t < end {
                let startMs = Int64(t * 1000)
                out.append(PassiveDecision(startMs: startMs,
                                           endMs: startMs + Int64(stride * 1000),
                                           logit: Float(1.2 + 0.8 * sin(Double(i) * 0.3)),
                                           writing: true, creditSeconds: stride))
                t += stride
                i += 1
            }
        }
        return out
    }
}
#endif

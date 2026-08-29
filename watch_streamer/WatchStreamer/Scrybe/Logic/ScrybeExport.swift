import Foundation

/// A versioned, self-describing export of the data the app holds locally.
///
/// The Profile screen previously shared an in-memory JSON *string* with no
/// filename and no type, containing only per-day seconds — while the label and
/// the privacy paragraph implied a portable copy of the user's data. This
/// writes a real file so receiving apps see JSON with a name, and states in
/// the payload itself what it does and does not contain.
enum ScrybeExport {
    /// Bump when the shape changes so a consumer can tell versions apart.
    static let schemaVersion = 1

    /// Builds the export payload.
    static func makeJSON(history: FocusRangeDTO?,
                         today: FocusTodayDTO?,
                         now: Date = Date()) -> Data {
        let root: [String: Any] = [
            "schema_version": schemaVersion,
            "exported_at": isoFormatter.string(from: now),
            "app": "Scrybe",
            // Why named explicitly: an export that omits raw motion data must
            // say so, or its absence reads as "there was none to begin with".
            "contains": ["daily_writing_seconds", "todays_writing_stretches",
                         "local_settings"],
            "excludes": ["raw_motion_samples", "server_side_recordings"],
            "days": (history?.days ?? []).map {
                ["date": $0.date, "writing_seconds": $0.writingSeconds]
            },
            "today_stretches": (today?.stretches ?? []).map {
                ["start_ms": $0.startMs, "end_ms": $0.endMs,
                 "duration_seconds": $0.durationS]
            },
            "settings": [
                "daily_goal_seconds": ScrybeSettings.goalSeconds,
                "language": UserDefaults.standard.string(forKey: ScrybeSettings.languageKey)
                    ?? ScrybeSettings.defaultLanguage,
                "week_start": UserDefaults.standard.integer(forKey: ScrybeSettings.weekStartKey),
            ],
        ]
        return (try? JSONSerialization.data(withJSONObject: root,
                                            options: [.prettyPrinted, .sortedKeys]))
            ?? Data("{}".utf8)
    }

    static func filename(now: Date = Date()) -> String {
        "scrybe-export-\(stampFormatter.string(from: now)).json"
    }

    /// Writes the export to a temporary file and returns its URL.
    ///
    /// Why a file rather than `Transferable` with `suggestedFileName`: that
    /// modifier is iOS 17+, and this app deploys to iOS 16. Sharing a file URL
    /// carries the name and the JSON type on every supported version.
    static func writeTemporaryFile(history: FocusRangeDTO?,
                                   today: FocusTodayDTO?,
                                   now: Date = Date()) -> URL? {
        let data = makeJSON(history: history, today: today, now: now)
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(filename(now: now))
        do {
            try data.write(to: url, options: [.atomic])
            return url
        } catch {
            return nil
        }
    }

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let stampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}

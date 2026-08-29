import SwiftUI
import Combine

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – Log store
// ─────────────────────────────────────────────────────────────────────────────

struct FTLogEntry: Identifiable {
    let id   = UUID()
    let date = Date()
    let tag:      String
    let tagColor: Color
    let message:  String

    // Why: the Admin log list reads this property for every visible row on
    // every body pass; building a DateFormatter per access is pure waste.
    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    var timeString: String { Self.timeFormatter.string(from: date) }
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

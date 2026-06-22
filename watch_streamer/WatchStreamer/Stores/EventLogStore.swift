import SwiftUI

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

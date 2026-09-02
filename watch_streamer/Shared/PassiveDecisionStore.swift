import Foundation

/// One model verdict for one window.
public nonisolated struct PassiveDecision: Codable, Equatable, Sendable {
    public let startMs: Int64
    public let endMs: Int64
    public let logit: Float
    public let writing: Bool
    /// Seconds of writing time this decision contributes. With overlapping
    /// windows this is the stride, not the window span.
    public let creditSeconds: Double

    public init(startMs: Int64, endMs: Int64, logit: Float,
                writing: Bool, creditSeconds: Double) {
        self.startMs = startMs
        self.endMs = endMs
        self.logit = logit
        self.writing = writing
        self.creditSeconds = creditSeconds
    }
}

/// Append-only persistence and daily aggregation for passive decisions.
///
/// Mirrors the existing spill design (JSONL in a serial queue) rather than
/// inventing a second persistence style, so its failure modes are ones this
/// codebase already handles: a torn last line costs one decision, not the file.
/// `nonisolated` so the tracker can read and append from a background
/// context; the type serializes its own file access on a private queue.
public nonisolated final class PassiveDecisionStore {
    private let fileURL: URL
    private let queue = DispatchQueue(label: "com.watchstreamer.passive.decisions",
                                      qos: .utility)
    private let calendar: Calendar
    /// Window starts already on disk, so an append deduplicates against
    /// memory instead of decoding the whole file on every cycle. Loaded from
    /// the file on first use and kept in step by every mutating call; only
    /// ever touched on `queue`.
    private var knownStarts: Set<Int64>?

    public init(fileURL: URL, calendar: Calendar = .current) {
        self.fileURL = fileURL
        self.calendar = calendar
    }

    /// Default location: Application Support, excluded from backups. Motion
    /// data is sensitive, and a decision log is derived motion data.
    public static func defaultFileURL() -> URL {
        AppSupportURL.file(named: "passive_decisions.jsonl")
    }

    @discardableResult
    public func record(_ decisions: [PassiveDecision]) -> Bool {
        guard !decisions.isEmpty else { return true }
        let url = fileURL
        return queue.sync {
            var seen = loadKnownStarts()
            let unique = decisions.filter { seen.insert($0.startMs).inserted }
            guard !unique.isEmpty else { return true }
            guard let blob = Self.encodeLines(unique) else { return false }
            let fm = FileManager.default
            if !fm.fileExists(atPath: url.path) {
                fm.createFile(atPath: url.path, contents: nil)
            }
            guard let handle = try? FileHandle(forWritingTo: url) else { return false }
            defer { try? handle.close() }
            do {
                _ = try handle.seekToEnd()
                try handle.write(contentsOf: blob)
                knownStarts = seen
                return true
            } catch {
                // Why: a failed or partial append leaves the file authoritative
                // and the cache unknown; the next call re-reads once.
                knownStarts = nil
                return false
            }
        }
    }

    /// Every decision on disk, skipping lines that failed to decode.
    public func allDecisions() -> [PassiveDecision] {
        let url = fileURL
        return queue.sync { Self.decodeFile(at: url) }
    }

    public func decisions(onDayContaining date: Date) -> [PassiveDecision] {
        let start = calendar.startOfDay(for: date)
        guard let end = calendar.date(byAdding: .day, value: 1, to: start) else { return [] }
        let startMs = Int64(start.timeIntervalSince1970 * 1000)
        let endMs = Int64(end.timeIntervalSince1970 * 1000)
        return allDecisions().filter { $0.startMs >= startMs && $0.startMs < endMs }
    }

    /// Writing seconds for a local-time day. Only `writing` decisions count,
    /// each contributing its stride rather than its full window span.
    public func writingSeconds(onDayContaining date: Date) -> Double {
        decisions(onDayContaining: date)
            .filter(\.writing)
            .reduce(0) { $0 + $1.creditSeconds }
    }

    /// Drops decisions older than `days` local days. Rewrites the file once.
    @discardableResult
    public func pruneOlderThan(days: Int, now: Date = Date()) -> Bool {
        let today = calendar.startOfDay(for: now)
        guard let cutoff = calendar.date(byAdding: .day, value: -days, to: today) else {
            return false
        }
        let cutoffMs = Int64(cutoff.timeIntervalSince1970 * 1000)
        let kept = allDecisions().filter { $0.startMs >= cutoffMs }
        return replaceAll(with: kept)
    }

    /// Replaces the log with an already-loaded compacted snapshot. This is
    /// used by the archive pass so it never has to read and decode the same
    /// JSONL file a second time merely to prune it.
    @discardableResult
    public func replaceAll(with decisions: [PassiveDecision]) -> Bool {
        guard let blob = Self.encodeLines(decisions) else { return false }
        let url = fileURL
        return queue.sync {
            do {
                try blob.write(to: url, options: [.atomic])
                knownStarts = Set(decisions.map(\.startMs))
                return true
            } catch {
                knownStarts = nil
                return false
            }
        }
    }

    public func removeAll() {
        let url = fileURL
        queue.sync {
            try? FileManager.default.removeItem(at: url)
            knownStarts = []
        }
    }

    /// Must run on `queue`.
    private func loadKnownStarts() -> Set<Int64> {
        if let knownStarts { return knownStarts }
        let loaded = Set(Self.decodeFile(at: fileURL).map(\.startMs))
        knownStarts = loaded
        return loaded
    }

    private static func decodeFile(at url: URL) -> [PassiveDecision] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        let decoder = JSONDecoder()
        return data.split(separator: 0x0A).compactMap {
            try? decoder.decode(PassiveDecision.self, from: Data($0))
        }
    }

    private static func encodeLines(_ decisions: [PassiveDecision]) -> Data? {
        let encoder = JSONEncoder()
        var blob = Data()
        for decision in decisions {
            guard let line = try? encoder.encode(decision) else { return nil }
            blob.append(line)
            blob.append(0x0A)
        }
        return blob
    }
}

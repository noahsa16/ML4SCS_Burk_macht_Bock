import Combine
import Foundation

/// The collected creatures.
///
/// Exactly one creature is ever in progress. Every session's credited
/// writing seconds add to it — a short session leaves it partly drawn and
/// the next session resumes it, rather than starting over. It completes once
/// it holds a full `Bestiary.secondsPerCreature`, is archived, and the next
/// creature begins with whatever surplus the finishing session had left over.
///
/// Measuring against a session's own target instead would let a five-minute
/// goal earn the same finished creature as a forty-five-minute one — a
/// collection earned that easily counts sessions, not writing.
@MainActor
final class BestiaryStore: ObservableObject {
    static let shared = BestiaryStore(fileURL: BestiaryStore.defaultFileURL())

    /// Finished creatures, most recently completed first.
    @Published private(set) var completed: [BestiaryEntry] = []
    /// The creature presently being drawn. `nil` only before the very first
    /// second of writing has ever been credited.
    @Published private(set) var current: BestiaryEntry?

    /// Every creature the collection holds, in display order: the one still
    /// being drawn first (if any), then finished creatures newest to oldest.
    var all: [BestiaryEntry] { (current.map { [$0] } ?? []) + completed }

    private let fileURL: URL

    init(fileURL: URL = BestiaryStore.defaultFileURL()) {
        self.fileURL = fileURL
        let snapshot = Self.load(from: fileURL)
        completed = snapshot.completed
        current = snapshot.current
    }

    /// Mirrors `FocusArchive.defaultFileURL()` so both live in one place.
    ///
    /// `nonisolated`: a `@MainActor` initializer evaluates its default
    /// arguments outside the actor, so a MainActor-isolated version of this
    /// could not be called from `init`'s own signature.
    nonisolated static func defaultFileURL() -> URL {
        let fm = FileManager.default
        let base = (try? fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                appropriateFor: nil, create: true))
            ?? fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? fm.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("bestiary.json")
    }

    // MARK: - Growing the creature in progress

    /// Credits `seconds` of writing time toward the creature already in
    /// progress, or starts a fresh one at `now` if none is.
    ///
    /// A single call that pushes past `Bestiary.secondsPerCreature` completes
    /// that creature — capped at the target, never overdrawn — and rolls the
    /// surplus into a new creature that begins at the same `now`. Splitting
    /// the same total across several calls (several sittings) reaches the
    /// same accumulated total and the same number of finished creatures
    /// either way; only *when* a creature completes depends on the split.
    func addWritingSeconds(_ seconds: Double, now: Date = Date()) {
        guard seconds > 0 else { return }
        var remaining = seconds
        while remaining > 1e-9 {
            let creature = current ?? beginCreature(at: now)
            let room = max(0, Bestiary.secondsPerCreature - creature.writingSeconds)
            let add = min(remaining, room)
            remaining -= add
            let newTotal = creature.writingSeconds + add
            if newTotal >= Bestiary.secondsPerCreature {
                completed.insert(BestiaryEntry(
                    speciesId: creature.speciesId, startedMs: creature.startedMs,
                    strokesTotal: creature.strokesTotal,
                    writingSeconds: Bestiary.secondsPerCreature,
                    completedMs: Int64(now.timeIntervalSince1970 * 1000)), at: 0)
                current = nil
            } else {
                current = BestiaryEntry(
                    speciesId: creature.speciesId, startedMs: creature.startedMs,
                    strokesTotal: creature.strokesTotal,
                    writingSeconds: newTotal, completedMs: nil)
            }
        }
        persist()
    }

    /// Seeded from the moment the creature begins, not from any one session's
    /// own start — a half-drawn creature must not change species when a
    /// later session resumes it (see `addWritingSeconds`, which only calls
    /// this when there is no creature to resume).
    private func beginCreature(at now: Date) -> BestiaryEntry {
        let startedMs = Int64(now.timeIntervalSince1970 * 1000)
        let speciesId = Bestiary.species(forSessionStartMs: startedMs)
        return BestiaryEntry(speciesId: speciesId, startedMs: startedMs,
                             strokesTotal: Marginalia.strokeCount(forSpecies: speciesId),
                             writingSeconds: 0, completedMs: nil)
    }

    // MARK: - Erasing

    func deleteAll() {
        completed.removeAll()
        current = nil
        try? FileManager.default.removeItem(at: fileURL)
    }

    // MARK: - Persistence

    private struct Snapshot: Codable {
        var completed: [BestiaryEntry]
        var current: BestiaryEntry?
    }

    private static func load(from url: URL) -> Snapshot {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode(Snapshot.self, from: data)
        else { return Snapshot(completed: [], current: nil) }
        return decoded
    }

    private func persist() {
        let snapshot = Snapshot(completed: completed, current: current)
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        // Why atomic: a torn file would lose the collection outright, and
        // unlike raw passive windows there is nothing to rebuild it from.
        try? data.write(to: fileURL, options: .atomic)
    }
}

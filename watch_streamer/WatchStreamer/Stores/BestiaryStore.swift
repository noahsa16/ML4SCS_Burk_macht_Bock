import Combine
import Foundation
import SwiftUI

/// The collected creatures.
///
/// At most one creature is ever in progress. Every session's credited
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
    /// The creature presently being drawn — `nil` before any writing has
    /// ever been credited, right after `deleteAll()`, and briefly whenever
    /// the last credit landed exactly on `Bestiary.secondsPerCreature` with
    /// no surplus to open the next creature. None of those states means "has
    /// never written" on their own; check `completed` too if that's the
    /// question.
    @Published private(set) var current: BestiaryEntry?

    /// Every creature the collection holds, in display order: the one still
    /// being drawn first (if any), then finished creatures newest to oldest.
    var all: [BestiaryEntry] { (current.map { [$0] } ?? []) + completed }

    /// `all`, minus a creature that has accumulated writing but not yet
    /// earned its first stroke (up to 23 s of a 1800 s target on the
    /// sparsest species). What `BestiaryView` draws, and what any other
    /// screen should check before deciding the collection has something to
    /// show — an entry with credited seconds but zero visible strokes reads
    /// as broken, not "in progress".
    var visible: [BestiaryEntry] { all.filter { $0.strokesDrawn > 0 } }

    private let fileURL: URL
    /// Set when the file on disk exists but could not be read or decoded —
    /// e.g. still protected under `completeUntilFirstUserAuthentication`
    /// after a reboot, or genuinely corrupt. A collection cannot be rebuilt
    /// from anything else, so this instance never writes over data it could
    /// not first read; it stays in memory only until the next relaunch, by
    /// which point whatever blocked the read has usually cleared.
    private var persistenceSuspended = false

    init(fileURL: URL = BestiaryStore.defaultFileURL()) {
        self.fileURL = fileURL
        switch Self.load(from: fileURL) {
        case .absent:
            completed = []
            current = nil
        case .loaded(let snapshot):
            completed = snapshot.completed.map(Self.redrawable)
            current = snapshot.current.map(Self.redrawable)
        case .unreadable(let reason):
            completed = []
            current = nil
            persistenceSuspended = true
            // Why logged: the suspension is silent by design — the collection
            // keeps working in memory — so without a line here a user losing
            // every creature on each launch leaves no trace to work from. The
            // reason separates the two cases that need different answers: a
            // protected file usually clears on the next unlock, a decode
            // failure never does.
            FTLogStore.shared.add("BESTIARY",
                                  "Sammlung nicht lesbar, Speichern ausgesetzt: \(reason)",
                                  color: ScrybeTheme.standard.danger)
        }
    }

    /// Mirrors `FocusArchive.defaultFileURL()` so both live in one place.
    ///
    /// `nonisolated`: a `@MainActor` initializer evaluates its default
    /// arguments outside the actor, so a MainActor-isolated version of this
    /// could not be called from `init`'s own signature.
    nonisolated static func defaultFileURL() -> URL {
        AppSupportURL.file(named: "bestiary.json")
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
                    ordinal: creature.ordinal, speciesId: creature.speciesId,
                    startedMs: creature.startedMs, strokesTotal: creature.strokesTotal,
                    writingSeconds: Bestiary.secondsPerCreature,
                    completedMs: Int64(now.timeIntervalSince1970 * 1000)), at: 0)
                current = nil
            } else {
                current = BestiaryEntry(
                    ordinal: creature.ordinal, speciesId: creature.speciesId,
                    startedMs: creature.startedMs, strokesTotal: creature.strokesTotal,
                    writingSeconds: newTotal, completedMs: nil)
            }
        }
        persist()
    }

    /// The creature the next credited second will grow: the one in progress,
    /// or — when none is — the one the next credit would begin.
    ///
    /// Derived on read and never stored, so asking does not put a strokeless
    /// creature into the collection. A running session draws against this so
    /// the animal in the margin is the one its writing time will actually
    /// grow; `speciesId`, `strokesTotal`, `ordinal` and `writingSeconds` are
    /// what `addWritingSeconds` will assign, while `startedMs` is a preview
    /// whenever `current` is nil.
    func creatureInProgress(now: Date = Date()) -> BestiaryEntry {
        current ?? beginCreature(at: now)
    }

    /// A credit that both finishes the in-progress creature and overflows
    /// into the next calls this again in the same loop iteration, with the
    /// same `now` the just-finished creature was completed at — `now` alone
    /// cannot identify or seed the new creature (see `BestiaryEntry`'s
    /// header). `ordinal` can: it counts creatures ever begun, so the new
    /// one always gets a fresh identity and an independently seeded species,
    /// never a copy of the one that just finished.
    private func beginCreature(at now: Date) -> BestiaryEntry {
        let ordinal = nextOrdinal()
        let speciesId = Bestiary.species(seed: ordinal)
        let startedMs = Int64(now.timeIntervalSince1970 * 1000)
        return BestiaryEntry(ordinal: ordinal, speciesId: speciesId, startedMs: startedMs,
                             strokesTotal: Marginalia.strokeCount(forSpecies: speciesId),
                             writingSeconds: 0, completedMs: nil)
    }

    private func nextOrdinal() -> Int64 {
        let highest = (completed.map(\.ordinal) + (current.map { [$0.ordinal] } ?? [])).max()
        return (highest ?? -1) + 1
    }

    // MARK: - Erasing

    func deleteAll() {
        completed.removeAll()
        current = nil
        // The user just asked to discard everything, so there is no longer
        // any surviving data a later write could clobber.
        persistenceSuspended = false
        try? FileManager.default.removeItem(at: fileURL)
    }

    // MARK: - Persistence

    private struct Snapshot: Codable {
        var completed: [BestiaryEntry]
        var current: BestiaryEntry?
    }

    private enum LoadResult {
        case absent
        case loaded(Snapshot)
        /// Carries why: an unreadable file and an undecodable one suspend
        /// persistence alike but mean different things to whoever reads the log.
        case unreadable(reason: String)
    }

    /// Restores a stroke count `BestiaryEntry`'s tolerant decoding could not
    /// supply. It defaults `strokesTotal` to zero when the field is absent —
    /// the only value it can pick without `Marginalia`, which lives in this
    /// target — and a zero-stroke entry draws nothing and is filtered out of
    /// `visible`. Here the species is enough to recover the real count, so a
    /// degraded file loses no creature.
    private static func redrawable(_ entry: BestiaryEntry) -> BestiaryEntry {
        guard entry.strokesTotal <= 0 else { return entry }
        return BestiaryEntry(ordinal: entry.ordinal, speciesId: entry.speciesId,
                             startedMs: entry.startedMs,
                             strokesTotal: Marginalia.strokeCount(forSpecies: entry.speciesId),
                             writingSeconds: entry.writingSeconds,
                             completedMs: entry.completedMs)
    }

    private static func load(from url: URL) -> LoadResult {
        guard FileManager.default.fileExists(atPath: url.path) else { return .absent }
        do {
            let data = try Data(contentsOf: url)
            return .loaded(try JSONDecoder().decode(Snapshot.self, from: data))
        } catch {
            return .unreadable(reason: "\(error)")
        }
    }

    private func persist() {
        guard !persistenceSuspended else { return }
        let snapshot = Snapshot(completed: completed, current: current)
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        // Why atomic: a torn file would lose the collection outright, and
        // unlike raw passive windows there is nothing to rebuild it from.
        try? data.write(to: fileURL, options: .atomic)
    }
}

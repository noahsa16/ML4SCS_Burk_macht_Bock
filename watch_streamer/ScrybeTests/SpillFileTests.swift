import Testing
import Foundation
@testable import WatchStreamer

@Suite("SpillFile")
struct SpillFileTests {

    private func makeFile(maxBytes: Int = 1 << 20) -> SpillFile {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("spill-\(UUID().uuidString).jsonl")
        return SpillFile(url: url, maxBytes: maxBytes)
    }

    private func append(_ text: String, to file: SpillFile) async -> SpillFile.AppendOutcome {
        await withCheckedContinuation { c in
            file.append(Data(text.utf8)) { c.resume(returning: $0) }
        }
    }

    private func next(at offset: UInt64, in file: SpillFile) async -> SpillFile.NextLine? {
        await withCheckedContinuation { c in
            file.readNextLine(at: offset) { c.resume(returning: $0) }
        }
    }

    private func compact(_ consumed: UInt64, in file: SpillFile) async -> Bool {
        await withCheckedContinuation { c in
            file.compact(consuming: consumed) { c.resume(returning: $0) }
        }
    }

    @Test("lines come back oldest first, each with the cursor advance past it")
    func appendAndRead() async {
        let file = makeFile()
        defer { file.remove() }
        #expect(await append("{\"a\":1}", to: file) == .appended)
        #expect(await append("{\"b\":2}", to: file) == .appended)

        let first = await next(at: 0, in: file)
        #expect(first?.data == Data("{\"a\":1}".utf8))
        #expect(first?.advance == 8)
        let second = await next(at: first!.advance, in: file)
        #expect(second?.data == Data("{\"b\":2}".utf8))
        #expect(await next(at: first!.advance + second!.advance, in: file) == nil)
        #expect(file.firstLine() == first?.data)
        #expect(file.lines().count == 2)
    }

    // A drain run consumes by moving the cursor; the rewrite happens once at
    // the end and must leave the unsent remainder as the new byte 0.
    @Test("compacting drops the consumed prefix and deletes an empty file")
    func compactPrefix() async {
        let file = makeFile()
        defer { file.remove() }
        _ = await append("one", to: file)
        _ = await append("two", to: file)
        #expect(await compact(4, in: file) == false)
        #expect(await next(at: 0, in: file)?.data == Data("two".utf8))
        #expect(await compact(4, in: file) == true)
        #expect(!FileManager.default.fileExists(atPath: file.url.path))
        #expect(await next(at: 0, in: file) == nil)
    }

    // The cap protects the device disk: the newest line is refused, the
    // backlog already on disk is untouched.
    @Test("the size cap refuses the newest line and keeps the backlog")
    func capRefusesNewest() async {
        let file = makeFile(maxBytes: 10)
        defer { file.remove() }
        #expect(await append("0123456789", to: file) == .appended)
        #expect(await append("late", to: file) == .capReached)
        #expect(file.lines() == [Data("0123456789".utf8)])
    }

    // A crash mid-append leaves a line without its newline. The drain treats
    // that as end of file rather than resending half an envelope.
    @Test("a torn last line is not readable as a line")
    func tornTailIsEndOfFile() async {
        let file = makeFile()
        defer { file.remove() }
        _ = await append("whole", to: file)
        let handle = try! FileHandle(forWritingTo: file.url)
        _ = try! handle.seekToEnd()
        try! handle.write(contentsOf: Data("torn".utf8))
        try! handle.close()
        let first = await next(at: 0, in: file)
        #expect(first?.data == Data("whole".utf8))
        #expect(await next(at: first!.advance, in: file) == nil)
    }
}

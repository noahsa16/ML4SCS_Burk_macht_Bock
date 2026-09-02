import Foundation

/// The Watch's on-disk overflow for sample envelopes: one JSON line each,
/// appended when the live path is saturated, drained oldest-first, and
/// compacted once a drain run ends. Survives app kill; a torn last line
/// costs one envelope, not the file.
///
/// Owns the file and the serial queue that keeps appends and rewrites from
/// racing. It knows nothing about envelopes beyond "a line": the byte cursor
/// stays with the caller, because whether a line counts as consumed is
/// decided by the reply of the transport that resent it.
public nonisolated final class SpillFile: Sendable {
    public struct NextLine: Sendable, Equatable {
        public let data: Data
        /// Bytes to move the cursor past this line, newline included.
        public let advance: UInt64
    }

    public enum AppendOutcome: Sendable, Equatable {
        case appended
        /// The file is at its size cap; the line was not written.
        case capReached
        case failed(String)
    }

    public let url: URL
    private let maxBytes: Int
    private let readChunk: Int
    private let queue = DispatchQueue(label: "com.watchstreamer.motion.spill",
                                      qos: .utility)

    /// - Parameters:
    ///   - maxBytes: hard cap so an indefinitely disconnected watch cannot
    ///     fill the disk; past it the newest line is refused.
    ///   - readChunk: the most that one `readNextLine` reads. A line longer
    ///     than this is treated as end of file.
    public init(url: URL, maxBytes: Int, readChunk: Int = 256 * 1024) {
        self.url = url
        self.maxBytes = maxBytes
        self.readChunk = readChunk
    }

    public static func defaultURL() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("watch_spill.jsonl")
    }

    /// Appends one line. `completion` runs on the spill queue.
    public func append(_ line: Data, completion: @escaping @Sendable (AppendOutcome) -> Void) {
        queue.async { [url, maxBytes] in
            let fm = FileManager.default
            let size = (try? fm.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
            if size >= maxBytes {
                completion(.capReached)
                return
            }
            if !fm.fileExists(atPath: url.path) {
                fm.createFile(atPath: url.path, contents: nil)
            }
            guard let handle = try? FileHandle(forWritingTo: url) else {
                completion(.failed("cannot open spill file"))
                return
            }
            defer { try? handle.close() }
            do {
                _ = try handle.seekToEnd()
                var blob = line
                blob.append(0x0A)
                try handle.write(contentsOf: blob)
                completion(.appended)
            } catch {
                completion(.failed(error.localizedDescription))
            }
        }
    }

    /// Reads the line at `offset` — one bounded chunk, never the whole file.
    /// Appends only touch the end, so the bytes at `offset` are stable while
    /// they are read. `nil` means the cursor is at or past the last complete
    /// line. `completion` runs on the spill queue.
    public func readNextLine(at offset: UInt64,
                             completion: @escaping @Sendable (NextLine?) -> Void) {
        queue.async { [url, readChunk] in
            guard let handle = try? FileHandle(forReadingFrom: url) else {
                completion(nil)
                return
            }
            defer { try? handle.close() }
            try? handle.seek(toOffset: offset)
            guard let chunk = try? handle.read(upToCount: readChunk),
                  !chunk.isEmpty,
                  let nl = chunk.firstIndex(of: 0x0A) else {
                completion(nil)
                return
            }
            let lineLen = chunk.distance(from: chunk.startIndex, to: nl)
            completion(NextLine(data: Data(chunk.prefix(lineLen)),
                                advance: UInt64(lineLen) + 1))
        }
    }

    /// Drops the first `consumed` bytes in one atomic rewrite, or deletes the
    /// file when nothing remains. `completion` receives whether the file is
    /// gone, and runs on the spill queue.
    public func compact(consuming consumed: UInt64,
                        completion: @escaping @Sendable (_ deletedAll: Bool) -> Void) {
        queue.async { [url] in
            if let data = try? Data(contentsOf: url), !data.isEmpty,
               consumed < UInt64(data.count) {
                let remainder = data.subdata(in: Int(consumed)..<data.count)
                try? remainder.write(to: url, options: [.atomic])
                completion(false)
            } else {
                try? FileManager.default.removeItem(at: url)
                completion(true)
            }
        }
    }

    public func remove() {
        queue.async { [url] in try? FileManager.default.removeItem(at: url) }
    }

    /// The oldest line, read synchronously. Only meaningful at rest, when the
    /// caller's cursor is 0 and byte 0 is the oldest live line.
    public func firstLine() -> Data? {
        queue.sync { Self.splitLines(at: url).first }
    }

    /// Every complete line, read synchronously — for the launch-time count.
    public func lines() -> [Data] {
        queue.sync { Self.splitLines(at: url) }
    }

    private static func splitLines(at url: URL) -> [Data] {
        guard let data = try? Data(contentsOf: url), !data.isEmpty else { return [] }
        return data.split(separator: UInt8(0x0A), omittingEmptySubsequences: true)
            .map { Data($0) }
    }
}

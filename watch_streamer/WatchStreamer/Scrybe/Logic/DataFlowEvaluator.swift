import Foundation

struct DataFlowEvaluator {
    var window: TimeInterval = 5.0

    private var lastCount: Int?
    private var lastProgressAt: Date = .distantPast

    mutating func update(count: Int, now: Date) -> Bool {
        // Why: skip the first observation — only a real increase counts as
        // progress, otherwise the baseline read registers as flow on launch.
        if let last = lastCount, count > last {
            lastProgressAt = now
        }
        lastCount = count
        return now.timeIntervalSince(lastProgressAt) < window
    }
}

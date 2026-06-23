import Foundation

struct DailyGoalProgress {
    let fraction: Double
    let percent: Int
    let isMet: Bool

    init(writingSeconds: Double, goalSeconds: Double) {
        guard goalSeconds > 0 else {
            fraction = 0
            percent = 0
            isMet = false
            return
        }
        let raw = writingSeconds / goalSeconds
        fraction = min(1.0, max(0.0, raw))
        percent = Int((raw * 100).rounded())
        isMet = writingSeconds >= goalSeconds
    }
}

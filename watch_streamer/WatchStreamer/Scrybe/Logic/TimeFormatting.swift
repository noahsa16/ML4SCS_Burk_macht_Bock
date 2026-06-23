import Foundation

enum TimeFormatting {
    static func clock(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        return "\(total / 60):\(String(format: "%02d", total % 60))"
    }

    static func human(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        let h = total / 60
        let m = total % 60
        return h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }
}

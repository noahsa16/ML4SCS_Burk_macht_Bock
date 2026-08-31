import Foundation

/// Validates the free duration field. Pure, so the sheet stays a view.
enum FocusDurationInput {

    /// Below five minutes is not a session; the ceiling is the hard cap in
    /// `FocusCommandPolicy.sessionCapSeconds`, and offering more than the
    /// Watch will run would promise a length it then cuts.
    static let range = 5...120

    enum Failure: Error, Equatable {
        case empty
        case notAWholeNumber
        case outOfRange
    }

    static func parse(_ text: String) -> Result<Int, Failure> {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return .failure(.empty) }
        guard let minutes = Int(trimmed) else { return .failure(.notAWholeNumber) }
        guard range.contains(minutes) else { return .failure(.outOfRange) }
        return .success(minutes)
    }

    static func message(for failure: Failure) -> String {
        switch failure {
        case .empty:
            return String(localized: "Trage eine Dauer in Minuten ein.")
        case .notAWholeNumber:
            return String(localized: "Nur ganze Minuten.")
        case .outOfRange:
            return String(localized: "Zwischen 5 und 120 Minuten.")
        }
    }
}

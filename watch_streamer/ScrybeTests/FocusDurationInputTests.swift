import Testing
@testable import WatchStreamer

@Suite("Focus duration input")
struct FocusDurationInputTests {

    @Test func acceptsWholeMinutesInRange() {
        #expect(FocusDurationInput.parse("5") == .success(5))
        #expect(FocusDurationInput.parse("25") == .success(25))
        #expect(FocusDurationInput.parse("120") == .success(120))
        #expect(FocusDurationInput.parse(" 40 ") == .success(40))
    }

    @Test func rejectsOutsideTheRange() {
        #expect(FocusDurationInput.parse("4") == .failure(.outOfRange))
        #expect(FocusDurationInput.parse("121") == .failure(.outOfRange))
        #expect(FocusDurationInput.parse("0") == .failure(.outOfRange))
    }

    /// Why not round a decimal: the field says minutes, and silently turning
    /// 12.6 into 13 is the app deciding something the user typed differently.
    @Test func rejectsWhatIsNotAWholeNumber() {
        #expect(FocusDurationInput.parse("12.5") == .failure(.notAWholeNumber))
        #expect(FocusDurationInput.parse("abc") == .failure(.notAWholeNumber))
    }

    @Test func rejectsEmpty() {
        #expect(FocusDurationInput.parse("") == .failure(.empty))
        #expect(FocusDurationInput.parse("   ") == .failure(.empty))
    }
}

import Testing
import Foundation
@testable import WatchStreamer

@Suite("Ink refresh state machine")
struct InkRefreshModelTests {

    private let threshold = InkRefreshModel.threshold

    @Test("a short pull neither arms nor fires")
    func shortPullDoesNothing() {
        var m = InkRefreshModel()
        #expect(m.pull(threshold * 0.5) == false)
        #expect(m.phase == .pulling(progress: 0.5))
        #expect(m.release() == false)
        #expect(m.phase == .idle)
    }

    @Test("progress tracks the pull and never exceeds one")
    func progressIsClamped() {
        var m = InkRefreshModel()
        m.pull(threshold * 0.25)
        #expect(m.ringProgress == 0.25)
        m.pull(threshold * 4)
        #expect(m.ringProgress == 1)
    }

    @Test("crossing the threshold arms exactly once")
    func armsOnce() {
        var m = InkRefreshModel()
        #expect(m.pull(threshold) == true)
        #expect(m.pull(threshold + 40) == false)
        #expect(m.pull(threshold + 80) == false)
        #expect(m.isArmed)
    }

    @Test("dragging back below the threshold disarms and re-arms on the next crossing")
    func disarmsAndRearms() {
        var m = InkRefreshModel()
        m.pull(threshold)
        #expect(m.pull(threshold - 20) == false)
        #expect(m.isArmed == false)
        #expect(m.pull(threshold) == true)
    }

    @Test("releasing while armed starts the refresh")
    func releaseStartsRefresh() {
        var m = InkRefreshModel()
        m.pull(threshold)
        #expect(m.release() == true)
        #expect(m.phase == .refreshing)
    }

    @Test("a second release mid-refresh does not fire again")
    func releaseIsNotReentrant() {
        var m = InkRefreshModel()
        m.pull(threshold)
        _ = m.release()
        #expect(m.release() == false)
        #expect(m.phase == .refreshing)
    }

    @Test("the native pull gesture enters the same refresh state")
    func systemRefreshStartsRefresh() {
        var m = InkRefreshModel()
        let didBegin = m.beginSystemRefresh()
        #expect(didBegin)
        #expect(m.phase == .refreshing)
        #expect(m.beginSystemRefresh() == false)
    }

    // Why: the content is padded down while syncing, so the offset probe keeps
    // reporting a standing pull. Acting on it would restart the sync forever.
    @Test("pulling during a refresh is ignored")
    func pullDuringRefreshIgnored() {
        var m = InkRefreshModel()
        m.pull(threshold)
        _ = m.release()
        #expect(m.pull(threshold * 3) == false)
        #expect(m.phase == .refreshing)
        #expect(m.isActive)
    }

    @Test("a success settles with the sync time and keeps the ring closed")
    func successSettles() {
        var m = InkRefreshModel()
        let at = Date(timeIntervalSince1970: 1_700_000_000)
        m.pull(threshold)
        _ = m.release()
        m.finish(.updated(at: at))
        #expect(m.status == .updated(at))
        #expect(m.ringProgress == 1)
        #expect(m.isActive)
    }

    @Test("a settled outcome carries its harvested minutes through to status")
    func successCarriesHarvestedMinutes() {
        var m = InkRefreshModel()
        let at = Date(timeIntervalSince1970: 1_700_000_000)
        m.pull(threshold)
        _ = m.release()
        m.finish(.updated(at: at, harvestedMinutes: 14))
        #expect(m.status == .updated(at, harvestedMinutes: 14))
    }

    @Test("a failure settles as offline")
    func failureSettles() {
        var m = InkRefreshModel()
        m.pull(threshold)
        _ = m.release()
        m.finish(.offline)
        #expect(m.status == .offline)
    }

    @Test("finishing without a running refresh is ignored")
    func finishRequiresRefreshing() {
        var m = InkRefreshModel()
        m.finish(.offline)
        #expect(m.phase == .idle)
    }

    @Test("dismissing a settled result retracts the control")
    func dismissRetracts() {
        var m = InkRefreshModel()
        m.pull(threshold)
        _ = m.release()
        m.finish(.offline)
        m.dismiss()
        #expect(m.phase == .idle)
        #expect(m.isActive == false)
    }

    @Test("dismissing mid-refresh does not cut the sync short")
    func dismissIgnoredWhileRefreshing() {
        var m = InkRefreshModel()
        m.pull(threshold)
        _ = m.release()
        m.dismiss()
        #expect(m.phase == .refreshing)
    }

    // The bug this guards: a refresh whose action never returned a result left
    // the model in `.refreshing`, and `beginSystemRefresh` refuses to start
    // from there — so the control spun forever and every later pull was
    // silently swallowed until the app restarted.
    @Test("an abandoned refresh releases the control for the next pull")
    func abandonEscapesRefreshing() {
        var m = InkRefreshModel()
        _ = m.beginSystemRefresh()
        #expect(m.beginSystemRefresh() == false)

        m.abandon()
        #expect(m.phase == .idle)
        #expect(m.isActive == false)
        #expect(m.status == .hint)
        #expect(m.beginSystemRefresh() == true)
    }

    @Test("abandoning also clears a settled result")
    func abandonClearsSettled() {
        var m = InkRefreshModel()
        _ = m.beginSystemRefresh()
        m.finish(.offline)
        m.abandon()
        #expect(m.phase == .idle)
    }

    @Test("status follows the phase")
    func statusMapping() {
        var m = InkRefreshModel()
        #expect(m.status == .hint)
        m.pull(threshold * 0.4)
        #expect(m.status == .hint)
        m.pull(threshold)
        #expect(m.status == .release)
        _ = m.release()
        #expect(m.status == .syncing)
    }
}

import SwiftUI
import Combine

/// Tracks whether watch data is actually reaching the server, independent of the
/// command WebSocket. "Data flowing" = the uploaded-sample counter advanced within
/// the last few seconds — the honest answer to "is the recording capturing data".
@MainActor
final class RecordingHealthStore: ObservableObject {
    static let shared = RecordingHealthStore()
    @Published private(set) var dataFlowing = false

    private var lastUploaded: Int?
    private var lastProgressAt = Date.distantPast
    private var timer: Timer?

    private init() {
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func tick() {
        let now = PhoneBridge.shared.uploadedSampleCount
        // Why: skip the first observation — only a real increase counts as
        // progress, otherwise the baseline read would register as flow on launch.
        if let last = lastUploaded, now > last { lastProgressAt = Date() }
        lastUploaded = now
        let flowing = Date().timeIntervalSince(lastProgressAt) < 5.0
        if flowing != dataFlowing { dataFlowing = flowing }
    }
}

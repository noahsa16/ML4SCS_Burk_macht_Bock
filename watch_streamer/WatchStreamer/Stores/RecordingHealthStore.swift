import SwiftUI
import Combine

/// Tracks whether watch data is actually reaching the server, independent of the
/// command WebSocket. "Data flowing" = the uploaded-sample counter advanced within
/// the last few seconds — the honest answer to "is the recording capturing data".
@MainActor
final class RecordingHealthStore: ObservableObject {
    static let shared = RecordingHealthStore()
    @Published private(set) var dataFlowing = false

    private var evaluator = DataFlowEvaluator()
    private var timer: Timer?

    private init() {
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in self.tick() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func tick() {
        let flowing = evaluator.update(count: PhoneBridge.shared.uploadedSampleCount, now: Date())
        if flowing != dataFlowing { dataFlowing = flowing }
    }
}

import SwiftUI
import Combine

// ─────────────────────────────────────────────────────────────────────────────
// MARK: – IMU data store
// ─────────────────────────────────────────────────────────────────────────────

@MainActor
final class IMUDataStore: ObservableObject {
    static let shared = IMUDataStore()
    @Published var accSamples:  [Double] = Array(repeating: 0, count: 120)
    @Published var gyroSamples: [Double] = Array(repeating: 0, count: 120)

    // Why: bei 100 Hz feuert pushBatch() doppelt so oft, und jeder Schreib auf
    // ein @Published-Array triggert sofort einen Canvas-Redraw auf dem Main-
    // Thread. Das sättigte den Main-Thread → Chart-Lag UND (als Folge) starvte
    // die Steuerungs-Ebene (WS-handle / currentSessionId). Lösung: pushBatch()
    // sammelt nur in nicht-publizierten Puffern; ein Timer schreibt sie ~12×/s
    // in die @Published-Arrays. Der Chart bleibt flüssig, die Redraw-Rate ist
    // jetzt von der Sample-Rate entkoppelt.
    private var pendingAcc:  [Double] = Array(repeating: 0, count: 120)
    private var pendingGyro: [Double] = Array(repeating: 0, count: 120)
    private var dirty = false
    private var flushTimer: Timer?

    private init() {
        let timer = Timer(timeInterval: 1.0 / 12.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.flush() }
        }
        RunLoop.main.add(timer, forMode: .common)
        flushTimer = timer
    }

    func pushBatch(accValues: [Double], gyroValues: [Double]) {
        var newAcc  = pendingAcc  + accValues
        var newGyro = pendingGyro + gyroValues
        if newAcc.count  > 120 { newAcc  = Array(newAcc.suffix(120))  }
        if newGyro.count > 120 { newGyro = Array(newGyro.suffix(120)) }
        pendingAcc  = newAcc
        pendingGyro = newGyro
        dirty = true
    }

    /// Schreibt die gepufferten Samples in die @Published-Arrays — nur wenn
    /// seit dem letzten Flush etwas ankam. Vom 12-Hz-Timer auf Main getrieben.
    private func flush() {
        guard dirty else { return }
        dirty = false
        accSamples  = pendingAcc
        gyroSamples = pendingGyro
    }

    func startStreaming() {}

    func stopStreaming() {
        pendingAcc  = Array(repeating: 0, count: 120)
        pendingGyro = Array(repeating: 0, count: 120)
        accSamples  = Array(repeating: 0, count: 120)
        gyroSamples = Array(repeating: 0, count: 120)
        dirty = false
    }
}

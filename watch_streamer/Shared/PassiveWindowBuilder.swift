import Foundation

/// One raw accelerometer sample as `CMSensorRecorder` delivers it.
///
/// Deliberately raw acceleration, not `userAcceleration`: the passive
/// recorder only offers the raw signal, and the shipped model was trained on
/// it (`ScrybePassive.json` → `channels: "raw_accel"`). Feeding it
/// gravity-removed data would be a silent distribution mismatch.
public nonisolated struct PassiveSample: Equatable, Sendable {
    public let timestamp: TimeInterval
    public let x: Float
    public let y: Float
    public let z: Float

    public init(timestamp: TimeInterval, x: Float, y: Float, z: Float) {
        self.timestamp = timestamp
        self.x = x
        self.y = y
        self.z = z
    }
}

/// A model-ready window: `seqLen * channels` floats, row-major `(seqLen, 3)`,
/// matching `build_raw_windows` on the training side.
public nonisolated struct PassiveWindow: Equatable, Sendable {
    public let startTimestamp: TimeInterval
    public let endTimestamp: TimeInterval
    public let values: [Float]
}

/// Turns a stream of recorder samples into fixed-length overlapping windows.
///
/// Two properties matter for correctness:
///
/// 1. **A window never straddles a recorder gap.** `CMSensorRecorder` returns
///    whatever it managed to store; a pause leaves a hole. Interpolating across
///    one, or simply concatenating either side, would hand the model five
///    seconds of signal that never happened. The buffer resets instead.
/// 2. **Channel order is x, y, z row-major.** The model's input layout is
///    fixed by the exported artifact, and getting it wrong produces confident
///    nonsense rather than an error.
public nonisolated struct PassiveWindowBuilder {
    public let seqLen: Int
    public let strideSamples: Int
    public let nominalHz: Double
    public let maxGapSeconds: TimeInterval

    private var buffer: [PassiveSample] = []
    private var lastTimestamp: TimeInterval?

    /// - Parameters:
    ///   - seqLen: samples per window (250 for the shipped model).
    ///   - strideSamples: advance between windows; half of `seqLen` gives the
    ///     50 % overlap the training pipeline used.
    ///   - maxGapSeconds: a larger inter-sample delta breaks the window. The
    ///     default is five missing samples at 50 Hz.
    public init(seqLen: Int = 250,
                strideSamples: Int = 125,
                nominalHz: Double = 50,
                maxGapSeconds: TimeInterval = 0.1) {
        self.seqLen = seqLen
        self.strideSamples = max(1, strideSamples)
        self.nominalHz = nominalHz
        self.maxGapSeconds = maxGapSeconds
        buffer.reserveCapacity(seqLen + self.strideSamples)
    }

    /// Seconds of writing time one window is worth. With overlapping windows
    /// the honest unit is the stride, not the window span — otherwise every
    /// second is counted twice.
    public var secondsPerWindow: Double {
        Double(strideSamples) / nominalHz
    }

    public mutating func reset() {
        buffer.removeAll(keepingCapacity: true)
        lastTimestamp = nil
    }

    /// Feeds samples in capture order and returns every window completed by them.
    public mutating func append(_ samples: [PassiveSample]) -> [PassiveWindow] {
        var out: [PassiveWindow] = []
        for sample in samples {
            if let previous = lastTimestamp {
                let delta = sample.timestamp - previous
                // Why: a non-monotonic sample is a recorder artefact, not data.
                // Dropping it keeps the window's time axis meaningful.
                if delta <= 0 { continue }
                if delta > maxGapSeconds {
                    buffer.removeAll(keepingCapacity: true)
                }
            }
            lastTimestamp = sample.timestamp
            buffer.append(sample)

            if buffer.count == seqLen {
                out.append(makeWindow())
                buffer.removeFirst(min(strideSamples, buffer.count))
            }
        }
        return out
    }

    private func makeWindow() -> PassiveWindow {
        var values = [Float](repeating: 0, count: seqLen * 3)
        for (i, s) in buffer.enumerated() {
            let base = i * 3
            values[base] = s.x
            values[base + 1] = s.y
            values[base + 2] = s.z
        }
        return PassiveWindow(startTimestamp: buffer[0].timestamp,
                             endTimestamp: buffer[buffer.count - 1].timestamp,
                             values: values)
    }
}

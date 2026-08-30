import Foundation

/// One six-channel IMU sample, shape depending on who produced it — this
/// type does not fix which signal `x/y/z` carries, only that the model
/// consuming it must be trained on the same one:
/// - `CMSensorRecorder` on the watch supplies raw acceleration (it offers
///   nothing else); the passive model (`ScrybePassive.json`,
///   `channels: "raw_accel"`) is trained on that.
/// - The live watch stream (`PhoneBridge`) supplies `userAcceleration` plus
///   rotation rate; the active model (`ScrybeActive.json`, `channels:
///   "imu"`) is trained on that.
///
/// Feeding either model the other producer's signal would be a silent
/// distribution mismatch.
public nonisolated struct PassiveSample: Equatable, Sendable {
    public let timestamp: TimeInterval
    public let x: Float
    public let y: Float
    public let z: Float
    public let rx: Float
    public let ry: Float
    public let rz: Float

    public init(timestamp: TimeInterval, x: Float, y: Float, z: Float,
                rx: Float = 0, ry: Float = 0, rz: Float = 0) {
        self.timestamp = timestamp
        self.x = x
        self.y = y
        self.z = z
        self.rx = rx
        self.ry = ry
        self.rz = rz
    }
}

/// A model-ready window: `seqLen * channels` floats, row-major
/// `(seqLen, channels)`, matching `build_raw_windows` on the training side.
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
/// 2. **Channel order is fixed by the exported artifact.** 3-channel is
///    x, y, z row-major; 6-channel is ax, ay, az, rx, ry, rz row-major.
///    Getting it wrong produces confident nonsense rather than an error.
public nonisolated struct PassiveWindowBuilder {
    public let seqLen: Int
    public let strideSamples: Int
    public let nominalHz: Double
    public let maxGapSeconds: TimeInterval
    public let channels: Int

    private var buffer: [PassiveSample] = []
    private var lastTimestamp: TimeInterval?

    /// - Parameters:
    ///   - seqLen: samples per window (250 for the shipped model).
    ///   - strideSamples: advance between windows; half of `seqLen` gives the
    ///     50 % overlap the training pipeline used.
    ///   - maxGapSeconds: a larger inter-sample delta breaks the window. The
    ///     default is five missing samples at 50 Hz.
    ///   - channels: 3 (accel only, the shipped passive model) or 6 (accel +
    ///     gyro, the focus-session model).
    public init(seqLen: Int = 250,
                strideSamples: Int = 125,
                nominalHz: Double = 50,
                maxGapSeconds: TimeInterval = 0.1,
                channels: Int = 3) {
        self.seqLen = seqLen
        self.strideSamples = max(1, strideSamples)
        self.nominalHz = nominalHz
        self.maxGapSeconds = maxGapSeconds
        self.channels = channels
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
        var values: [Float] = []
        values.reserveCapacity(seqLen * channels)
        for sample in buffer.prefix(seqLen) {
            values.append(sample.x); values.append(sample.y); values.append(sample.z)
            if channels == 6 {
                values.append(sample.rx); values.append(sample.ry); values.append(sample.rz)
            }
        }
        return PassiveWindow(startTimestamp: buffer[0].timestamp,
                             endTimestamp: buffer[buffer.count - 1].timestamp,
                             values: values)
    }
}

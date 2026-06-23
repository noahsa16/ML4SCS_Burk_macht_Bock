import Combine
import SwiftUI

@MainActor
final class OperationsLogger {
    static let shared = OperationsLogger()
    private var bag = Set<AnyCancellable>()
    private let log = FTLogStore.shared
    private let palette = ScrybeTheme.standard

    private init() {
        let server = ServerCommandListener.shared
        let bridge = PhoneBridge.shared

        server.$isConnected.removeDuplicates().dropFirst().sink { [palette, log] up in
            log.add("WS", up ? "Server verbunden" : "Server getrennt",
                    color: up ? palette.success : palette.danger)
        }.store(in: &bag)

        server.$currentSessionId.removeDuplicates().dropFirst().sink { [palette, log] sid in
            if let sid { log.add("SESSION", "Start \(sid)", color: palette.accent) }
            else { log.add("SESSION", "Stop", color: palette.sepia) }
        }.store(in: &bag)

        server.$watchPolling.removeDuplicates().dropFirst().sink { [palette, log] fresh in
            log.add("WATCH", fresh ? "Watch-Poll frisch" : "Watch-Poll veraltet",
                    color: fresh ? palette.success : palette.warning)
        }.store(in: &bag)

        bridge.$droppedBatchCount.removeDuplicates().dropFirst().sink { [palette, log] n in
            if n > 0 { log.add("DATA", "Verworfen: \(n) Batches", color: palette.danger) }
        }.store(in: &bag)
    }
}

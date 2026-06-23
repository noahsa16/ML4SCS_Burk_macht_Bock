import SwiftUI

@main
struct ScrybeApp: App {
    init() {
        // Eagerly activate WCSession + WS before any view (preserved from WatchStreamerApp).
        _ = PhoneBridge.shared
        _ = ServerCommandListener.shared
        _ = OperationsLogger.shared
    }

    var body: some Scene {
        WindowGroup {
            ScrybeLocaleProvider {
                ScrybeThemeProvider { RootPagerView() }
            }
        }
    }
}

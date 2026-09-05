import SwiftUI

@main
struct ScrybeApp: App {
    init() {
        // Eagerly activate WCSession + WS before any view (preserved from WatchStreamerApp).
        _ = PhoneBridge.shared
        _ = ServerCommandListener.shared
        _ = OperationsLogger.shared
        // Why: every Scrybe screen is a ScrollView, and UIScrollView holds a
        // touch back for ~150 ms to decide whether it is a drag. A button
        // inside one therefore showed no pressed state on a quick tap. With
        // the delay off the button highlights at once; a touch that turns
        // into a drag is still cancelled and scrolls.
        UIScrollView.appearance().delaysContentTouches = false
    }

    var body: some Scene {
        WindowGroup {
            ScrybeLocaleProvider {
                ScrybeThemeProvider { RootPagerView() }
            }
        }
    }
}

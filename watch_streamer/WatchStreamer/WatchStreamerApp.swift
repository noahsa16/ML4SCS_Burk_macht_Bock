//
//  WatchStreamerApp.swift
//  WatchStreamer
//
//  Created by Noah Samel on 30.04.26.
//

import SwiftUI

@main
struct WatchStreamerApp: App {
    init() {
        // Eagerly activate WCSession before any view is created.
        // PhoneBridge.shared sets WCSession.default.delegate and calls activate().
        _ = PhoneBridge.shared
    }

    var body: some Scene {
        WindowGroup {
            iPhoneView()
        }
    }
}

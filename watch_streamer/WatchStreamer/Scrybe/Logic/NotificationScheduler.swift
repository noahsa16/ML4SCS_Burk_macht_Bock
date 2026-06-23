import Foundation
import UserNotifications

/// Daily writing reminder via a repeating local notification. Fires once a day
/// at the chosen time (a gentle nudge; it does not check goal state at fire time).
enum NotificationScheduler {
    static let reminderId = "scrybe.dailyReminder"

    static func requestAuthorization() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound])
        } catch {
            return false
        }
    }

    static func schedule(minutes: Int) {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [reminderId])

        var comps = DateComponents()
        comps.hour = minutes / 60
        comps.minute = minutes % 60

        let content = UNMutableNotificationContent()
        content.title = "Scrybe"
        content.body = "Zeit zu schreiben — dein Tagesziel wartet."
        content.sound = .default

        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: true)
        center.add(UNNotificationRequest(identifier: reminderId, content: content, trigger: trigger))
    }

    static func cancel() {
        UNUserNotificationCenter.current()
            .removePendingNotificationRequests(withIdentifiers: [reminderId])
    }
}

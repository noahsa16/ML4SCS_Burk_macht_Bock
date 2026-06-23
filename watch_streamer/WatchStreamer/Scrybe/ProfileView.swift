import SwiftUI

struct ProfileView: View {
    @Environment(\.scrybe) private var theme
    @State private var adminPresented = false
    @State private var adminUnlocked = false

    var body: some View {
        ScrollView {
            ScrybeGlassGroup(spacing: 24) {
                VStack(spacing: 24) {
                    GoalSettingCard()
                    ReminderCard()
                    WatchConnectionCard()
                    PreferencesCard()
                    PrivacyCard()
                    footer
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .background { theme.paper.ignoresSafeArea() }
        .fullScreenCover(isPresented: $adminPresented, onDismiss: { adminUnlocked = false }) {
            ScrybeThemeProvider {
                if adminUnlocked {
                    AdminPanelView(onExit: { adminPresented = false })
                } else {
                    AdminGateView(onUnlock: { adminUnlocked = true })
                }
            }
        }
    }

    // Hidden admin entry — long-press the version line (invisible affordance).
    private var footer: some View {
        Text("Scrybe \(appVersion)")
            .font(.caption2)
            .foregroundStyle(theme.mutedInk)
            .padding(.top, 8)
            .onLongPressGesture(minimumDuration: 2.0) { adminPresented = true }
            .accessibilityHint("Lang drücken öffnet den Admin-Bereich")
    }

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    }
}

private struct ProfileCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline).foregroundStyle(theme.ink)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }
}

/// Editable daily writing goal; the Heute ring runs against this value.
private struct GoalSettingCard: View {
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var goalMinutes: Double { (goalSeconds / 60).rounded() }

    var body: some View {
        ProfileCard(title: "Tagesziel") {
            HStack {
                Text(TimeFormatting.human(seconds: goalSeconds))
                    .font(.system(.title2, design: .serif))
                    .foregroundStyle(theme.accent)
                    .contentTransition(.numericText())
                Spacer()
                Stepper("",
                        value: Binding(get: { goalMinutes },
                                       set: { goalSeconds = $0 * 60 }),
                        in: 5...480, step: 5)
                    .labelsHidden()
                    .accessibilityLabel("Tagesziel in Minuten")
                    .accessibilityValue("\(Int(goalMinutes)) Minuten")
            }
        }
    }
}

private struct ReminderCard: View {
    @AppStorage(ScrybeSettings.reminderEnabledKey) private var enabled = false
    @AppStorage(ScrybeSettings.reminderMinutesKey) private var minutes = ScrybeSettings.defaultReminderMinutes
    @Environment(\.scrybe) private var theme

    private var time: Binding<Date> {
        Binding(
            get: {
                var c = DateComponents(); c.hour = minutes / 60; c.minute = minutes % 60
                return Calendar.current.date(from: c) ?? Date()
            },
            set: { newDate in
                let c = Calendar.current.dateComponents([.hour, .minute], from: newDate)
                minutes = (c.hour ?? 0) * 60 + (c.minute ?? 0)
                if enabled { NotificationScheduler.schedule(minutes: minutes) }
            })
    }

    var body: some View {
        ProfileCard(title: "Erinnerung") {
            Toggle("Tägliche Erinnerung", isOn: $enabled)
                .tint(theme.accent)
            if enabled {
                DatePicker("Uhrzeit", selection: time, displayedComponents: .hourAndMinute)
            }
        }
        .onChange(of: enabled) { on in
            if on {
                Task {
                    if await NotificationScheduler.requestAuthorization() {
                        NotificationScheduler.schedule(minutes: minutes)
                    } else {
                        enabled = false
                    }
                }
            } else {
                NotificationScheduler.cancel()
            }
        }
    }
}

private struct WatchConnectionCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @Environment(\.scrybe) private var theme

    private var connected: Bool { server.watchPolling }
    private var statusText: String { connected ? "Watch verbunden" : "Watch getrennt" }

    var body: some View {
        ProfileCard(title: "Watch") {
            HStack(spacing: 12) {
                Image(systemName: "applewatch")
                    .font(.title3)
                    .foregroundStyle(connected ? theme.success : theme.mutedInk)
                Text(statusText).font(.subheadline).foregroundStyle(theme.ink)
                Spacer()
            }
            .accessibilityElement(children: .combine)
        }
    }
}

private struct PreferencesCard: View {
    @AppStorage(ScrybeSettings.languageKey) private var language = ScrybeSettings.defaultLanguage
    @AppStorage(ScrybeSettings.weekStartKey) private var weekStart = ScrybeSettings.defaultWeekStart
    @Environment(\.scrybe) private var theme

    var body: some View {
        ProfileCard(title: "Einstellungen") {
            Picker("Sprache", selection: $language) {
                Text("System").tag("system")
                Text("Deutsch").tag("de")
                Text("English").tag("en")
            }
            Picker("Wochenstart", selection: $weekStart) {
                Text("Montag").tag(2)
                Text("Sonntag").tag(1)
            }
        }
        .tint(theme.accent)
    }
}

private struct PrivacyCard: View {
    @Environment(\.scrybe) private var theme
    @State private var confirmReset = false

    var body: some View {
        ProfileCard(title: "Datenschutz") {
            Text("Deine Bewegungsdaten werden nur zur Schreiberkennung verarbeitet und nicht an Dritte weitergegeben.")
                .font(.footnote).foregroundStyle(theme.sepia)
            ShareLink(item: exportJSON()) {
                Label("Daten exportieren", systemImage: "square.and.arrow.up")
                    .font(.subheadline)
            }
            Button(role: .destructive) { confirmReset = true } label: {
                Label("Lokale Einstellungen zurücksetzen", systemImage: "trash")
                    .font(.subheadline)
            }
        }
        .confirmationDialog("Lokale Einstellungen zurücksetzen?",
                            isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Zurücksetzen", role: .destructive, action: resetLocal)
            Button("Abbrechen", role: .cancel) {}
        }
    }

    private func exportJSON() -> String {
        var obj: [String: Any] = [:]
        if let days = FocusStore.shared.history?.days {
            obj["days"] = days.map { ["date": $0.date, "writing_seconds": $0.writingSeconds] }
        }
        let data = (try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted])) ?? Data()
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    private func resetLocal() {
        let d = UserDefaults.standard
        [ScrybeSettings.goalKey, ScrybeSettings.reminderEnabledKey,
         ScrybeSettings.reminderMinutesKey, ScrybeSettings.languageKey,
         ScrybeSettings.weekStartKey].forEach { d.removeObject(forKey: $0) }
        NotificationScheduler.cancel()
    }
}

#Preview {
    ProfileView().scrybeTheme()
}

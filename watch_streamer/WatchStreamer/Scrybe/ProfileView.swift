import SwiftUI

struct ProfileView: View {
    @Environment(\.scrybe) private var theme
    @State private var adminPresented = false
    @State private var adminUnlocked = false
    @State private var secretTaps = 0
    @State private var lastSecretTapAt = Date.distantPast

    private static let secretTapCount = 5
    private static let secretTapWindow: TimeInterval = 1.5

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

    // Hidden admin entry: five deliberate taps on the version line open the
    // operator panel. A timed long-press proved unreliable; a tap count is robust
    // and the line still reads as a plain version string to a proband.
    private var footer: some View {
        Text("Scrybe \(appVersion)")
            .font(.caption2)
            .foregroundStyle(theme.mutedInk)
            .padding(.top, 8)
            .contentShape(Rectangle())
            .onTapGesture { registerSecretTap() }
            // Why: the visible element still reads as a plain version string,
            // so a proband learns nothing. But a five-tap gesture on unlabelled
            // text is unreachable with VoiceOver, Switch Control, Voice Control
            // or a keyboard, which locked operators who use them out of the
            // panel entirely. A custom action is offered only to assistive
            // technology, where it is a rotor entry rather than visible UI.
            .accessibilityLabel("Scrybe \(appVersion)")
            .accessibilityAction(named: Text("Betriebsmodus öffnen")) {
                adminPresented = true
            }
    }

    private func registerSecretTap() {
        // Why: reset unless taps arrive as a deliberate run (≤ window apart), so the
        // operator taps at a natural pace instead of nailing five system-fast taps.
        if Date().timeIntervalSince(lastSecretTapAt) > Self.secretTapWindow { secretTaps = 0 }
        lastSecretTapAt = Date()
        secretTaps += 1
        if secretTaps >= Self.secretTapCount {
            secretTaps = 0
            adminPresented = true
        }
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
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme
    @State private var confirmReset = false
    @State private var confirmDelete = false

    var body: some View {
        ProfileCard(title: "Datenschutz") {
            // Why this wording: the previous paragraph said only that data is
            // not shared, while raw motion sat backup-eligible in Documents
            // and the reset button removed five preference keys. Storage,
            // backup and scope are now stated as they actually are.
            Text("Deine Bewegungsdaten werden nur zur Schreiberkennung verarbeitet und nicht an Dritte weitergegeben. Noch nicht hochgeladene Rohdaten liegen geschützt auf diesem Gerät und werden nicht in Backups aufgenommen.")
                .font(.footnote).foregroundStyle(theme.secondaryInk)

            if let file = exportFile {
                ShareLink(item: file) {
                    Label("Daten exportieren", systemImage: "square.and.arrow.up")
                        .font(.subheadline)
                }
            } else {
                Label("Export nicht möglich", systemImage: "exclamationmark.triangle")
                    .font(.subheadline)
                    .foregroundStyle(theme.danger)
            }
            Text("Als JSON-Datei: Schreibzeit pro Tag, heutige Schreibphasen und deine Einstellungen. Keine Rohbewegungsdaten.")
                .font(.caption2).foregroundStyle(theme.secondaryInk)

            Button(role: .destructive) { confirmReset = true } label: {
                Label("Einstellungen zurücksetzen", systemImage: "arrow.counterclockwise")
                    .font(.subheadline)
            }
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Alle lokalen Daten löschen", systemImage: "trash")
                    .font(.subheadline)
            }
        }
        .confirmationDialog("Einstellungen zurücksetzen?",
                            isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Zurücksetzen", role: .destructive, action: resetSettings)
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Setzt Tagesziel, Erinnerung, Sprache und Wochenstart zurück. Aufgezeichnete Daten bleiben erhalten.")
        }
        .confirmationDialog("Alle lokalen Daten löschen?",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Löschen", role: .destructive, action: deleteLocalData)
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Löscht noch nicht hochgeladene Rohdaten und alle Einstellungen auf diesem iPhone. Bereits auf den Server übertragene Aufnahmen sind davon nicht betroffen.")
        }
    }

    private var exportFile: URL? {
        ScrybeExport.writeTemporaryFile(history: focus.history, today: focus.today)
    }

    private func resetSettings() {
        let d = UserDefaults.standard
        [ScrybeSettings.goalKey, ScrybeSettings.reminderEnabledKey,
         ScrybeSettings.reminderMinutesKey, ScrybeSettings.languageKey,
         ScrybeSettings.weekStartKey].forEach { d.removeObject(forKey: $0) }
        NotificationScheduler.cancel()
    }

    private func deleteLocalData() {
        resetSettings()
        PhoneBridge.shared.deleteAllLocalData()
    }
}

#Preview {
    ProfileView().scrybeTheme()
}

import PhotosUI
import SwiftUI

/// Profile and settings, opened from the header's profile circle.
///
/// Reads top to bottom the way the design intends: who is writing (picture and
/// balance), what they have drawn (the collection), then the settings that
/// shape the pages — each section under a tracked caption, separated by a
/// hairline rule rather than boxed into a card.
struct ProfileView: View {
    /// Set when shown as a sheet; drives the header's close control.
    var onClose: (() -> Void)? = nil

    @Environment(\.scrybe) private var theme
    @State private var adminPresented = false
    @State private var adminUnlocked = false
    @State private var secretTaps = 0
    @State private var path = NavigationPath()
    @State private var lastSecretTapAt = Date.distantPast

    private static let secretTapCount = 5
    private static let secretTapWindow: TimeInterval = 1.5

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    ScrybeHeader(label: "Profil", showsProfileEntry: false, onClose: onClose)
                    IdentitySection()
                    ScrybeRule()
                    BalanceSection()
                    ScrybeRule()
                    CollectionSection()
                    ScrybeRule()
                    GoalSection()
                    ScrybeRule()
                    ReminderSection()
                    ScrybeRule()
                    WatchSection()
                    ScrybeRule()
                    PreferencesSection()
                    ScrybeRule()
                    PrivacySection()
                    footer
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background { theme.paper.ignoresSafeArea() }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: BestiaryDestination.self) { _ in BestiaryView() }
        }
        #if DEBUG
        .onAppear {
            switch DebugFixture.initialScreen {
            case .bestiary: path.append(BestiaryDestination())
            case .admin: adminUnlocked = true; adminPresented = true
            case .adminGate: adminPresented = true
            default: break
            }
        }
        #endif
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
            .frame(maxWidth: .infinity)
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

// MARK: - Identity

/// The picture the header circle shows, and the way to change it.
private struct IdentitySection: View {
    @ObservedObject private var avatar = ProfileAvatarStore.shared
    @Environment(\.scrybe) private var theme
    @State private var picked: PhotosPickerItem?
    @State private var pickerShown = false

    var body: some View {
        VStack(spacing: 14) {
            // A Button plus the `.photosPicker` modifier rather than the
            // `PhotosPicker` view: its label closure is not main-actor
            // isolated, so the theme lookups inside it do not compile in
            // Swift 6.
            Button { pickerShown = true } label: {
                ProfileAvatar(side: 84)
                    .overlay(alignment: .bottomTrailing) {
                        Image(systemName: "camera.fill")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(theme.paperTop)
                            .frame(width: 24, height: 24)
                            .background(Circle().fill(theme.accent))
                            .overlay(Circle().stroke(theme.paperTop, lineWidth: 2))
                            .accessibilityHidden(true)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Profilbild ändern")
            .photosPicker(isPresented: $pickerShown, selection: $picked,
                          matching: .images, photoLibrary: .shared())

            HStack(spacing: 16) {
                Text("Profilbild").scrybeCaption()
                if avatar.image != nil {
                    Text("·").foregroundStyle(theme.mutedInk)
                    Button("Entfernen") { avatar.clear() }
                        .buttonStyle(.plain)
                        .font(.caption)
                        .foregroundStyle(theme.secondaryInk)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .onChange(of: picked) { item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    avatar.set(imageData: data)
                }
                picked = nil
            }
        }
    }
}

// MARK: - Balance

/// Lifetime figures: everything written, on how many days, and the longest
/// run of goal-met days. The one place the app adds up the whole history.
private struct BalanceSection: View {
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme

    private var days: [FocusDayDTO] { focus.history?.days ?? [] }
    private var totalSeconds: Double { days.reduce(0) { $0 + $1.writingSeconds } }
    private var activeDays: Int { days.filter { $0.writingSeconds > 0 }.count }
    private var firstActive: String? {
        days.first { $0.writingSeconds > 0 }.map { DateFormatting.dayMonth(iso: $0.date) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ScrybeSectionHeader("Schreibbilanz") {
                if let firstActive {
                    Text("seit \(firstActive)").scrybeMarginNote(.footnote)
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                figure {
                    DurationFigure(seconds: totalSeconds, size: 34)
                } caption: {
                    Text("Gesamt").scrybeCaption()
                }
                divider
                figure {
                    Text("\(activeDays)").scrybeDisplayFigure(size: 34)
                } caption: {
                    Text("Schreibtage").scrybeCaption()
                }
                divider
                figure {
                    Text("\(focus.longestStreak)").scrybeDisplayFigure(size: 34)
                } caption: {
                    Text("Bester Streak").scrybeCaption()
                }
            }
            .accessibilityElement(children: .combine)
        }
    }

    private func figure<F: View, C: View>(@ViewBuilder _ figure: () -> F,
                                          @ViewBuilder caption: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            figure()
            caption()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var divider: some View {
        Rectangle().fill(theme.hairline).frame(width: 1, height: 36)
            .padding(.trailing, 12)
    }
}

// MARK: - Collection

private struct CollectionSection: View {
    @ObservedObject private var bestiary = BestiaryStore.shared
    @Environment(\.scrybe) private var theme

    private static let shownOnProfile = 4
    private var entries: [BestiaryEntry] { bestiary.visible }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ScrybeSectionHeader("Sammlung · \(bestiary.completed.count) gesammelt") {
                if entries.count > Self.shownOnProfile {
                    NavigationLink(value: BestiaryDestination()) {
                        Text("Alle ansehen").scrybeMarginNote(.footnote)
                    }
                    .buttonStyle(.plain)
                }
            }
            if entries.isEmpty {
                EmptyCreatureCard()
            } else {
                CreatureCollectionGrid(entries: Array(entries.prefix(Self.shownOnProfile)))
            }
            Text("Jede Kreatur entsteht aus echter Schreibzeit.")
                .scrybeMarginNote(.footnote)
                .frame(maxWidth: .infinity)
        }
    }
}

// MARK: - Goal

/// The daily goal the Heute ring runs against, stepped in five-minute moves.
private struct GoalSection: View {
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private static let stepSeconds: Double = 5 * 60
    private static let range: ClosedRange<Double> = (5 * 60)...(480 * 60)

    private var goalMinutes: Int { Int(goalSeconds / 60) }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ScrybeSectionHeader("Tagesziel")
            HStack(alignment: .center) {
                DurationFigure(seconds: goalSeconds, size: 44)
                Spacer()
                stepper
            }
            .accessibilityElement(children: .contain)
        }
    }

    /// A ruled pill with "−" and "+", replacing the stock `Stepper`, whose
    /// grey UIKit chrome was the one foreign object on the page.
    private var stepper: some View {
        HStack(spacing: 0) {
            stepButton("minus", label: "Tagesziel verringern") { step(-Self.stepSeconds) }
            Rectangle().fill(theme.hairline).frame(width: 1, height: 20)
            stepButton("plus", label: "Tagesziel erhöhen") { step(Self.stepSeconds) }
        }
        .background(Capsule().stroke(theme.sepia.opacity(0.5), lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Tagesziel in Minuten")
        .accessibilityValue("\(goalMinutes) Minuten")
    }

    private func stepButton(_ symbol: String, label: LocalizedStringKey,
                            action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(theme.ink)
                .frame(width: 52, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private func step(_ delta: Double) {
        let next = min(Self.range.upperBound, max(Self.range.lowerBound, goalSeconds + delta))
        guard next != goalSeconds else { return }
        UISelectionFeedbackGenerator().selectionChanged()
        goalSeconds = next
    }
}

// MARK: - Reminder

private struct ReminderSection: View {
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
        VStack(alignment: .leading, spacing: 14) {
            ScrybeSectionHeader("Erinnerung")
            Toggle(isOn: Binding(get: { enabled }, set: { setReminder($0) })) {
                Text("Tägliche Erinnerung")
                    .font(.system(.body, design: .serif))
                    .foregroundStyle(theme.ink)
            }
            .tint(theme.accent)
            if enabled {
                DatePicker(selection: time, displayedComponents: .hourAndMinute) {
                    Text("Uhrzeit")
                        .font(.system(.body, design: .serif))
                        .foregroundStyle(theme.ink)
                }
                .tint(theme.accent)
            }
            Text("Ein täglicher Anstoß, falls dein Ziel noch offen ist.")
                .scrybeMarginNote(.footnote)
        }
    }

    /// Driven from the toggle rather than from `onChange`: the stored value is
    /// re-published while the sheet appears, and an observer on it asked for
    /// the notification permission before anyone had touched the switch.
    private func setReminder(_ on: Bool) {
        guard on else {
            enabled = false
            NotificationScheduler.cancel()
            return
        }
        enabled = true
        Task {
            if await NotificationScheduler.requestAuthorization() {
                NotificationScheduler.schedule(minutes: minutes)
            } else {
                enabled = false
            }
        }
    }
}

// MARK: - Watch

private struct WatchSection: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme

    /// The same definition the header glyph uses, so the two never disagree.
    private var connected: Bool { server.watchPolling || bridge.isConnected }
    private var statusText: LocalizedStringKey { connected ? "Watch verbunden" : "Watch getrennt" }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ScrybeSectionHeader("Watch")
            HStack(spacing: 12) {
                Circle()
                    .fill(connected ? theme.success : theme.goalReached)
                    .frame(width: 9, height: 9)
                Text(statusText)
                    .font(.system(.body, design: .serif))
                    .foregroundStyle(theme.ink)
                Spacer()
                if !connected {
                    Button { server.reconnectAndRefresh() } label: {
                        Text("Verbinden").scrybeCaption()
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: 44)
                }
            }
            .accessibilityElement(children: .combine)
            if let at = focus.lastWritingAt {
                Text("Zuletzt geschrieben \(at.formatted(date: .omitted, time: .shortened))")
                    .scrybeMarginNote(.footnote)
            }
        }
    }
}

// MARK: - Preferences

private struct PreferencesSection: View {
    @AppStorage(ScrybeSettings.languageKey) private var language = ScrybeSettings.defaultLanguage
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ScrybeSectionHeader("Einstellungen")
            preference("Sprache") {
                SerifSegmentedControl(
                    options: [("system", "System"), ("de", "Deutsch"), ("en", "English")],
                    selection: $language)
            }
        }
    }

    private func preference<C: View>(_ title: LocalizedStringKey,
                                     @ViewBuilder control: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(.body, design: .serif))
                .foregroundStyle(theme.ink)
            control()
        }
    }
}

// MARK: - Privacy

private struct PrivacySection: View {
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme
    @State private var confirmReset = false
    @State private var confirmDelete = false
    @State private var exportFile: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ScrybeSectionHeader("Datenschutz")
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
                .foregroundStyle(theme.accent)
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
            .frame(minHeight: 44)
            Button(role: .destructive) { confirmDelete = true } label: {
                Label("Alle lokalen Daten löschen", systemImage: "trash")
                    .font(.subheadline)
            }
            .frame(minHeight: 44)
        }
        .confirmationDialog("Einstellungen zurücksetzen?",
                            isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Zurücksetzen", role: .destructive, action: resetSettings)
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Setzt Tagesziel, Erinnerung und Sprache zurück. Aufgezeichnete Daten bleiben erhalten.")
        }
        .confirmationDialog("Alle lokalen Daten löschen?",
                            isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Löschen", role: .destructive, action: deleteLocalData)
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Löscht deine gesamte Schreibzeit-Historie, dein Bestiarium, noch nicht hochgeladene Rohdaten und alle Einstellungen auf diesem iPhone. Bereits auf den Server übertragene Aufnahmen sind davon nicht betroffen.")
        }
        .onAppear(perform: prepareExport)
        .onChange(of: focus.lastUpdated) { _ in prepareExport() }
    }

    private func prepareExport() {
        exportFile = ScrybeExport.writeTemporaryFile(history: focus.history, today: focus.today)
    }

    private func resetSettings() {
        let d = UserDefaults.standard
        ScrybeSettings.resettableKeys.forEach { d.removeObject(forKey: $0) }
        NotificationScheduler.cancel()
    }

    private func deleteLocalData() {
        resetSettings()
        PhoneBridge.shared.deleteAllLocalData()
        ProfileAvatarStore.shared.clear()
        Task {
            await focus.deleteAllLocalData()
            // The collection is its own file, so it survives every other erase
            // here — and a bestiary that outlives a deletion the user was told
            // was total is the surprise this whole dialog exists to prevent.
            BestiaryStore.shared.deleteAll()
        }
    }
}

#Preview {
    ProfileView(onClose: {}).scrybeTheme()
}

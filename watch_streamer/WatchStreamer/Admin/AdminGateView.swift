import SwiftUI

struct AdminGateView: View {
    var onUnlock: () -> Void

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ScaledMetric(relativeTo: .largeTitle) private var lockSize: CGFloat = 40
    @State private var entry = ""
    @State private var error = false
    /// Set once the default PIN has been accepted and a replacement is due.
    @State private var settingNewPIN = false
    @State private var firstNewPIN: String?
    @State private var errorResetTask: Task<Void, Never>?
    private let pinLength = 4

    private var title: String {
        guard settingNewPIN else { return "Admin" }
        return firstNewPIN == nil ? "Neue PIN wählen" : "Neue PIN bestätigen"
    }

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: settingNewPIN ? "lock.rotation" : "lock")
                .font(.system(size: lockSize))
                .foregroundStyle(theme.accent)
                .accessibilityHidden(true)
            Text(title)
                .font(.system(.title2, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)

            // Why stated here: the source comment already said this is not a
            // security feature. The operator standing in front of it should
            // know that too, rather than inferring protection from a keypad.
            Text(settingNewPIN
                 ? "Die Standard-PIN darf nicht bestehen bleiben."
                 : "Bedienzugang, kein Sicherheitsmerkmal.")
                .font(.caption)
                .foregroundStyle(theme.secondaryInk)
                .multilineTextAlignment(.center)

            HStack(spacing: 16) {
                ForEach(0..<pinLength, id: \.self) { i in
                    Circle()
                        .fill(i < entry.count ? theme.ink : theme.mutedInk)
                        .frame(width: 14, height: 14)
                }
            }
            .modifier(Shake(animatableData: error ? 1 : 0))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("PIN")
            .accessibilityValue("\(entry.count) von \(pinLength)")

            PinKeypad(onDigit: append, onDelete: { entry = String(entry.dropLast()) })
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background { theme.paper.ignoresSafeArea() }
        .onDisappear { errorResetTask?.cancel() }
    }

    private func append(_ d: String) {
        guard entry.count < pinLength else { return }
        entry += d
        guard entry.count == pinLength else { return }
        settingNewPIN ? captureNewPIN() : verify()
    }

    private func verify() {
        guard entry == ScrybeSettings.adminPIN else {
            reject("Falsche PIN")
            return
        }
        entry = ""
        // Why: a build that ships with 0000 and never asks for a change leaves
        // the published default as the live credential. Accepting it once is
        // the moment to replace it.
        if ScrybeSettings.hasCustomPIN {
            onUnlock()
        } else {
            settingNewPIN = true
        }
    }

    private func captureNewPIN() {
        guard let first = firstNewPIN else {
            guard entry != ScrybeSettings.defaultPIN else {
                reject("Bitte eine andere PIN wählen")
                return
            }
            firstNewPIN = entry
            entry = ""
            return
        }
        guard entry == first else {
            firstNewPIN = nil
            reject("PINs stimmen nicht überein")
            return
        }
        ScrybeSettings.setAdminPIN(entry)
        entry = ""
        settingNewPIN = false
        firstNewPIN = nil
        onUnlock()
    }

    private func reject(_ message: String) {
        withAnimation(reduceMotion ? nil : .default) { error = true }
        entry = ""
        UIAccessibility.post(notification: .announcement, argument: message)
        // Why a cancellable task: the previous asyncAfter could land after the
        // view was gone and re-apply a stale animation state.
        errorResetTask?.cancel()
        errorResetTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled else { return }
            error = false
        }
    }
}

private struct PinKeypad: View {
    var onDigit: (String) -> Void
    var onDelete: () -> Void

    @Environment(\.scrybe) private var theme
    private let rows = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["", "0", "⌫"]]

    var body: some View {
        ScrybeGlassGroup(spacing: 16) {
            VStack(spacing: 16) {
                ForEach(rows, id: \.self) { row in
                    HStack(spacing: 24) {
                        ForEach(row, id: \.self) { key in keyButton(key) }
                    }
                }
            }
        }
    }

    @ViewBuilder private func keyButton(_ key: String) -> some View {
        if key.isEmpty {
            Color.clear.frame(width: 64, height: 64).accessibilityHidden(true)
        } else if key == "⌫" {
            Button(action: onDelete) {
                Image(systemName: "delete.left")
                    .font(.title2)
                    .frame(width: 64, height: 64)
                    .foregroundStyle(theme.ink)
            }
            .accessibilityLabel("Letzte Ziffer löschen")
        } else {
            Button { onDigit(key) } label: {
                Text(key)
                    .font(.system(.title, design: .serif))
                    .frame(width: 64, height: 64)
                    .foregroundStyle(theme.ink)
                    .scrybeCapsuleSurface(interactive: true)
            }
        }
    }
}

private struct Shake: GeometryEffect {
    var animatableData: CGFloat
    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 8 * sin(animatableData * .pi * 4), y: 0))
    }
}

#Preview {
    AdminGateView(onUnlock: {}).scrybeTheme()
}

import SwiftUI

struct AdminGateView: View {
    var onUnlock: () -> Void

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ScaledMetric(relativeTo: .largeTitle) private var lockSize: CGFloat = 40
    @State private var entry = ""
    @State private var error = false
    private let pinLength = 4

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "lock")
                .font(.system(size: lockSize))
                .foregroundStyle(theme.accent)
                .accessibilityHidden(true)
            Text("Admin")
                .font(.system(.title2, design: .serif))
                .foregroundStyle(theme.ink)

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
    }

    private func append(_ d: String) {
        guard entry.count < pinLength else { return }
        entry += d
        if entry.count == pinLength { verify() }
    }

    private func verify() {
        if entry == ScrybeSettings.adminPIN {
            onUnlock()
        } else {
            withAnimation(reduceMotion ? nil : .default) { error = true }
            entry = ""
            UIAccessibility.post(notification: .announcement, argument: "Falsche PIN")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { error = false }
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

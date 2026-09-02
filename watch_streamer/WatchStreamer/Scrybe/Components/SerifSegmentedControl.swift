import SwiftUI

/// A hairline-ruled pill holding two or three serif switches, where a stock
/// segmented picker used to sit.
///
/// Keeps what `Picker` gave for free: each option is a button, and the
/// selected one announces itself as selected. Losing that would trade an
/// accessibility guarantee for a typeface.
struct SerifSegmentedControl<Value: Hashable>: View {
    let options: [(value: Value, label: String)]
    @Binding var selection: Value

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: 4) {
            ForEach(options, id: \.value) { option in
                let selected = option.value == selection
                Button {
                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) {
                        selection = option.value
                    }
                } label: {
                    Text(LocalizedStringKey(option.label))
                        .font(.system(.body, design: .serif).weight(selected ? .semibold : .regular))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
                .background {
                    if selected {
                        Capsule()
                            .fill(theme.wash(theme.accent))
                            .overlay(Capsule().stroke(theme.accent.opacity(0.35), lineWidth: 1))
                    }
                }
                .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
            }
        }
        .padding(4)
        .background(Capsule().stroke(theme.hairline, lineWidth: 1))
    }
}

#Preview {
    struct Demo: View {
        @State private var pick = "week"
        var body: some View {
            SerifSegmentedControl(options: [("week", "Woche"), ("month", "Monat")],
                                  selection: $pick)
                .padding(24)
                .background(ScrybeTheme.standard.paper)
                .scrybeTheme()
        }
    }
    return Demo()
}

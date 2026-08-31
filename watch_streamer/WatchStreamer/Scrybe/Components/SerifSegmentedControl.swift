import SwiftUI

/// Two tinted serif switches where a stock segmented picker used to sit.
///
/// Keeps what `Picker` gave for free: each option is a button, and the
/// selected one announces itself as selected. Losing that would trade an
/// accessibility guarantee for a typeface.
struct SerifSegmentedControl<Value: Hashable>: View {
    let options: [(value: Value, label: String)]
    @Binding var selection: Value

    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options, id: \.value) { option in
                let selected = option.value == selection
                Button { selection = option.value } label: {
                    Text(LocalizedStringKey(option.label))
                        .font(.system(.subheadline, design: .serif))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
                .background(selected ? theme.wash(theme.accent) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
            }
        }
        .padding(4)
        .background(theme.track, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

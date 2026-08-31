import SwiftUI

/// Presets, a free field and "just write". Opened by tapping the number in
/// the ready screen's sentence, never shown on arrival — the form exists, it
/// is just not the first thing anyone meets.
struct FocusDurationSheet: View {
    @Binding var minutes: Int?
    @Binding var isPresented: Bool

    @Environment(\.scrybe) private var theme
    @State private var freeText = ""
    @State private var failure: FocusDurationInput.Failure?

    private static let presets = [15, 25, 45]

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Wie lange?")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)

            HStack(spacing: 12) {
                ForEach(Self.presets, id: \.self) { preset in
                    presetChip(preset)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    TextField("Minuten", text: $freeText)
                        .keyboardType(.numberPad)
                        .font(.system(.body, design: .serif))
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel(Text("Eigene Dauer in Minuten"))
                    Button("Übernehmen") { applyFreeText() }
                        .buttonStyle(.plain)
                        .foregroundStyle(theme.accent)
                }
                if let failure {
                    Text(FocusDurationInput.message(for: failure))
                        .font(.footnote)
                        .foregroundStyle(theme.danger)
                }
            }

            Button {
                minutes = nil
                isPresented = false
            } label: {
                Text("Einfach schreiben")
                    .font(.system(.body, design: .serif))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.secondaryInk)
            .accessibilityHint(Text("Startet ohne Ziel. Die Sitzung endet, wenn du sie beendest."))
        }
        .padding(20)
        .presentationDetents([.height(320)])
    }

    private func presetChip(_ preset: Int) -> some View {
        let selected = minutes == preset
        return Button {
            minutes = preset
            isPresented = false
        } label: {
            Text("\(preset) Min")
                .font(.system(.body, design: .serif))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
        .background(selected ? theme.wash(theme.accent) : theme.track,
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private func applyFreeText() {
        switch FocusDurationInput.parse(freeText) {
        case .success(let value):
            minutes = value
            failure = nil
            isPresented = false
        case .failure(let reason):
            failure = reason
        }
    }
}

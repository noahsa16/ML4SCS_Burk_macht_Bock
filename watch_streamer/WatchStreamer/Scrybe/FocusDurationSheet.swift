import SwiftUI

/// A free field and "just write". Opened by the fourth pill on the ready
/// screen; the three preset lengths live there, so this sheet only holds
/// what a pill cannot.
struct FocusDurationSheet: View {
    @Binding var minutes: Int?
    @Binding var isPresented: Bool

    @Environment(\.scrybe) private var theme
    @State private var freeText = ""
    @State private var failure: FocusDurationInput.Failure?
    @FocusState private var fieldFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Eigene Dauer").scrybeCaption()
                    Text("Wie lange?")
                        .font(.system(.title2, design: .serif))
                        .foregroundStyle(theme.ink)
                }

                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        TextField("25", text: $freeText)
                            .keyboardType(.numberPad)
                            .font(.system(size: 40, weight: .regular, design: .serif))
                            .foregroundStyle(theme.ink)
                            .focused($fieldFocused)
                            .frame(maxWidth: 120)
                            .accessibilityLabel(Text("Eigene Dauer in Minuten"))
                        Text("Minuten")
                            .font(.system(.title3, design: .serif))
                            .foregroundStyle(theme.secondaryInk)
                        Spacer()
                        Button("Übernehmen") { applyFreeText() }
                            .buttonStyle(.plain)
                            .foregroundStyle(theme.accent)
                            .font(.subheadline.weight(.semibold))
                            .frame(minHeight: 44)
                    }
                    Rectangle().fill(theme.hairline).frame(height: 1)
                    if let failure {
                        Text(FocusDurationInput.message(for: failure))
                            .font(.footnote)
                            .foregroundStyle(theme.danger)
                    } else {
                        Text("Zwischen \(FocusDurationInput.range.lowerBound) und \(FocusDurationInput.range.upperBound) Minuten.")
                            .scrybeMarginNote(.footnote)
                    }
                }

                ScrybeRule()

                Button {
                    minutes = nil
                    isPresented = false
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "infinity")
                            .foregroundStyle(theme.sepia)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Einfach schreiben")
                                .font(.system(.body, design: .serif))
                                .foregroundStyle(theme.ink)
                            Text("Ohne Ziel. Die Sitzung endet, wenn du sie beendest.")
                                .scrybeMarginNote(.footnote)
                        }
                        Spacer()
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .frame(minHeight: 44)
            }
            .padding(24)
        }
        .background { theme.paper.ignoresSafeArea() }
        .presentationDetents([.medium])
        .onAppear { fieldFocused = true }
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

#Preview {
    FocusDurationSheet(minutes: .constant(25), isPresented: .constant(true))
        .scrybeTheme()
}

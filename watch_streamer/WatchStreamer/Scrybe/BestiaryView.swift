import SwiftUI

/// The creatures a writer has drawn, one to a margin at a time — all of
/// them, on their own page. Pushed from the focus tab's footer and from the
/// profile's collection section, both of which own the navigation stack.
///
/// A creature still in progress shows exactly as far as it has been drawn,
/// with the strokes to come traced faintly behind it.
struct BestiaryView: View {
    @ObservedObject private var store = BestiaryStore.shared
    @Environment(\.scrybe) private var theme

    private var entries: [BestiaryEntry] { store.visible }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                ScrybeSectionHeader("Bestiarium") {
                    Text("\(store.completed.count) gesammelt").scrybeMarginNote(.footnote)
                }
                if entries.isEmpty {
                    EmptyCreatureCard()
                } else {
                    CreatureCollectionGrid(entries: entries)
                }
                Text("Jede Kreatur entsteht aus echter Schreibzeit.")
                    .scrybeMarginNote(.footnote)
                    .frame(maxWidth: .infinity)
            }
            .padding(20)
        }
        .background { theme.paper.ignoresSafeArea() }
        .navigationTitle("Bestiarium")
        .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview {
    NavigationStack { BestiaryView().scrybeTheme() }
}

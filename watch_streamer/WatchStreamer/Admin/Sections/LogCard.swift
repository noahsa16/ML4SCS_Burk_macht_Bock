import SwiftUI

struct LogCard: View {
    @ObservedObject private var store = FTLogStore.shared
    @Environment(\.scrybe) private var theme
    private let maxEntries = 8

    var body: some View {
        AdminCard(title: "Protokoll") {
            if store.entries.isEmpty {
                Text("Noch keine Ereignisse.")
                    .font(.caption).foregroundStyle(theme.sepia)
            } else {
                ForEach(store.entries.prefix(maxEntries)) { entry in
                    HStack(alignment: .top, spacing: 8) {
                        Text(entry.timeString)
                            .font(.caption2).monospacedDigit()
                            .foregroundStyle(theme.sepia)
                            .frame(width: 56, alignment: .leading)
                        Text(entry.tag)
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 4)
                            .background(entry.tagColor.opacity(0.12))
                            .foregroundStyle(entry.tagColor)
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                        Text(entry.message)
                            .font(.caption2).foregroundStyle(theme.ink)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }
}

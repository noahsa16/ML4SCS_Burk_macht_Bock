import SwiftUI

/// What the phone actually knows: when writing was last detected, and when the
/// watch last handed data over.
///
/// Replaces the live "schreibt gerade" chip, which the server produced from a
/// 1 Hz stream. Passive decisions come from `CMSensorRecorder`, which is only
/// readable minutes after the fact, so a live claim would be a claim the data
/// cannot support.
struct SyncChip: View {
    let lastWritingAt: Date?
    let lastSyncedAt: Date?
    let unreachable: Bool

    @Environment(\.scrybe) private var theme

    /// Writing this recent still reads as "in progress" to a person.
    private static let recentWindow: TimeInterval = 15 * 60

    private var isRecent: Bool {
        guard let lastWritingAt else { return false }
        return Date().timeIntervalSince(lastWritingAt) < Self.recentWindow
    }

    private var dotColor: Color {
        if unreachable { return theme.warning }
        return isRecent ? theme.success : theme.ink.opacity(0.25)
    }

    private var headline: Text {
        guard let lastWritingAt else { return Text("Noch keine Schreibzeit") }
        return Text("Zuletzt geschrieben \(time(lastWritingAt))")
    }

    private var detail: Text? {
        if unreachable { return Text("Uhr nicht erreichbar") }
        guard let lastSyncedAt else { return nil }
        return Text("abgeglichen \(time(lastSyncedAt))")
    }

    private func time(_ date: Date) -> String {
        date.formatted(date: .omitted, time: .shortened)
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(dotColor).frame(width: 8, height: 8)
            headline
                .font(.footnote.weight(.medium))
                .foregroundStyle(theme.ink)
            if let detail {
                Text("·").foregroundStyle(theme.mutedInk)
                detail.font(.footnote).foregroundStyle(theme.secondaryInk)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .scrybeCapsuleSurface(
            tint: isRecent ? theme.success.opacity(0.16) : theme.ink.opacity(0.05))
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    VStack(spacing: 16) {
        SyncChip(lastWritingAt: Date(), lastSyncedAt: Date(), unreachable: false)
        SyncChip(lastWritingAt: Date().addingTimeInterval(-7200),
                 lastSyncedAt: Date(), unreachable: false)
        SyncChip(lastWritingAt: nil, lastSyncedAt: nil, unreachable: false)
        SyncChip(lastWritingAt: Date().addingTimeInterval(-7200),
                 lastSyncedAt: nil, unreachable: true)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}

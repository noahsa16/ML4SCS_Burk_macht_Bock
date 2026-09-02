import SwiftUI

/// The round profile picture: the chosen photo, or a one-stroke profile glyph
/// on a hairline circle while none is set. Sized by the caller; the header
/// uses it small beside the Watch glyph, the profile page large at the top.
struct ProfileAvatar: View {
    var side: CGFloat = 28

    @ObservedObject private var store = ProfileAvatarStore.shared
    @Environment(\.scrybe) private var theme

    var body: some View {
        ZStack {
            if let image = store.image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Circle().fill(theme.wash(theme.sepia))
                ScrybeGlyphShape(glyph: .profile)
                    .stroke(style: StrokeStyle(lineWidth: max(1.2, side / 22),
                                               lineCap: .round, lineJoin: .round))
                    .foregroundStyle(theme.secondaryInk)
                    .padding(side * 0.18)
            }
        }
        .frame(width: side, height: side)
        .clipShape(Circle())
        .overlay(Circle().stroke(theme.sepia.opacity(0.6), lineWidth: 1))
        .accessibilityHidden(true)
    }
}

#Preview {
    HStack(spacing: 24) {
        ProfileAvatar()
        ProfileAvatar(side: 80)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}

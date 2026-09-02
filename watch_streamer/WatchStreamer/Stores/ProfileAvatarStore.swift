import Combine
import Foundation
import UIKit

/// The picture in the header's profile circle.
///
/// One small JPEG in Application Support, resized on the way in: the header
/// draws it at 28 points and the profile page at about 80, so a camera-sized
/// original would only cost launch time and backup space. Nothing else in the
/// app depends on it — a missing file means the circle shows a monogram.
@MainActor
final class ProfileAvatarStore: ObservableObject {
    static let shared = ProfileAvatarStore(fileURL: ProfileAvatarStore.defaultFileURL())

    @Published private(set) var image: UIImage?

    private let fileURL: URL
    /// Longest side of the stored picture, in pixels.
    static let storedSide: CGFloat = 320

    init(fileURL: URL) {
        self.fileURL = fileURL
        if let data = try? Data(contentsOf: fileURL) {
            image = UIImage(data: data)
        }
    }

    nonisolated static func defaultFileURL() -> URL {
        AppSupportURL.file(named: "avatar.jpg")
    }

    /// Adopts a picked photo; returns `false` when the data is not an image.
    @discardableResult
    func set(imageData: Data) -> Bool {
        guard let picked = UIImage(data: imageData) else { return false }
        let squared = Self.squareThumbnail(picked, side: Self.storedSide)
        image = squared
        if let jpeg = squared.jpegData(compressionQuality: 0.85) {
            try? jpeg.write(to: fileURL, options: .atomic)
        }
        return true
    }

    func clear() {
        image = nil
        try? FileManager.default.removeItem(at: fileURL)
    }

    /// Centre-crops to a square and scales to `side`. Orientation is applied by
    /// drawing, so a portrait photo does not come back sideways.
    private static func squareThumbnail(_ source: UIImage, side: CGFloat) -> UIImage {
        let size = source.size
        let edge = min(size.width, size.height)
        let scale = side / edge
        let drawn = CGSize(width: size.width * scale, height: size.height * scale)
        let origin = CGPoint(x: (side - drawn.width) / 2, y: (side - drawn.height) / 2)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: CGSize(width: side, height: side), format: format)
            .image { _ in source.draw(in: CGRect(origin: origin, size: drawn)) }
    }
}

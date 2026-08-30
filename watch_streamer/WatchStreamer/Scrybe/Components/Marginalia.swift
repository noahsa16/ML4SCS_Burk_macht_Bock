import SwiftUI

/// The creatures a focus session draws in the margin of its page.
///
/// Drolleries: the small beasts medieval scribes drew beside their text. They
/// are hand-authored rather than generated, because a generator produces
/// variations of one shape and that sameness is exactly what makes an interface
/// look machine-made.
///
/// Every path is defined in a 100×100 box using SwiftUI's convention — y counts
/// downward, so a smaller y is higher on the page. The strokes are ordered: a
/// session draws them one at a time as writing time accumulates, so the order is
/// the order a person would draw the animal in, not an arbitrary list.
///
/// Imports nothing but SwiftUI, so `tools/render_marginalia.swift` can compile
/// against this file directly and render the creatures for inspection.
enum Marginalia {

    static let names = [
        "Trompeten-Hase",
        "Panzerschnecke",
        "Dreibein-Vogel",
        "Lesender Greif",
        "Bücherwurm",
        "Mondhund",
        "Federfisch",
        "Zwei-Kopf-Kranich",
    ]

    static func strokeCount(forSpecies id: Int) -> Int {
        strokes(forSpecies: id).count
    }

    static func strokes(forSpecies id: Int) -> [Path] {
        switch id {
        case 0: return trumpetHare
        case 1: return armouredSnail
        case 2: return threeLeggedBird
        case 3: return readingGriffin
        case 4: return bookworm
        case 5: return moonHound
        case 6: return featherFish
        case 7: return twoHeadedCrane
        default: return []
        }
    }

    // MARK: - 0 · Trompeten-Hase

    // A first attempt built the hare from many small strokes and it read as a
    // fish. Rebuilt silhouette-first: one long back, one belly, a head that is
    // its own closed shape. Features come after the outline, never instead.
    private static var trumpetHare: [Path] {
        [
            // back: haunch up to the shoulder
            Path { p in
                p.move(to: CGPoint(x: 22, y: 84))
                p.addCurve(to: CGPoint(x: 56, y: 48),
                           control1: CGPoint(x: 16, y: 56),
                           control2: CGPoint(x: 34, y: 44))
            },
            // belly and chest, closing the body
            Path { p in
                p.move(to: CGPoint(x: 22, y: 84))
                p.addCurve(to: CGPoint(x: 56, y: 48),
                           control1: CGPoint(x: 40, y: 92),
                           control2: CGPoint(x: 58, y: 74))
            },
            // head, sunk into the shoulder rather than floating beside it
            Path { p in
                p.move(to: CGPoint(x: 52, y: 52))
                p.addCurve(to: CGPoint(x: 76, y: 44),
                           control1: CGPoint(x: 58, y: 34),
                           control2: CGPoint(x: 76, y: 32))
                p.addCurve(to: CGPoint(x: 54, y: 58),
                           control1: CGPoint(x: 76, y: 54),
                           control2: CGPoint(x: 62, y: 58))
            },
            // near ear: a closed leaf, which is what makes a hare a hare
            Path { p in
                p.move(to: CGPoint(x: 58, y: 38))
                p.addCurve(to: CGPoint(x: 50, y: 8),
                           control1: CGPoint(x: 50, y: 30),
                           control2: CGPoint(x: 44, y: 14))
                p.addCurve(to: CGPoint(x: 62, y: 36),
                           control1: CGPoint(x: 58, y: 16),
                           control2: CGPoint(x: 62, y: 24))
            },
            // far ear
            Path { p in
                p.move(to: CGPoint(x: 66, y: 36))
                p.addCurve(to: CGPoint(x: 72, y: 12),
                           control1: CGPoint(x: 66, y: 26),
                           control2: CGPoint(x: 70, y: 18))
                p.addCurve(to: CGPoint(x: 70, y: 36),
                           control1: CGPoint(x: 76, y: 20),
                           control2: CGPoint(x: 76, y: 30))
            },
            // foreleg
            Path { p in
                p.move(to: CGPoint(x: 52, y: 66))
                p.addCurve(to: CGPoint(x: 54, y: 88),
                           control1: CGPoint(x: 48, y: 76),
                           control2: CGPoint(x: 50, y: 82))
            },
            // haunch fold
            Path { p in
                p.move(to: CGPoint(x: 26, y: 68))
                p.addCurve(to: CGPoint(x: 36, y: 86),
                           control1: CGPoint(x: 30, y: 78),
                           control2: CGPoint(x: 30, y: 84))
            },
            // trumpet, held out from the muzzle
            Path { p in
                p.move(to: CGPoint(x: 76, y: 46))
                p.addLine(to: CGPoint(x: 94, y: 36))
                p.addLine(to: CGPoint(x: 94, y: 56))
                p.closeSubpath()
            },
            // eye
            Path { p in
                p.addEllipse(in: CGRect(x: 64, y: 42, width: 3, height: 3))
            },
        ]
    }

    // MARK: - 1 · Panzerschnecke

    private static var armouredSnail: [Path] {
        [
            // outer shell
            Path { p in
                p.move(to: CGPoint(x: 24, y: 62))
                p.addCurve(to: CGPoint(x: 62, y: 62),
                           control1: CGPoint(x: 24, y: 24),
                           control2: CGPoint(x: 62, y: 24))
            },
            // shell underside
            Path { p in
                p.move(to: CGPoint(x: 24, y: 62))
                p.addCurve(to: CGPoint(x: 62, y: 62),
                           control1: CGPoint(x: 30, y: 74),
                           control2: CGPoint(x: 56, y: 74))
            },
            // inner whorl
            Path { p in
                p.move(to: CGPoint(x: 34, y: 60))
                p.addCurve(to: CGPoint(x: 52, y: 58),
                           control1: CGPoint(x: 34, y: 40),
                           control2: CGPoint(x: 54, y: 42))
            },
            // whorl centre
            Path { p in
                p.move(to: CGPoint(x: 52, y: 58))
                p.addCurve(to: CGPoint(x: 43, y: 52),
                           control1: CGPoint(x: 50, y: 66),
                           control2: CGPoint(x: 42, y: 62))
            },
            // foot
            Path { p in
                p.move(to: CGPoint(x: 20, y: 72))
                p.addCurve(to: CGPoint(x: 78, y: 74),
                           control1: CGPoint(x: 34, y: 82),
                           control2: CGPoint(x: 66, y: 82))
            },
            // neck and head
            Path { p in
                p.move(to: CGPoint(x: 64, y: 70))
                p.addCurve(to: CGPoint(x: 80, y: 58),
                           control1: CGPoint(x: 74, y: 70),
                           control2: CGPoint(x: 78, y: 64))
            },
            // eye stalk
            Path { p in
                p.move(to: CGPoint(x: 79, y: 59))
                p.addLine(to: CGPoint(x: 86, y: 44))
            },
            // second stalk
            Path { p in
                p.move(to: CGPoint(x: 76, y: 60))
                p.addLine(to: CGPoint(x: 74, y: 44))
            },
            // eyes
            Path { p in
                p.addEllipse(in: CGRect(x: 85, y: 41, width: 3.5, height: 3.5))
                p.addEllipse(in: CGRect(x: 72, y: 41, width: 3.5, height: 3.5))
            },
        ]
    }

    // MARK: - 2 · Dreibein-Vogel

    private static var threeLeggedBird: [Path] {
        [
            // breast and back
            Path { p in
                p.move(to: CGPoint(x: 36, y: 40))
                p.addCurve(to: CGPoint(x: 40, y: 72),
                           control1: CGPoint(x: 20, y: 52),
                           control2: CGPoint(x: 22, y: 70))
            },
            // underside
            Path { p in
                p.move(to: CGPoint(x: 40, y: 72))
                p.addCurve(to: CGPoint(x: 66, y: 52),
                           control1: CGPoint(x: 60, y: 74),
                           control2: CGPoint(x: 66, y: 66))
            },
            // shoulder to tail
            Path { p in
                p.move(to: CGPoint(x: 36, y: 40))
                p.addCurve(to: CGPoint(x: 66, y: 52),
                           control1: CGPoint(x: 52, y: 34),
                           control2: CGPoint(x: 64, y: 42))
            },
            // head
            Path { p in
                p.move(to: CGPoint(x: 36, y: 40))
                p.addCurve(to: CGPoint(x: 30, y: 26),
                           control1: CGPoint(x: 30, y: 36),
                           control2: CGPoint(x: 26, y: 30))
            },
            // beak
            Path { p in
                p.move(to: CGPoint(x: 30, y: 26))
                p.addLine(to: CGPoint(x: 14, y: 22))
                p.addLine(to: CGPoint(x: 30, y: 32))
            },
            // wing, a closed leaf so it reads as a wing and not a scratch
            Path { p in
                p.move(to: CGPoint(x: 38, y: 44))
                p.addCurve(to: CGPoint(x: 62, y: 56),
                           control1: CGPoint(x: 48, y: 40),
                           control2: CGPoint(x: 58, y: 46))
                p.addCurve(to: CGPoint(x: 38, y: 44),
                           control1: CGPoint(x: 54, y: 64),
                           control2: CGPoint(x: 42, y: 58))
            },
            // tail, two sweeping feathers rather than two sticks
            Path { p in
                p.move(to: CGPoint(x: 66, y: 50))
                p.addCurve(to: CGPoint(x: 92, y: 38),
                           control1: CGPoint(x: 78, y: 44),
                           control2: CGPoint(x: 86, y: 38))
                p.move(to: CGPoint(x: 66, y: 55))
                p.addCurve(to: CGPoint(x: 90, y: 58),
                           control1: CGPoint(x: 78, y: 56),
                           control2: CGPoint(x: 85, y: 60))
            },
            // left leg
            Path { p in
                p.move(to: CGPoint(x: 38, y: 72))
                p.addLine(to: CGPoint(x: 34, y: 90))
            },
            // middle leg
            Path { p in
                p.move(to: CGPoint(x: 46, y: 73))
                p.addLine(to: CGPoint(x: 46, y: 90))
            },
            // right leg
            Path { p in
                p.move(to: CGPoint(x: 54, y: 71))
                p.addLine(to: CGPoint(x: 58, y: 90))
            },
            // eye
            Path { p in
                p.addEllipse(in: CGRect(x: 30, y: 30, width: 3, height: 3))
            },
        ]
    }

    // MARK: - 3 · Lesender Greif

    // Drawn as a fox, and it kept reading as a crested beast with a great
    // sweeping tail — so it was named for what it is rather than redrawn until
    // it obeyed. Hybrids are the rule in marginalia, not the exception.
    //
    // The first attempt gave the tail its own crescent floating beside the
    // body, and it read as two unrelated shapes. Body and tail are now one
    // continuous sweep, which is what holds the animal together at this size.
    private static var readingGriffin: [Path] {
        [
            // muzzle over the skull and down the back, into the tail
            Path { p in
                p.move(to: CGPoint(x: 10, y: 40))
                p.addCurve(to: CGPoint(x: 40, y: 34),
                           control1: CGPoint(x: 20, y: 32),
                           control2: CGPoint(x: 30, y: 28))
                p.addCurve(to: CGPoint(x: 62, y: 62),
                           control1: CGPoint(x: 52, y: 40),
                           control2: CGPoint(x: 60, y: 50))
                p.addCurve(to: CGPoint(x: 86, y: 34),
                           control1: CGPoint(x: 84, y: 66),
                           control2: CGPoint(x: 92, y: 50))
            },
            // tail's underside, returning to the haunch
            Path { p in
                p.move(to: CGPoint(x: 86, y: 34))
                p.addCurve(to: CGPoint(x: 58, y: 76),
                           control1: CGPoint(x: 80, y: 48),
                           control2: CGPoint(x: 72, y: 66))
            },
            // chest and front of the haunch
            Path { p in
                p.move(to: CGPoint(x: 10, y: 40))
                p.addCurve(to: CGPoint(x: 34, y: 80),
                           control1: CGPoint(x: 16, y: 56),
                           control2: CGPoint(x: 24, y: 70))
                p.addLine(to: CGPoint(x: 58, y: 78))
            },
            // ear
            Path { p in
                p.move(to: CGPoint(x: 30, y: 30))
                p.addLine(to: CGPoint(x: 30, y: 14))
                p.addLine(to: CGPoint(x: 42, y: 30))
            },
            // second ear behind it
            Path { p in
                p.move(to: CGPoint(x: 44, y: 32))
                p.addLine(to: CGPoint(x: 48, y: 18))
                p.addLine(to: CGPoint(x: 54, y: 36))
            },
            // the book, open in front of the chest
            Path { p in
                p.move(to: CGPoint(x: 6, y: 58))
                p.addLine(to: CGPoint(x: 26, y: 52))
                p.addLine(to: CGPoint(x: 26, y: 70))
                p.addLine(to: CGPoint(x: 6, y: 76))
                p.closeSubpath()
            },
            // its spine
            Path { p in
                p.move(to: CGPoint(x: 16, y: 55))
                p.addLine(to: CGPoint(x: 16, y: 73))
            },
            // eye
            Path { p in
                p.addEllipse(in: CGRect(x: 24, y: 36, width: 3, height: 3))
            },
        ]
    }

    // MARK: - 4 · Bücherwurm

    private static var bookworm: [Path] {
        [
            Path { p in
                p.move(to: CGPoint(x: 12, y: 56))
                p.addCurve(to: CGPoint(x: 50, y: 62),
                           control1: CGPoint(x: 26, y: 48),
                           control2: CGPoint(x: 42, y: 52))
            },
            Path { p in
                p.move(to: CGPoint(x: 50, y: 62))
                p.addCurve(to: CGPoint(x: 88, y: 56),
                           control1: CGPoint(x: 58, y: 52),
                           control2: CGPoint(x: 74, y: 48))
            },
            Path { p in
                p.move(to: CGPoint(x: 12, y: 56))
                p.addLine(to: CGPoint(x: 16, y: 82))
                p.addCurve(to: CGPoint(x: 50, y: 86),
                           control1: CGPoint(x: 30, y: 74),
                           control2: CGPoint(x: 42, y: 78))
            },
            Path { p in
                p.move(to: CGPoint(x: 88, y: 56))
                p.addLine(to: CGPoint(x: 84, y: 82))
                p.addCurve(to: CGPoint(x: 50, y: 86),
                           control1: CGPoint(x: 70, y: 74),
                           control2: CGPoint(x: 58, y: 78))
            },
            Path { p in
                p.move(to: CGPoint(x: 50, y: 62))
                p.addLine(to: CGPoint(x: 50, y: 86))
            },
            Path { p in
                p.move(to: CGPoint(x: 34, y: 60))
                p.addCurve(to: CGPoint(x: 40, y: 26),
                           control1: CGPoint(x: 22, y: 44),
                           control2: CGPoint(x: 24, y: 26))
            },
            Path { p in
                p.move(to: CGPoint(x: 40, y: 26))
                p.addCurve(to: CGPoint(x: 66, y: 34),
                           control1: CGPoint(x: 54, y: 26),
                           control2: CGPoint(x: 60, y: 22))
            },
            Path { p in
                p.addEllipse(in: CGRect(x: 62, y: 28, width: 12, height: 11))
            },
            Path { p in
                p.addEllipse(in: CGRect(x: 68, y: 31, width: 3, height: 3))
            },
        ]
    }

    // MARK: - 5 · Mondhund

    // A crescent reads as a crescent at any size and however crudely drawn —
    // which is the whole reason this one is in the roster.
    private static var moonHound: [Path] {
        [
            Path { p in
                p.move(to: CGPoint(x: 78, y: 10))
                p.addCurve(to: CGPoint(x: 78, y: 46),
                           control1: CGPoint(x: 58, y: 18),
                           control2: CGPoint(x: 58, y: 38))
                p.addCurve(to: CGPoint(x: 78, y: 10),
                           control1: CGPoint(x: 68, y: 36),
                           control2: CGPoint(x: 68, y: 20))
            },
            Path { p in
                p.move(to: CGPoint(x: 16, y: 84))
                p.addCurve(to: CGPoint(x: 44, y: 56),
                           control1: CGPoint(x: 12, y: 64),
                           control2: CGPoint(x: 28, y: 52))
            },
            Path { p in
                p.move(to: CGPoint(x: 16, y: 84))
                p.addCurve(to: CGPoint(x: 44, y: 66),
                           control1: CGPoint(x: 32, y: 88),
                           control2: CGPoint(x: 42, y: 78))
            },
            Path { p in
                p.move(to: CGPoint(x: 44, y: 56))
                p.addCurve(to: CGPoint(x: 56, y: 34),
                           control1: CGPoint(x: 46, y: 46),
                           control2: CGPoint(x: 50, y: 38))
            },
            Path { p in
                p.move(to: CGPoint(x: 56, y: 34))
                p.addCurve(to: CGPoint(x: 44, y: 66),
                           control1: CGPoint(x: 62, y: 44),
                           control2: CGPoint(x: 54, y: 60))
            },
            Path { p in
                p.move(to: CGPoint(x: 50, y: 36))
                p.addLine(to: CGPoint(x: 44, y: 24))
                p.addLine(to: CGPoint(x: 56, y: 30))
            },
            Path { p in
                p.move(to: CGPoint(x: 22, y: 78))
                p.addLine(to: CGPoint(x: 20, y: 92))
            },
            Path { p in
                p.move(to: CGPoint(x: 38, y: 74))
                p.addLine(to: CGPoint(x: 40, y: 92))
            },
            Path { p in
                p.move(to: CGPoint(x: 14, y: 76))
                p.addCurve(to: CGPoint(x: 4, y: 58),
                           control1: CGPoint(x: 6, y: 74),
                           control2: CGPoint(x: 4, y: 66))
            },
        ]
    }

    // MARK: - 6 · Federfisch

    private static var featherFish: [Path] {
        [
            Path { p in
                p.move(to: CGPoint(x: 16, y: 54))
                p.addCurve(to: CGPoint(x: 70, y: 54),
                           control1: CGPoint(x: 28, y: 26),
                           control2: CGPoint(x: 58, y: 30))
            },
            Path { p in
                p.move(to: CGPoint(x: 16, y: 54))
                p.addCurve(to: CGPoint(x: 70, y: 54),
                           control1: CGPoint(x: 28, y: 82),
                           control2: CGPoint(x: 58, y: 78))
            },
            Path { p in
                p.move(to: CGPoint(x: 70, y: 54))
                p.addLine(to: CGPoint(x: 92, y: 34))
                p.addCurve(to: CGPoint(x: 92, y: 74),
                           control1: CGPoint(x: 84, y: 50),
                           control2: CGPoint(x: 84, y: 58))
                p.closeSubpath()
            },
            Path { p in
                p.move(to: CGPoint(x: 34, y: 38))
                p.addCurve(to: CGPoint(x: 56, y: 34),
                           control1: CGPoint(x: 38, y: 18),
                           control2: CGPoint(x: 52, y: 16))
            },
            Path { p in
                p.move(to: CGPoint(x: 40, y: 26))
                p.addLine(to: CGPoint(x: 44, y: 36))
                p.move(to: CGPoint(x: 48, y: 22))
                p.addLine(to: CGPoint(x: 50, y: 34))
            },
            Path { p in
                p.move(to: CGPoint(x: 36, y: 70))
                p.addCurve(to: CGPoint(x: 54, y: 74),
                           control1: CGPoint(x: 40, y: 88),
                           control2: CGPoint(x: 52, y: 88))
            },
            Path { p in
                p.move(to: CGPoint(x: 28, y: 44))
                p.addCurve(to: CGPoint(x: 28, y: 64),
                           control1: CGPoint(x: 22, y: 52),
                           control2: CGPoint(x: 22, y: 56))
            },
            Path { p in
                p.addEllipse(in: CGRect(x: 24, y: 48, width: 4, height: 4))
            },
        ]
    }

    // MARK: - 7 · Zwei-Kopf-Kranich

    // The two necks are the whole idea, so they are drawn first and given the
    // most room; the body is deliberately a plain shape underneath them.
    private static var twoHeadedCrane: [Path] {
        [
            Path { p in
                p.move(to: CGPoint(x: 44, y: 62))
                p.addCurve(to: CGPoint(x: 22, y: 18),
                           control1: CGPoint(x: 34, y: 46),
                           control2: CGPoint(x: 22, y: 34))
            },
            Path { p in
                p.move(to: CGPoint(x: 22, y: 18))
                p.addLine(to: CGPoint(x: 8, y: 12))
                p.addLine(to: CGPoint(x: 22, y: 24))
            },
            Path { p in
                p.move(to: CGPoint(x: 52, y: 62))
                p.addCurve(to: CGPoint(x: 74, y: 20),
                           control1: CGPoint(x: 62, y: 46),
                           control2: CGPoint(x: 74, y: 36))
            },
            Path { p in
                p.move(to: CGPoint(x: 74, y: 20))
                p.addLine(to: CGPoint(x: 88, y: 14))
                p.addLine(to: CGPoint(x: 74, y: 26))
            },
            Path { p in
                p.move(to: CGPoint(x: 34, y: 64))
                p.addCurve(to: CGPoint(x: 68, y: 68),
                           control1: CGPoint(x: 44, y: 54),
                           control2: CGPoint(x: 62, y: 56))
            },
            Path { p in
                p.move(to: CGPoint(x: 34, y: 64))
                p.addCurve(to: CGPoint(x: 68, y: 68),
                           control1: CGPoint(x: 42, y: 80),
                           control2: CGPoint(x: 60, y: 80))
            },
            Path { p in
                p.move(to: CGPoint(x: 44, y: 76))
                p.addLine(to: CGPoint(x: 42, y: 92))
            },
            Path { p in
                p.move(to: CGPoint(x: 58, y: 76))
                p.addLine(to: CGPoint(x: 60, y: 92))
            },
            Path { p in
                p.addEllipse(in: CGRect(x: 24, y: 17, width: 2.6, height: 2.6))
                p.addEllipse(in: CGRect(x: 70, y: 19, width: 2.6, height: 2.6))
            },
        ]
    }
}

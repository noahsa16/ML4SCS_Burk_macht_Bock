import Foundation

/// Carries a value across an isolation boundary that the compiler cannot
/// prove safe.
///
/// WatchConnectivity and JSONSerialization hand this code `[String: Any]`
/// dictionaries: value-typed copies holding only property-list types, owned
/// by exactly one thread at a time. Swift cannot express that, so the wrapper
/// asserts it. Every use is a hand-over — the sender must not touch the value
/// again once boxed.
public nonisolated struct UncheckedSendable<Value>: @unchecked Sendable {
    public let value: Value
    public init(_ value: Value) { self.value = value }
}

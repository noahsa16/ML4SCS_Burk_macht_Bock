import Foundation

struct FocusAPI {
    // No stored closure (would be non-Sendable). Reads the base URL inline.
    func today() async throws -> FocusTodayDTO { try await get("/focus/today") }
    func week() async throws -> FocusRangeDTO { try await get("/focus/week") }
    func history(days: Int) async throws -> FocusRangeDTO {
        try await get("/focus/history?days=\(days)")
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = URL(string: PhoneBridge.serverBaseURL + path) else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        req.timeoutInterval = 6
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

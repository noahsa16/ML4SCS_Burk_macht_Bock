import Testing
import Foundation
@testable import WatchStreamer

@Suite("ServerEndpoint")
struct ServerEndpointTests {

    @Test("bare host gets http scheme and default port")
    func bareHost() throws {
        let r = try #require(ServerEndpoint.resolve("192.168.178.147"))
        #expect(r.httpBase.absoluteString == "http://192.168.178.147:8000")
        #expect(r.watchUpload.absoluteString == "http://192.168.178.147:8000/watch")
        #expect(r.webSocket.absoluteString == "ws://192.168.178.147:8000/ws")
        #expect(r.isSecure == false)
    }

    @Test("explicit port is preserved")
    func explicitPort() throws {
        let r = try #require(ServerEndpoint.resolve("10.0.0.5:9000"))
        #expect(r.httpBase.absoluteString == "http://10.0.0.5:9000")
        #expect(r.webSocket.absoluteString == "ws://10.0.0.5:9000/ws")
    }

    @Test("https maps the socket to wss")
    func secureScheme() throws {
        let r = try #require(ServerEndpoint.resolve("https://scrybe.example.org"))
        #expect(r.isSecure)
        #expect(r.webSocket.scheme == "wss")
        #expect(r.watchUpload.absoluteString == "https://scrybe.example.org:8000/watch")
    }

    @Test("whitespace and trailing slashes are trimmed")
    func trimming() throws {
        let r = try #require(ServerEndpoint.resolve("  192.168.1.2:8000/  "))
        #expect(r.httpBase.absoluteString == "http://192.168.1.2:8000")
    }

    @Test("IPv6 literal is parsed")
    func ipv6() throws {
        let r = try #require(ServerEndpoint.resolve("[fd00::1]:8000"))
        #expect(r.webSocket.absoluteString == "ws://[fd00::1]:8000/ws")
    }

    @Test("empty or unusable input resolves to nil", arguments: ["", "   ", "///"])
    func rejectsGarbage(raw: String) {
        #expect(ServerEndpoint.resolve(raw) == nil)
    }

    @Test("http and ws paths agree on host and port")
    func pathsAgree() throws {
        let r = try #require(ServerEndpoint.resolve("myhost:1234"))
        #expect(r.httpBase.host == r.webSocket.host)
        #expect(r.httpBase.port == r.webSocket.port)
    }
}

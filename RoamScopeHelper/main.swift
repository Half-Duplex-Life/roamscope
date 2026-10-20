import Cocoa
import CoreLocation
import CoreWLAN
import Network

final class AppDelegate: NSObject, NSApplicationDelegate, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var window: NSWindow!
    private var output: NSTextView!
    private var listener: NWListener?

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 660, height: 370), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "RoamScope Wi-Fi Identity Test"
        window.center()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)
        let button = NSButton(title: "Request Location Access", target: self, action: #selector(requestPermission))
        let refresh = NSButton(title: "Read Wi-Fi", target: self, action: #selector(readWiFi))
        output = NSTextView()
        output.isEditable = false
        output.font = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        let scroll = NSScrollView()
        scroll.documentView = output
        scroll.hasVerticalScroller = true
        stack.addArrangedSubview(button)
        stack.addArrangedSubview(refresh)
        stack.addArrangedSubview(scroll)
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 240).isActive = true
        window.contentView = stack
        manager.delegate = self
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        append("Initial location authorization: \(manager.authorizationStatus.rawValue) (0=not determined, 1=restricted, 2=denied, 3=authorized on macOS)")
        readWiFi()
        startLocalServer()
    }
    private func append(_ s: String) { output.string += s + "\n" }
    @objc private func requestPermission() {
        append("Requesting location authorization...")
        manager.requestWhenInUseAuthorization()
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        append("Location authorization: \(manager.authorizationStatus.rawValue)")
        readWiFi()
    }
    private func currentWiFiPayload() -> [String: Any] {
        precondition(Thread.isMainThread)
        let status = manager.authorizationStatus
        let iface = CWWiFiClient.shared().interfaces()?.first(where: { $0.interfaceName == "en0" })
        let ssid = iface?.ssid() ?? ""
        let bssid = iface?.bssid() ?? ""
        // Report the actual CoreLocation state and the identity read result
        // separately. Never synthesize a BSSID or claim authorization based
        // on whether a network happens to be visible.
        return [
            "authorization_status": status.rawValue,
            "authorized": status == .authorizedAlways,
            "interface": iface?.interfaceName ?? "",
            "ssid": ssid,
            "bssid": bssid,
            "rssi": iface?.rssiValue() ?? 0,
            "noise": iface?.noiseMeasurement() ?? 0,
            "channel": iface?.wlanChannel()?.channelNumber ?? 0,
            "channel_band": iface?.wlanChannel().map { String(describing: $0.channelBand) } ?? "",
            "channel_width": iface?.wlanChannel().map { String(describing: $0.channelWidth) } ?? "",
            "tx_mbps": iface?.transmitRate() ?? 0
        ]
    }
    private func startLocalServer() {
        do {
            let server = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: 18763)!)
            server.parameters.requiredLocalEndpoint = .hostPort(host: .ipv4(.loopback), port: NWEndpoint.Port(rawValue: 18763)!)
            server.newConnectionHandler = { [weak self] connection in
                connection.start(queue: .main)
                connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] _, _, _, _ in
                    // Network callbacks can execute outside the main thread. CoreLocation
                    // and CoreWLAN state is sampled on the GUI application's main queue.
                    DispatchQueue.main.async {
                        guard let self = self else { connection.cancel(); return }
                        let payload = self.currentWiFiPayload()
                        let data = (try? JSONSerialization.data(withJSONObject: payload)) ?? Data("{}".utf8)
                        let header = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: \(data.count)\r\nConnection: close\r\n\r\n"
                        connection.send(content: Data(header.utf8) + data, completion: .contentProcessed { _ in connection.cancel() })
                    }
                }
            }
            server.stateUpdateHandler = { [weak self] state in
                if case .failed(let error) = state { self?.append("Local service failed: \(error)") }
            }
            server.start(queue: .main)
            listener = server
            append("Local RoamScope bridge: http://127.0.0.1:18763 (keep this app open)")
        } catch { append("Local bridge unavailable: \(error)") }
    }
    @objc private func readWiFi() {
        let interfaces = CWWiFiClient.shared().interfaces() ?? []
        if interfaces.isEmpty { append("No CoreWLAN interfaces returned") }
        for iface in interfaces {
            append("Interface: \(iface.interfaceName ?? "UNAVAILABLE")")
            append("SSID: \(iface.ssid() ?? "UNAVAILABLE")")
            append("BSSID: \(iface.bssid() ?? "UNAVAILABLE")")
            append("RSSI: \(iface.rssiValue()) dBm; Noise: \(iface.noiseMeasurement()) dBm")
            append("Channel: \(iface.wlanChannel()?.channelNumber ?? 0); Tx: \(iface.transmitRate()) Mbps")
        }
        append("---")
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()

import Cocoa
import Darwin
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    private let appName = "Data Handler"
    private let bundleIdentifier = "com.dit.data-handler"
    private var window: NSWindow?
    private var webView: WKWebView?
    private var serverProcess: Process?
    private var supportDirectory: URL?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        configureMenu()
        createWindow()
        startAppFront()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopConsole()
    }

    private func configureMenu() {
        let menu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "Quit \(appName)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appMenuItem.submenu = appMenu
        menu.addItem(appMenuItem)
        NSApp.mainMenu = menu
    }

    private func createWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(self, name: "pathChooser")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.title = appName
        window.minSize = NSSize(width: 1100, height: 760)
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)

        self.webView = webView
        self.window = window
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "pathChooser",
              let payload = message.body as? [String: Any],
              let requestId = payload["requestId"] as? String
        else {
            return
        }

        let currentPath = payload["currentPath"] as? String
        showFolderPicker(requestId: requestId, currentPath: currentPath)
    }

    private func showFolderPicker(requestId: String, currentPath: String?) {
        let panel = NSOpenPanel()
        panel.title = "Select folder"
        panel.prompt = "Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true

        if let currentPath, !currentPath.isEmpty {
            let currentURL = URL(fileURLWithPath: currentPath)
            var isDirectory: ObjCBool = false
            if FileManager.default.fileExists(atPath: currentURL.path, isDirectory: &isDirectory) {
                panel.directoryURL = isDirectory.boolValue ? currentURL : currentURL.deletingLastPathComponent()
            }
        }

        if let window {
            panel.beginSheetModal(for: window) { [weak self] response in
                let selectedPath = response == .OK ? panel.url?.path : nil
                self?.sendPathSelectionResult(requestId: requestId, path: selectedPath)
            }
            return
        }

        let response = panel.runModal()
        sendPathSelectionResult(requestId: requestId, path: response == .OK ? panel.url?.path : nil)
    }

    private func sendPathSelectionResult(requestId: String, path: String?) {
        let payload: [String: Any] = [
            "requestId": requestId,
            "path": path ?? NSNull()
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8)
        else {
            return
        }
        webView?.evaluateJavaScript("window.DataHandlerPathChooser && window.DataHandlerPathChooser.resolve(\(json));")
    }

    private func startAppFront() {
        guard let resources = Bundle.main.resourceURL else {
            showFailure("The app bundle is missing its Resources directory.")
            return
        }

        let appRoot = resources.appendingPathComponent("app", isDirectory: true)
        let python = resources.appendingPathComponent("venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            showFailure("The bundled Python runtime is missing or is not executable.")
            return
        }

        let support = applicationSupportDirectory()
        supportDirectory = support
        let pipelineRoot = support.appendingPathComponent(".pipeline", isDirectory: true)
        let logDirectory = support.appendingPathComponent("logs", isDirectory: true)
        try? FileManager.default.createDirectory(at: pipelineRoot, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)

        let port = firstAvailablePort(startingAt: 8750, limit: 20) ?? 8750
        let url = URL(string: "http://127.0.0.1:\(port)/")!

        let process = Process()
        process.executableURL = python
        process.currentDirectoryURL = appRoot
        process.arguments = [
            "-m", "orchestrator.cli",
            "app",
            "--host", "127.0.0.1",
            "--port", "\(port)"
        ]

        var environment = ProcessInfo.processInfo.environment
        let existingPythonPath = environment["PYTHONPATH"].map { ":\($0)" } ?? ""
        let existingPath = environment["PATH"].map { ":\($0)" } ?? ""
        environment["PYTHONPATH"] = appRoot.path + existingPythonPath
        environment["PATH"] = resources.appendingPathComponent("venv/bin").path + existingPath
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["DATA_HANDLER_PIPELINE_ROOT"] = pipelineRoot.path
        environment["DATA_HANDLER_APP_BUNDLE"] = Bundle.main.bundlePath
        process.environment = environment

        process.standardOutput = fileHandle(at: logDirectory.appendingPathComponent("app-front.out.log"))
        process.standardError = fileHandle(at: logDirectory.appendingPathComponent("app-front.err.log"))

        do {
            try process.run()
        } catch {
            showFailure("The app front could not start: \(error.localizedDescription)")
            return
        }

        serverProcess = process
        waitForAppFront(url: url, deadline: Date().addingTimeInterval(15))
    }

    private func waitForAppFront(url: URL, deadline: Date) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let stateURL = url.appendingPathComponent("api/app/state")

            while Date() < deadline {
                if self.serverProcess?.isRunning == false {
                    DispatchQueue.main.async {
                        self.showFailure("The app front exited before it became ready.")
                    }
                    return
                }

                if (try? Data(contentsOf: stateURL)) != nil {
                    DispatchQueue.main.async {
                        self.webView?.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
                    }
                    return
                }

                Thread.sleep(forTimeInterval: 0.2)
            }

            DispatchQueue.main.async {
                self.showFailure("The app front did not become ready in time.")
            }
        }
    }

    private func stopConsole() {
        guard let process = serverProcess else {
            return
        }
        if process.isRunning {
            process.terminate()
            DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                if process.isRunning {
                    kill(process.processIdentifier, SIGKILL)
                }
            }
        }
    }

    private func showFailure(_ message: String) {
        let escaped = message
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        let html = """
        <!doctype html>
        <html>
        <head>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body {
              margin: 0;
              min-height: 100vh;
              display: grid;
              place-items: center;
              background: #f7f7f5;
              color: #1f2328;
              font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            main {
              width: min(520px, calc(100vw - 40px));
              padding: 20px;
              border: 1px solid #e5e2dd;
              border-radius: 8px;
              background: #fff;
            }
            h1 { margin: 0 0 8px; font-size: 18px; }
            p { margin: 0; color: #68707a; line-height: 1.45; }
          </style>
        </head>
        <body>
          <main>
            <h1>Data Handler could not start</h1>
            <p>\(escaped)</p>
          </main>
        </body>
        </html>
        """
        webView?.loadHTMLString(html, baseURL: nil)
    }

    private func applicationSupportDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let support = base.appendingPathComponent(appName, isDirectory: true)
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        return support
    }

    private func fileHandle(at url: URL) -> FileHandle? {
        FileManager.default.createFile(atPath: url.path, contents: nil)
        return try? FileHandle(forWritingTo: url)
    }

    private func firstAvailablePort(startingAt port: Int, limit: Int) -> Int? {
        let lastPort = min(65535, port + max(0, limit - 1))
        if port > lastPort {
            return nil
        }
        for candidate in port...lastPort {
            if canBind(port: candidate) {
                return candidate
            }
        }
        return nil
    }

    private func canBind(port: Int) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        if descriptor < 0 {
            return false
        }
        defer { close(descriptor) }

        var value: Int32 = 1
        setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &value, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(port).bigEndian
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

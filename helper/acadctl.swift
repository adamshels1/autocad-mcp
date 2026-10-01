// acadctl: small native helper that lets the MCP server drive AutoCAD for Mac.
//
//   acadctl type [--no-escape] [--no-enter] [--restore-focus] <text>
//       Brings AutoCAD to the front and types <text> into its command line
//       using Unicode keyboard events (independent of the active keyboard layout).
//   acadctl history
//       Prints the command line history (everything AutoCAD printed).
//   acadctl window
//       Prints JSON about the main AutoCAD window: {"id":..,"title":..,"x":..,"y":..,"w":..,"h":..}
//   acadctl click <x> <y>
//       Left-clicks at screen point (x, y) in points.
//   acadctl key <keycode> [cmd|shift|alt|ctrl ...]
//       Brings AutoCAD to the front and presses a single key (virtual key code).
//
// Env: ACAD_BUNDLE_ID (default com.autodesk.AutoCAD2026)
import Cocoa

let bundleId = ProcessInfo.processInfo.environment["ACAD_BUNDLE_ID"] ?? "com.autodesk.AutoCAD2026"
let src = CGEventSource(stateID: .hidSystemState)

func fail(_ msg: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(code)
}

func autocad() -> NSRunningApplication {
    guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).first else {
        fail("ERROR: AutoCAD (\(bundleId)) is not running", 4)
    }
    return app
}

func requireAX() {
    if !AXIsProcessTrusted() {
        fail("ERROR: no Accessibility permission for the host process (System Settings > Privacy & Security > Accessibility: enable your terminal / Claude app)", 3)
    }
}

func isFrontmost(_ app: NSRunningApplication) -> Bool {
    NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
}

// NSRunningApplication.activate() is ignored when called from a background process
// on recent macOS, so go through AppleScript, which is allowed to switch apps.
func activateApp(bundle: String) {
    var err: NSDictionary?
    NSAppleScript(source: "tell application id \"\(bundle)\" to activate")?.executeAndReturnError(&err)
}

// Keystrokes must never land in another app, so bail out if AutoCAD is not in front.
func activate(_ app: NSRunningApplication) {
    if isFrontmost(app) { return }
    activateApp(bundle: bundleId)
    for _ in 0..<60 { if isFrontmost(app) { break }; usleep(50_000) }
    guard isFrontmost(app) else { fail("ERROR: could not bring AutoCAD to the front", 6) }
    usleep(300_000)
}

func key(_ code: CGKeyCode, flags: CGEventFlags = []) {
    let d = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)!
    d.flags = flags
    d.post(tap: .cghidEventTap)
    usleep(10_000)
    let u = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)!
    u.flags = flags
    u.post(tap: .cghidEventTap)
    usleep(10_000)
}

func typeChar(_ ch: Character) {
    let units = Array(String(ch).utf16)
    for down in [true, false] {
        let e = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: down)!
        e.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
        e.post(tap: .cghidEventTap)
        usleep(4_000)
    }
}

// ---- Accessibility: AutoCAD's command line is an AXTextArea "cmdInput", history is "cmdHistory".
func axAttr(_ e: AXUIElement, _ a: String) -> AnyObject? {
    var v: AnyObject?
    AXUIElementCopyAttributeValue(e, a as CFString, &v)
    return v
}

func axFind(_ e: AXUIElement, _ id: String, depth: Int = 0) -> AXUIElement? {
    if (axAttr(e, kAXIdentifierAttribute) as? String) == id { return e }
    if depth > 14 { return nil }
    for k in (axAttr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? [] {
        if let r = axFind(k, id, depth: depth + 1) { return r }
    }
    return nil
}

func axElement(_ app: NSRunningApplication, _ id: String) -> AXUIElement? {
    let root = AXUIElementCreateApplication(app.processIdentifier)
    for w in (axAttr(root, kAXWindowsAttribute) as? [AXUIElement]) ?? [] {
        if let e = axFind(w, id) { return e }
    }
    return nil
}

func mainWindow(pid: pid_t) -> [String: Any]? {
    guard let list = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return nil }
    var best: [String: Any]? = nil
    var bestArea = 0.0
    for w in list {
        guard (w[kCGWindowOwnerPID as String] as? Int32) == pid,
              (w[kCGWindowLayer as String] as? Int) == 0,
              let b = w[kCGWindowBounds as String] as? [String: Double] else { continue }
        let area = (b["Width"] ?? 0) * (b["Height"] ?? 0)
        if area > bestArea {
            bestArea = area
            best = ["id": w[kCGWindowNumber as String] as? Int ?? 0,
                    "title": w[kCGWindowName as String] as? String ?? "",
                    "onscreen": (w[kCGWindowIsOnscreen as String] as? Bool) ?? false,
                    "x": b["X"] ?? 0, "y": b["Y"] ?? 0, "w": b["Width"] ?? 0, "h": b["Height"] ?? 0]
        }
    }
    return best
}

var args = Array(CommandLine.arguments.dropFirst())
guard !args.isEmpty else { fail("usage: acadctl type|window|click|key ...", 2) }
let cmd = args.removeFirst()

switch cmd {
case "type":
    var sendEscape = true, sendEnter = true, restore = false
    var text: String? = nil
    for a in args {
        switch a {
        case "--no-escape": sendEscape = false
        case "--no-enter": sendEnter = false
        case "--restore-focus": restore = true
        default: text = a
        }
    }
    guard let line = text else { fail("usage: acadctl type [--no-escape] [--no-enter] [--restore-focus] <text>", 2) }
    requireAX()
    let app = autocad()
    let previous = NSWorkspace.shared.frontmostApplication
    activate(app)
    guard let input = axElement(app, "cmdInput") else {
        fail("ERROR: AutoCAD command line not found (is a drawing open and the command line visible? Ctrl+9 toggles it)", 8)
    }
    func focusInput() {
        AXUIElementSetAttributeValue(input, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        usleep(80_000)
    }
    func current() -> String { (axAttr(input, kAXValueAttribute) as? String) ?? "" }
    // Enter is pressed only after the command line holds exactly `line`: dropped key events
    // or a focus change in the middle of typing would otherwise run half a command.
    // (Writing the text with AXValue does not work: AutoCAD shows it but its own input buffer stays empty.)
    func enter() -> Bool {
        if !isFrontmost(app) { fail("ERROR: AutoCAD lost focus while typing", 7) }
        for ch in line { typeChar(ch) }
        for _ in 0..<20 { if current() == line { return true }; usleep(25_000) }
        return false
    }

    focusInput()
    if sendEscape { key(53); key(53); usleep(100_000) }
    if !line.isEmpty {
        var ok = false
        for _ in 0..<4 {
            if enter() { ok = true; break }
            key(53); key(53); usleep(150_000)   // clear the partial text and try again
            focusInput()
        }
        if !ok {
            fail("ERROR: the AutoCAD command line did not accept the text (got: \(current().prefix(60))...)", 9)
        }
    }
    usleep(40_000)
    if sendEnter { key(36) }
    if restore, let p = previous, p.processIdentifier != app.processIdentifier, let b = p.bundleIdentifier {
        usleep(250_000)
        activateApp(bundle: b)
    }

case "key":
    guard let first = args.first, let code = UInt16(first) else { fail("usage: acadctl key <keycode> [cmd shift alt ctrl]", 2) }
    var flags: CGEventFlags = []
    for m in args.dropFirst() {
        switch m {
        case "cmd": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "alt": flags.insert(.maskAlternate)
        case "ctrl": flags.insert(.maskControl)
        default: break
        }
    }
    requireAX()
    activate(autocad())
    key(CGKeyCode(code), flags: flags)

case "history":
    // Prints the whole command line history (text window contents).
    requireAX()
    guard let h = axElement(autocad(), "cmdHistory") else { fail("ERROR: command history not found", 8) }
    print(axAttr(h, kAXValueAttribute) as? String ?? "", terminator: "")

case "window":
    let app = autocad()
    guard let w = mainWindow(pid: app.processIdentifier) else { fail("ERROR: AutoCAD window not found", 5) }
    var out = w
    out["active"] = app.isActive
    let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)

case "click":
    guard args.count >= 2, let x = Double(args[0]), let y = Double(args[1]) else { fail("usage: acadctl click <x> <y>", 2) }
    requireAX()
    let p = CGPoint(x: x, y: y)
    CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(50_000)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(30_000)
    CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)

default:
    fail("unknown command: \(cmd)", 2)
}

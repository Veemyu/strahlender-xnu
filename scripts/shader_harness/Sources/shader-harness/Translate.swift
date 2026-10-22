import Foundation

func findSpirvCross() -> String? {
    var candidates: [String] = []
    if let e = ProcessInfo.processInfo.environment["SPIRV_CROSS"] { candidates.append(e) }
    candidates += ["/opt/homebrew/bin/spirv-cross", "/usr/local/bin/spirv-cross"]
    for d in (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":") { candidates.append("\(d)/spirv-cross") }
    return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
}

func runProcess(_ exe: String, _ args: [String]) throws -> (status: Int32, out: Data, err: Data) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let o = Pipe(), e = Pipe()
    p.standardOutput = o
    p.standardError = e
    try p.run()
    // read stderr in its own thread so no pipe fills up
    var errData = Data()
    let g = DispatchGroup()
    g.enter()
    DispatchQueue.global().async { errData = e.fileHandleForReading.readDataToEndOfFile(); g.leave() }
    let outData = o.fileHandleForReading.readDataToEndOfFile()
    g.wait()
    p.waitUntilExit()
    return (p.terminationStatus, outData, errData)
}

/// SPIR-V -> MSL 2.3 per spirv-cross; Entry-Point heisst danach `main0`.
func translateToMSL(_ stage: StageSource) throws -> String {
    if let m = stage.msl {
        guard let s = try? String(contentsOf: m, encoding: .utf8) else { throw HarnessError("MSL \(m.path) nicht lesbar") }
        return s
    }
    guard let spv = stage.spirv else { throw HarnessError("no shader source") }
    guard FileManager.default.fileExists(atPath: spv.path) else { throw HarnessError("SPIR-V \(spv.path) not found") }
    guard let exe = findSpirvCross() else { throw HarnessError("spirv-cross not found (brew install spirv-cross or SPIRV_CROSS=<path>)") }
    var args = [spv.path, "--msl", "--msl-version", "20300"]
    if stage.flipVertY { args.append("--flip-vert-y") }
    if stage.fixupClipspace { args.append("--fixup-clipspace") }
    args += stage.extraArgs
    let r = try runProcess(exe, args)
    guard r.status == 0 else {
        throw HarnessError("spirv-cross exit \(r.status) for\(spv.lastPathComponent): \(String(decoding: r.err, as: UTF8.self))")
    }
    return String(decoding: r.out, as: UTF8.self)
}

/// Optional offline check with `xcrun metal` (only useful if the Metal toolchain is installed).
func xcrunMetalCheck(file: URL) -> String {
    guard let r = try? runProcess("/usr/bin/xcrun", ["-sdk", "macosx", "metal", "-std=macos-metal2.3", "-c", file.path, "-o", file.path + ".air"]) else {
        return "xcrun nicht startbar"
    }
    if r.status == 0 { return "ok" }
    return "not available/failed: " + String(decoding: r.err, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
}

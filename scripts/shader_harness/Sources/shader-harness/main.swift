import Foundation
import CryptoKit

let usage = """
shader-harness - Offscreen-Referenzrenderer (SPIR-V/MSL -> Metal -> PNG)

  shader-harness render <spec.json> --out <bild.png> [--dump-msl <ordner>] [--xcrun-check]
  shader-harness info   <spec.json> [--dump-msl <ordner>]

render  uebersetzt (spirv-cross), kompiliert (Metal-Laufzeit), rendert offscreen und schreibt ein PNG (RGBA8).
info    uebersetzt und kompiliert, gibt die Bindings (Buffer/Textur/Sampler/Attribute) aus und rendert nicht.
--dump-msl   schreibt die erzeugte MSL als <ordner>/vertex.metal und fragment.metal.
--xcrun-check  ruft zusaetzlich `xcrun metal -c` auf (nur mit installierter Metal-Toolchain).
Umgebungsvariable SPIRV_CROSS ueberschreibt den spirv-cross-Pfad.
"""

func fail(_ msg: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(code)
}

func run() throws {
    var args = Array(CommandLine.arguments.dropFirst())
    guard let cmd = args.first, cmd == "render" || cmd == "info" else {
        print(usage)
        exit(args.first == "--help" || args.first == "-h" ? 0 : 2)
    }
    args.removeFirst()
    var specPath: String?
    var out: String?
    var dump: String?
    var xcrun = false
    var i = 0
    while i < args.count {
        switch args[i] {
        case "--out": i += 1; guard i < args.count else { fail("--out braucht einen Pfad", code: 2) }; out = args[i]
        case "--dump-msl": i += 1; guard i < args.count else { fail("--dump-msl braucht einen Ordner", code: 2) }; dump = args[i]
        case "--xcrun-check": xcrun = true
        default:
            guard specPath == nil, !args[i].hasPrefix("--") else { fail("unbekannte Option \(args[i])\n\(usage)", code: 2) }
            specPath = args[i]
        }
        i += 1
    }
    guard let sp = specPath else { fail("Spec-Datei fehlt\n\(usage)", code: 2) }
    if cmd == "render" && out == nil { fail("render braucht --out <bild.png>", code: 2) }

    let specURL = URL(fileURLWithPath: sp)
    guard let raw = try? Data(contentsOf: specURL) else { throw HarnessError("Spec \(sp) nicht lesbar") }
    let json: Any
    do { json = try JSONSerialization.jsonObject(with: raw) } catch { throw HarnessError("Spec \(sp): kein gueltiges JSON (\(error.localizedDescription))") }
    let spec = try parseSpec(json, base: specURL.deletingLastPathComponent())

    let vs = try translateToMSL(spec.vertex)
    let fs = try translateToMSL(spec.fragment)
    if let d = dump {
        let dir = URL(fileURLWithPath: d)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try vs.write(to: dir.appendingPathComponent("vertex.metal"), atomically: true, encoding: .utf8)
        try fs.write(to: dir.appendingPathComponent("fragment.metal"), atomically: true, encoding: .utf8)
        if xcrun {
            print("xcrun metal vertex: " + xcrunMetalCheck(file: dir.appendingPathComponent("vertex.metal")))
            print("xcrun metal fragment: " + xcrunMetalCheck(file: dir.appendingPathComponent("fragment.metal")))
        }
    } else if xcrun {
        fail("--xcrun-check braucht --dump-msl <ordner>", code: 2)
    }

    let result = try render(spec, vsMSL: vs, fsMSL: fs, infoOnly: cmd == "info")
    result.info.forEach { print($0) }
    guard cmd == "render", let o = out else { return }
    let outURL = URL(fileURLWithPath: o)
    try FileManager.default.createDirectory(at: outURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    try writePNG(result, to: outURL)
    let cc = spec.clearColor.map(toByte)
    var covered = 0
    for p in stride(from: 0, to: result.rgba.count, by: 4) where Array(result.rgba[p..<p + 4]) != cc { covered += 1 }
    let sha = SHA256.hash(data: result.rgba).map { String(format: "%02x", $0) }.joined()
    print("png=\(outURL.path) size=\(result.width)x\(result.height) nonclear_pixels=\(covered) rgba_sha256=\(sha)")
}

do { try run() } catch { fail("FEHLER: \(error)") }

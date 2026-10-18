// Kompiliert MSL-Dateien per Laufzeit-Compiler (MTLDevice.makeLibrary) und zaehlt Erfolge.
// Aufruf: swiftc -O scripts/shader_msl_check.swift -o work/shader-test/msl_check && work/shader-test/msl_check <dir> [max]
import Foundation
import Metal

let args = CommandLine.arguments
guard args.count >= 2, let device = MTLCreateSystemDefaultDevice() else {
    print("usage: msl_check <dir> [max]; Metal device needed")
    exit(2)
}
let dir = args[1]
let limit = args.count > 2 ? Int(args[2]) ?? Int.max : Int.max
let files = ((try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? [])
    .filter { $0.hasSuffix(".metal") }.sorted().prefix(limit)
var ok = 0
var fail = 0
var firstErrors: [String] = []
for f in files {
    guard let src = try? String(contentsOfFile: dir + "/" + f, encoding: .utf8) else { continue }
    let opts = MTLCompileOptions()
    opts.languageVersion = .version2_3
    do {
        _ = try device.makeLibrary(source: src, options: opts)
        ok += 1
    } catch {
        fail += 1
        if firstErrors.count < 5 { firstErrors.append("\(f): \(String("\(error)".prefix(300)))") }
    }
}
print("device=\(device.name) ok=\(ok) fail=\(fail)")
firstErrors.forEach { print($0) }

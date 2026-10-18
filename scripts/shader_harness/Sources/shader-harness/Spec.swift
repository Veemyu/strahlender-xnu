import Foundation
import Metal

struct HarnessError: Error, CustomStringConvertible {
    let description: String
    init(_ s: String) { description = s }
}

/// JSON-Objekt mit Pfadangabe fuer Fehlermeldungen; unbekannte Schluessel gelten als Fehler (Tippfehler-Schutz).
final class Obj {
    let dict: [String: Any]
    let path: String
    private var used = Set<String>()

    init(_ any: Any, path: String) throws {
        guard let d = any as? [String: Any] else { throw HarnessError("\(path): Objekt erwartet") }
        dict = d
        self.path = path
    }

    private func raw(_ k: String) -> Any? {
        used.insert(k)
        guard let v = dict[k], !(v is NSNull) else { return nil }
        return v
    }

    func has(_ k: String) -> Bool { used.insert(k); return dict[k] != nil && !(dict[k] is NSNull) }

    func string(_ k: String) throws -> String? {
        guard let v = raw(k) else { return nil }
        guard let s = v as? String else { throw HarnessError("\(path).\(k): String erwartet") }
        return s
    }

    func int(_ k: String) throws -> Int? {
        guard let v = raw(k) else { return nil }
        guard let n = v as? NSNumber, let i = Int(exactly: n.doubleValue) else { throw HarnessError("\(path).\(k): Ganzzahl erwartet") }
        return i
    }

    func double(_ k: String) throws -> Double? {
        guard let v = raw(k) else { return nil }
        guard let n = v as? NSNumber else { throw HarnessError("\(path).\(k): Zahl erwartet") }
        return n.doubleValue
    }

    func bool(_ k: String) throws -> Bool? {
        guard let v = raw(k) else { return nil }
        guard let b = v as? Bool else { throw HarnessError("\(path).\(k): true/false erwartet") }
        return b
    }

    func array(_ k: String) throws -> [Any]? {
        guard let v = raw(k) else { return nil }
        guard let a = v as? [Any] else { throw HarnessError("\(path).\(k): Liste erwartet") }
        return a
    }

    func doubles(_ k: String) throws -> [Double]? {
        guard let a = try array(k) else { return nil }
        return try a.enumerated().map { i, e in
            guard let n = e as? NSNumber else { throw HarnessError("\(path).\(k)[\(i)]: Zahl erwartet") }
            return n.doubleValue
        }
    }

    func ints(_ k: String) throws -> [Int]? {
        guard let a = try array(k) else { return nil }
        return try a.enumerated().map { i, e in
            guard let n = e as? NSNumber, let v = Int(exactly: n.doubleValue) else { throw HarnessError("\(path).\(k)[\(i)]: Ganzzahl erwartet") }
            return v
        }
    }

    func strings(_ k: String) throws -> [String]? {
        guard let a = try array(k) else { return nil }
        return try a.enumerated().map { i, e in
            guard let s = e as? String else { throw HarnessError("\(path).\(k)[\(i)]: String erwartet") }
            return s
        }
    }

    func obj(_ k: String) throws -> Obj? {
        guard let v = raw(k) else { return nil }
        return try Obj(v, path: "\(path).\(k)")
    }

    func objs(_ k: String) throws -> [Obj]? {
        guard let a = try array(k) else { return nil }
        return try a.enumerated().map { i, e in try Obj(e, path: "\(path).\(k)[\(i)]") }
    }

    func finish() throws {
        let unknown = Set(dict.keys).subtracting(used).sorted()
        if !unknown.isEmpty { throw HarnessError("\(path): unbekannte Schluessel \(unknown)") }
    }
}

func resolve(_ p: String, base: URL) -> URL {
    p.hasPrefix("/") ? URL(fileURLWithPath: p) : base.appendingPathComponent(p).standardizedFileURL
}

func littleEndian<T: FixedWidthInteger>(_ values: [T]) -> Data {
    var d = Data()
    for v in values { var le = v.littleEndian; withUnsafeBytes(of: &le) { d.append(contentsOf: $0) } }
    return d
}

/// Nutzdaten aus genau einer der Formen floats / ints / uints / bytes / file.
func readPayload(_ o: Obj, base: URL) throws -> Data {
    var found: [(String, Data)] = []
    if let f = try o.doubles("floats") { found.append(("floats", littleEndian(f.map { Float($0).bitPattern }))) }
    if let i = try o.ints("ints") { found.append(("ints", littleEndian(i.map { Int32(truncatingIfNeeded: $0) }))) }
    if let u = try o.ints("uints") {
        guard u.allSatisfy({ $0 >= 0 && $0 <= Int(UInt32.max) }) else { throw HarnessError("\(o.path).uints: ausserhalb 0...4294967295") }
        found.append(("uints", littleEndian(u.map { UInt32($0) })))
    }
    if let b = try o.ints("bytes") {
        guard b.allSatisfy({ $0 >= 0 && $0 <= 255 }) else { throw HarnessError("\(o.path).bytes: ausserhalb 0...255") }
        found.append(("bytes", Data(b.map { UInt8($0) })))
    }
    if let f = try o.string("file") {
        let url = resolve(f, base: base)
        guard let d = try? Data(contentsOf: url) else { throw HarnessError("\(o.path).file: \(url.path) nicht lesbar") }
        found.append(("file", d))
    }
    guard found.count == 1 else { throw HarnessError("\(o.path): genau eine Quelle aus floats/ints/uints/bytes/file erwartet (gefunden: \(found.map { $0.0 }))") }
    return found[0].1
}

struct StageSource {
    var spirv: URL?
    var msl: URL?
    var entry = "main0"
    var flipVertY = false
    var fixupClipspace = false
    var extraArgs: [String] = []
}

struct BufferWrite {
    var offset: Int
    var data: Data
}

struct BufferSpec {
    var stage: String
    var slot: Int
    var minSize: Int
    var writes: [BufferWrite]
}

struct VertexBufferSpec {
    var slot: Int
    var stride: Int?
    var data: Data
    var perInstance: Bool
}

struct AttributeSpec {
    var location: Int
    var buffer: Int
    var offset: Int
    var format: MTLVertexFormat
    var size: Int
}

struct SamplerSpec {
    var minFilter = MTLSamplerMinMagFilter.linear
    var magFilter = MTLSamplerMinMagFilter.linear
    var mipFilter = MTLSamplerMipFilter.notMipmapped
    var s = MTLSamplerAddressMode.clampToEdge
    var t = MTLSamplerAddressMode.clampToEdge
    var r = MTLSamplerAddressMode.clampToEdge
}

enum TextureSource {
    case file(URL)
    case solid([Double])
    case checker(size: Int, cells: Int, a: [Double], b: [Double])
    case gradient(size: Int)
}

struct TextureSpec {
    var stage: String
    var slot: Int
    var samplerSlot: Int
    var source: TextureSource
    var format: MTLPixelFormat
    var mipmaps: Bool
    var sampler: SamplerSpec
}

struct BlendSpec {
    var srcRGB: MTLBlendFactor, dstRGB: MTLBlendFactor, opRGB: MTLBlendOperation
    var srcA: MTLBlendFactor, dstA: MTLBlendFactor, opA: MTLBlendOperation
}

struct StateSpec {
    var cull = MTLCullMode.none
    var frontCCW = true
    var blend: BlendSpec?
    var depthCompare: MTLCompareFunction?
    var depthWrite = true
    var colorMask: MTLColorWriteMask = .all
    var wireframe = false
}

struct Spec {
    var width = 256
    var height = 256
    var clearColor: [Double] = [0, 0, 0, 1]
    var clearDepth = 1.0
    var vertex: StageSource
    var fragment: StageSource
    var topology = MTLPrimitiveType.triangle
    var vertexCount = 0
    var instanceCount = 1
    var indices: [UInt32]?
    var indexType = MTLIndexType.uint16
    var vertexBuffers: [VertexBufferSpec] = []
    var attributes: [AttributeSpec] = []
    var buffers: [BufferSpec] = []
    var textures: [TextureSpec] = []
    var state = StateSpec()
    var viewport: [Double]?
}

// MARK: Enum-Tabellen

func pick<T>(_ name: String?, _ table: [String: T], _ what: String, default def: T) throws -> T {
    guard let n = name else { return def }
    guard let v = table[n] else { throw HarnessError("\(what): '\(n)' unbekannt, erlaubt: \(table.keys.sorted())") }
    return v
}

let vertexFormats: [String: (MTLVertexFormat, Int)] = [
    "float": (.float, 4), "float2": (.float2, 8), "float3": (.float3, 12), "float4": (.float4, 16),
    "int": (.int, 4), "int2": (.int2, 8), "int3": (.int3, 12), "int4": (.int4, 16),
    "uint": (.uint, 4), "uint2": (.uint2, 8), "uint3": (.uint3, 12), "uint4": (.uint4, 16),
    "uchar4": (.uchar4, 4), "uchar4Normalized": (.uchar4Normalized, 4),
    "ushort2": (.ushort2, 4), "ushort4": (.ushort4, 8), "half2": (.half2, 4), "half4": (.half4, 8),
]
let topologies: [String: MTLPrimitiveType] = [
    "triangle": .triangle, "triangleStrip": .triangleStrip, "line": .line, "lineStrip": .lineStrip, "point": .point,
]
let blendFactors: [String: MTLBlendFactor] = [
    "zero": .zero, "one": .one, "sourceColor": .sourceColor, "oneMinusSourceColor": .oneMinusSourceColor,
    "sourceAlpha": .sourceAlpha, "oneMinusSourceAlpha": .oneMinusSourceAlpha, "destinationColor": .destinationColor,
    "oneMinusDestinationColor": .oneMinusDestinationColor, "destinationAlpha": .destinationAlpha,
    "oneMinusDestinationAlpha": .oneMinusDestinationAlpha,
]
let blendOps: [String: MTLBlendOperation] = ["add": .add, "subtract": .subtract, "reverseSubtract": .reverseSubtract, "min": .min, "max": .max]
let compares: [String: MTLCompareFunction] = [
    "never": .never, "less": .less, "equal": .equal, "lessEqual": .lessEqual, "greater": .greater,
    "notEqual": .notEqual, "greaterEqual": .greaterEqual, "always": .always,
]
let addressModes: [String: MTLSamplerAddressMode] = [
    "clamp": .clampToEdge, "repeat": .repeat, "mirror": .mirrorRepeat, "border": .clampToZero,
]
let filters: [String: MTLSamplerMinMagFilter] = ["nearest": .nearest, "linear": .linear]
let mipFilters: [String: MTLSamplerMipFilter] = ["none": .notMipmapped, "nearest": .nearest, "linear": .linear]
let texFormats: [String: MTLPixelFormat] = ["rgba8Unorm": .rgba8Unorm, "rgba8Unorm_srgb": .rgba8Unorm_srgb, "r8Unorm": .r8Unorm]

// MARK: Parser

func parseStage(_ o: Obj, base: URL) throws -> StageSource {
    var s = StageSource()
    if let p = try o.string("spirv") { s.spirv = resolve(p, base: base) }
    if let p = try o.string("msl") { s.msl = resolve(p, base: base) }
    guard (s.spirv == nil) != (s.msl == nil) else { throw HarnessError("\(o.path): genau eines aus 'spirv' oder 'msl' angeben") }
    s.entry = try o.string("entry") ?? "main0"
    s.flipVertY = try o.bool("flipVertY") ?? false
    s.fixupClipspace = try o.bool("fixupClipspace") ?? false
    s.extraArgs = try o.strings("spirvCrossArgs") ?? []
    try o.finish()
    return s
}

func parseSampler(_ o: Obj?) throws -> SamplerSpec {
    var s = SamplerSpec()
    guard let o = o else { return s }
    s.minFilter = try pick(o.string("min"), filters, "\(o.path).min", default: s.minFilter)
    s.magFilter = try pick(o.string("mag"), filters, "\(o.path).mag", default: s.magFilter)
    s.mipFilter = try pick(o.string("mip"), mipFilters, "\(o.path).mip", default: s.mipFilter)
    let all = try o.string("address")
    s.s = try pick(try o.string("s") ?? all, addressModes, "\(o.path).s", default: s.s)
    s.t = try pick(try o.string("t") ?? all, addressModes, "\(o.path).t", default: s.t)
    s.r = try pick(try o.string("r") ?? all, addressModes, "\(o.path).r", default: s.r)
    try o.finish()
    return s
}

func color4(_ d: [Double]?, _ path: String, default def: [Double]) throws -> [Double] {
    guard let d = d else { return def }
    guard d.count == 4 else { throw HarnessError("\(path): 4 Werte (RGBA, 0...1) erwartet") }
    return d
}

func parseBlend(_ o: Obj) throws -> BlendSpec? {
    if let preset = try o.string("preset") {
        try o.finish()
        switch preset {
        case "alpha": return BlendSpec(srcRGB: .sourceAlpha, dstRGB: .oneMinusSourceAlpha, opRGB: .add, srcA: .one, dstA: .oneMinusSourceAlpha, opA: .add)
        case "additive": return BlendSpec(srcRGB: .sourceAlpha, dstRGB: .one, opRGB: .add, srcA: .one, dstA: .one, opA: .add)
        case "premultiplied": return BlendSpec(srcRGB: .one, dstRGB: .oneMinusSourceAlpha, opRGB: .add, srcA: .one, dstA: .oneMinusSourceAlpha, opA: .add)
        default: throw HarnessError("\(o.path).preset: alpha, additive oder premultiplied erwartet")
        }
    }
    let b = BlendSpec(
        srcRGB: try pick(o.string("srcRGB"), blendFactors, "\(o.path).srcRGB", default: .one),
        dstRGB: try pick(o.string("dstRGB"), blendFactors, "\(o.path).dstRGB", default: .zero),
        opRGB: try pick(o.string("opRGB"), blendOps, "\(o.path).opRGB", default: .add),
        srcA: try pick(o.string("srcA"), blendFactors, "\(o.path).srcA", default: .one),
        dstA: try pick(o.string("dstA"), blendFactors, "\(o.path).dstA", default: .zero),
        opA: try pick(o.string("opA"), blendOps, "\(o.path).opA", default: .add))
    try o.finish()
    return b
}

func parseState(_ o: Obj?) throws -> StateSpec {
    var s = StateSpec()
    guard let o = o else { return s }
    s.cull = try pick(o.string("cull"), ["none": .none, "front": .front, "back": .back], "\(o.path).cull", default: .none)
    s.frontCCW = try pick(o.string("frontFace"), ["ccw": true, "cw": false], "\(o.path).frontFace", default: true)
    s.wireframe = try o.bool("wireframe") ?? false
    if let b = try o.obj("blend") { s.blend = try parseBlend(b) }
    if let d = try o.obj("depth") {
        s.depthCompare = try pick(d.string("test"), compares, "\(d.path).test", default: .less)
        s.depthWrite = try d.bool("write") ?? true
        try d.finish()
    }
    if let m = try o.string("colorMask") {
        var mask: MTLColorWriteMask = []
        for c in m {
            switch c {
            case "r": mask.insert(.red)
            case "g": mask.insert(.green)
            case "b": mask.insert(.blue)
            case "a": mask.insert(.alpha)
            default: throw HarnessError("\(o.path).colorMask: nur Zeichen r,g,b,a erlaubt")
            }
        }
        s.colorMask = mask
    }
    try o.finish()
    return s
}

func parseTexture(_ o: Obj, base: URL) throws -> TextureSpec {
    let stage = try o.string("stage") ?? "fragment"
    guard stage == "vertex" || stage == "fragment" else { throw HarnessError("\(o.path).stage: vertex oder fragment erwartet") }
    guard let slot = try o.int("slot") else { throw HarnessError("\(o.path): 'slot' fehlt") }
    let src: TextureSource
    if let f = try o.string("file") {
        src = .file(resolve(f, base: base))
    } else if let g = try o.obj("generate") {
        let kind = try g.string("kind") ?? ""
        let size = try g.int("size") ?? 64
        guard size > 0 && size <= 4096 else { throw HarnessError("\(g.path).size: 1...4096") }
        switch kind {
        case "solid": src = .solid(try color4(g.doubles("color"), "\(g.path).color", default: [1, 1, 1, 1]))
        case "checker":
            src = .checker(size: size, cells: try g.int("cells") ?? 8,
                           a: try color4(g.doubles("colorA"), "\(g.path).colorA", default: [1, 1, 1, 1]),
                           b: try color4(g.doubles("colorB"), "\(g.path).colorB", default: [0, 0, 0, 1]))
        case "gradient": src = .gradient(size: size)
        default: throw HarnessError("\(g.path).kind: solid, checker oder gradient erwartet")
        }
        try g.finish()
    } else {
        throw HarnessError("\(o.path): 'file' oder 'generate' erwartet")
    }
    let t = TextureSpec(
        stage: stage, slot: slot, samplerSlot: try o.int("samplerSlot") ?? slot, source: src,
        format: try pick(o.string("format"), texFormats, "\(o.path).format", default: .rgba8Unorm),
        mipmaps: try o.bool("mipmaps") ?? false,
        sampler: try parseSampler(o.obj("sampler")))
    try o.finish()
    return t
}

func parseSpec(_ json: Any, base: URL) throws -> Spec {
    let root = try Obj(json, path: "spec")
    guard let v = try root.obj("vertex"), let f = try root.obj("fragment") else { throw HarnessError("spec: 'vertex' und 'fragment' erforderlich") }
    var s = Spec(vertex: try parseStage(v, base: base), fragment: try parseStage(f, base: base))
    if let sz = try root.ints("size") {
        guard sz.count == 2, sz.allSatisfy({ $0 > 0 && $0 <= 8192 }) else { throw HarnessError("spec.size: [Breite, Hoehe] in 1...8192") }
        s.width = sz[0]; s.height = sz[1]
    }
    s.clearColor = try color4(root.doubles("clearColor"), "spec.clearColor", default: s.clearColor)
    s.clearDepth = try root.double("clearDepth") ?? 1.0
    s.topology = try pick(root.string("topology"), topologies, "spec.topology", default: .triangle)
    s.vertexCount = try root.int("vertexCount") ?? 0
    s.instanceCount = try root.int("instanceCount") ?? 1
    if let i = try root.ints("indices") {
        guard i.allSatisfy({ $0 >= 0 }) else { throw HarnessError("spec.indices: negative Werte") }
        s.indices = i.map { UInt32($0) }
    }
    s.indexType = try pick(root.string("indexType"), ["uint16": .uint16, "uint32": .uint32], "spec.indexType", default: .uint16)
    s.viewport = try root.doubles("viewport")
    if let vp = s.viewport, vp.count != 4 { throw HarnessError("spec.viewport: [x, y, Breite, Hoehe]") }

    for o in try root.objs("vertexBuffers") ?? [] {
        guard let slot = try o.int("slot") else { throw HarnessError("\(o.path): 'slot' fehlt") }
        let step = try pick(o.string("step"), ["vertex": false, "instance": true], "\(o.path).step", default: false)
        s.vertexBuffers.append(VertexBufferSpec(slot: slot, stride: try o.int("stride"), data: try readPayload(o, base: base), perInstance: step))
        try o.finish()
    }
    for o in try root.objs("attributes") ?? [] {
        guard let loc = try o.int("location"), let buf = try o.int("buffer") else { throw HarnessError("\(o.path): 'location' und 'buffer' erforderlich") }
        let (fmt, size) = try pick(o.string("format"), vertexFormats, "\(o.path).format", default: (.float4, 16))
        s.attributes.append(AttributeSpec(location: loc, buffer: buf, offset: try o.int("offset") ?? 0, format: fmt, size: size))
        try o.finish()
    }
    for o in try root.objs("buffers") ?? [] {
        let stage = try o.string("stage") ?? ""
        guard stage == "vertex" || stage == "fragment" else { throw HarnessError("\(o.path).stage: vertex oder fragment erwartet") }
        guard let slot = try o.int("slot") else { throw HarnessError("\(o.path): 'slot' fehlt") }
        var b = BufferSpec(stage: stage, slot: slot, minSize: try o.int("size") ?? 0, writes: [])
        if let ws = try o.objs("writes") {
            for w in ws {
                b.writes.append(BufferWrite(offset: try writeOffset(w), data: try readPayload(w, base: base)))
                try w.finish()
            }
        } else {
            b.writes.append(BufferWrite(offset: try writeOffset(o), data: try readPayload(o, base: base)))
        }
        try o.finish()
        s.buffers.append(b)
    }
    for o in try root.objs("textures") ?? [] { s.textures.append(try parseTexture(o, base: base)) }
    s.state = try parseState(root.obj("state"))
    try root.finish()
    return s
}

func writeOffset(_ o: Obj) throws -> Int {
    let bytes = try o.int("offset") ?? 0
    let floats = try o.int("offsetFloats") ?? 0
    return bytes + floats * 4
}

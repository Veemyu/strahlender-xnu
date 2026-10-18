import Foundation
import Metal
import ImageIO
import CoreGraphics
import UniformTypeIdentifiers

struct RenderResult {
    var width: Int
    var height: Int
    var rgba: [UInt8]
    var info: [String]
}

// Wie die GPU: Wert erst auf Float32 runden, dann exakt skalieren und runden
func toByte(_ v: Double) -> UInt8 { UInt8((min(max(Double(Float(v)), 0), 1) * 255).rounded()) }

/// Liefert RGBA8 (nicht-vormultipliziert fuer Generatoren; PNG-Dateien werden von ImageIO vormultipliziert geladen).
func loadTexturePixels(_ src: TextureSource) throws -> (w: Int, h: Int, rgba: [UInt8]) {
    switch src {
    case .solid(let c):
        return (4, 4, (0..<16).flatMap { _ in c.map(toByte) })
    case .checker(let size, let cells, let a, let b):
        guard cells > 0 else { throw HarnessError("checker.cells muss > 0 sein") }
        var px = [UInt8](); px.reserveCapacity(size * size * 4)
        for y in 0..<size { for x in 0..<size {
            let odd = ((x * cells / size) + (y * cells / size)) % 2 == 1
            px += (odd ? b : a).map(toByte)
        } }
        return (size, size, px)
    case .gradient(let size):
        var px = [UInt8](); px.reserveCapacity(size * size * 4)
        let d = Double(max(size - 1, 1))
        for y in 0..<size { for x in 0..<size {
            px += [toByte(Double(x) / d), toByte(Double(y) / d), 128, 255]
        } }
        return (size, size, px)
    case .file(let url):
        guard let isrc = CGImageSourceCreateWithURL(url as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(isrc, 0, nil) else {
            throw HarnessError("Textur \(url.path) nicht ladbar (PNG/JPEG/TIFF erwartet)")
        }
        let w = img.width, h = img.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let ok = px.withUnsafeMutableBytes { buf -> Bool in
            guard let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                      space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { throw HarnessError("Textur \(url.path): CGContext fehlgeschlagen") }
        return (w, h, px)
    }
}

func compile(_ device: MTLDevice, _ msl: String, entry: String, label: String) throws -> MTLFunction {
    let opts = MTLCompileOptions()
    opts.languageVersion = .version2_3
    let lib: MTLLibrary
    do { lib = try device.makeLibrary(source: msl, options: opts) } catch {
        throw HarnessError("Metal-Compiler (\(label)): \(error.localizedDescription)")
    }
    guard let fn = lib.makeFunction(name: entry) else {
        throw HarnessError("\(label): Funktion '\(entry)' nicht in MSL (vorhanden: \(lib.functionNames))")
    }
    return fn
}

func describe(_ args: [MTLArgument]) -> [String] {
    args.sorted { ($0.type.rawValue, $0.index) < ($1.type.rawValue, $1.index) }.map { a in
        let kind: String
        switch a.type {
        case .buffer: kind = "buffer(\(a.index)) \(a.bufferDataSize) B"
        case .texture: kind = "texture(\(a.index))"
        case .sampler: kind = "sampler(\(a.index))"
        default: kind = "arg(\(a.index))"
        }
        return "  \(kind) '\(a.name)'\(a.isActive ? "" : " [inaktiv]")"
    }
}

func render(_ spec: Spec, vsMSL: String, fsMSL: String, infoOnly: Bool) throws -> RenderResult {
    guard let device = MTLCreateSystemDefaultDevice(), let queue = device.makeCommandQueue() else { throw HarnessError("kein Metal-Geraet") }
    var info = ["device=\(device.name)"]
    let vfn = try compile(device, vsMSL, entry: spec.vertex.entry, label: "Vertex")
    let ffn = try compile(device, fsMSL, entry: spec.fragment.entry, label: "Fragment")
    info.append("vertex-attribute: " + vfn.vertexAttributes!.map { "\($0.attributeIndex)\($0.isActive ? "" : "(inaktiv)")" }.joined(separator: ","))

    let desc = MTLRenderPipelineDescriptor()
    desc.vertexFunction = vfn
    desc.fragmentFunction = ffn
    let ca = desc.colorAttachments[0]!
    ca.pixelFormat = .rgba8Unorm
    ca.writeMask = spec.state.colorMask
    if let b = spec.state.blend {
        ca.isBlendingEnabled = true
        ca.sourceRGBBlendFactor = b.srcRGB; ca.destinationRGBBlendFactor = b.dstRGB; ca.rgbBlendOperation = b.opRGB
        ca.sourceAlphaBlendFactor = b.srcA; ca.destinationAlphaBlendFactor = b.dstA; ca.alphaBlendOperation = b.opA
    }
    if spec.state.depthCompare != nil { desc.depthAttachmentPixelFormat = .depth32Float }
    let vd = MTLVertexDescriptor()
    var strides: [Int: Int] = [:]
    for a in spec.attributes {
        vd.attributes[a.location].format = a.format
        vd.attributes[a.location].offset = a.offset
        vd.attributes[a.location].bufferIndex = a.buffer
        strides[a.buffer] = max(strides[a.buffer] ?? 0, a.offset + a.size)
    }
    for vb in spec.vertexBuffers {
        let stride = vb.stride ?? strides[vb.slot] ?? 0
        guard stride > 0 else { throw HarnessError("Vertexpuffer \(vb.slot): Stride unbekannt (stride angeben oder Attribute definieren)") }
        vd.layouts[vb.slot].stride = stride
        vd.layouts[vb.slot].stepFunction = vb.perInstance ? .perInstance : .perVertex
    }
    for a in spec.attributes where !spec.vertexBuffers.contains(where: { $0.slot == a.buffer }) {
        throw HarnessError("Attribut \(a.location) verweist auf Vertexpuffer-Slot \(a.buffer), der nicht definiert ist")
    }
    if !vfn.vertexAttributes!.isEmpty { desc.vertexDescriptor = vd }

    for a in vfn.vertexAttributes! where a.isActive && !spec.attributes.contains(where: { $0.location == a.attributeIndex }) {
        throw HarnessError("Vertex-Attribut \(a.attributeIndex) '\(a.name)' ist aktiv, aber nicht in 'attributes' beschrieben")
    }
    var refl: MTLRenderPipelineReflection?
    let pso: MTLRenderPipelineState
    do {
        pso = try device.makeRenderPipelineState(descriptor: desc, options: [.argumentInfo, .bufferTypeInfo], reflection: &refl)
    } catch { throw HarnessError("Pipeline: \(error.localizedDescription)") }
    let vArgs = refl?.vertexArguments ?? [], fArgs = refl?.fragmentArguments ?? []
    info.append("vertex-bindings:"); info += describe(vArgs)
    info.append("fragment-bindings:"); info += describe(fArgs)
    if infoOnly { return RenderResult(width: 0, height: 0, rgba: [], info: info) }

    guard let cb = queue.makeCommandBuffer() else { throw HarnessError("Command-Buffer fehlgeschlagen") }

    // Ziel-Texturen
    let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba8Unorm, width: spec.width, height: spec.height, mipmapped: false)
    td.usage = [.renderTarget]; td.storageMode = .shared
    guard let color = device.makeTexture(descriptor: td) else { throw HarnessError("Farbtextur fehlgeschlagen") }
    let rp = MTLRenderPassDescriptor()
    rp.colorAttachments[0].texture = color
    rp.colorAttachments[0].loadAction = .clear
    rp.colorAttachments[0].storeAction = .store
    let cc = spec.clearColor
    rp.colorAttachments[0].clearColor = MTLClearColor(red: cc[0], green: cc[1], blue: cc[2], alpha: cc[3])
    var dss: MTLDepthStencilState?
    if let cmp = spec.state.depthCompare {
        let dd = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .depth32Float, width: spec.width, height: spec.height, mipmapped: false)
        dd.usage = [.renderTarget]; dd.storageMode = .private
        rp.depthAttachment.texture = device.makeTexture(descriptor: dd)
        rp.depthAttachment.loadAction = .clear
        rp.depthAttachment.storeAction = .dontCare
        rp.depthAttachment.clearDepth = spec.clearDepth
        let ds = MTLDepthStencilDescriptor()
        ds.depthCompareFunction = cmp
        ds.isDepthWriteEnabled = spec.state.depthWrite
        dss = device.makeDepthStencilState(descriptor: ds)
    }

    // Eingaben vorbereiten (Texturen mit Mipmaps brauchen vorher einen Blit)
    var textures: [(TextureSpec, MTLTexture, MTLSamplerState)] = []
    var needMips: [MTLTexture] = []
    for t in spec.textures {
        let (w, h, rgba) = try loadTexturePixels(t.source)
        let one = t.format == .r8Unorm
        let levels = t.mipmaps ? Int(log2(Double(max(w, h)))) + 1 : 1
        let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: t.format, width: w, height: h, mipmapped: false)
        d.mipmapLevelCount = levels
        d.usage = [.shaderRead]; d.storageMode = .shared
        guard let tex = device.makeTexture(descriptor: d) else { throw HarnessError("Textur (slot \(t.slot)) fehlgeschlagen") }
        let data: [UInt8] = one ? stride(from: 0, to: rgba.count, by: 4).map { rgba[$0] } : rgba
        data.withUnsafeBytes { tex.replace(region: MTLRegionMake2D(0, 0, w, h), mipmapLevel: 0, withBytes: $0.baseAddress!, bytesPerRow: w * (one ? 1 : 4)) }
        if levels > 1 { needMips.append(tex) }
        let sd = MTLSamplerDescriptor()
        sd.minFilter = t.sampler.minFilter; sd.magFilter = t.sampler.magFilter; sd.mipFilter = t.sampler.mipFilter
        sd.sAddressMode = t.sampler.s; sd.tAddressMode = t.sampler.t; sd.rAddressMode = t.sampler.r
        guard let smp = device.makeSamplerState(descriptor: sd) else { throw HarnessError("Sampler fehlgeschlagen") }
        textures.append((t, tex, smp))
    }
    if !needMips.isEmpty, let blit = cb.makeBlitCommandEncoder() {
        needMips.forEach { blit.generateMipmaps(for: $0) }
        blit.endEncoding()
    }

    guard let enc = cb.makeRenderCommandEncoder(descriptor: rp) else { throw HarnessError("Encoder fehlgeschlagen") }
    var encoderOpen = true
    defer { if encoderOpen { enc.endEncoding() } }
    enc.setRenderPipelineState(pso)
    if let dss = dss { enc.setDepthStencilState(dss) }
    enc.setCullMode(spec.state.cull)
    enc.setFrontFacing(spec.state.frontCCW ? .counterClockwise : .clockwise)
    if spec.state.wireframe { enc.setTriangleFillMode(.lines) }
    let vp = spec.viewport ?? [0, 0, Double(spec.width), Double(spec.height)]
    enc.setViewport(MTLViewport(originX: vp[0], originY: vp[1], width: vp[2], height: vp[3], znear: 0, zfar: 1))

    var inferredCount = 0
    for vb in spec.vertexBuffers {
        guard !vb.data.isEmpty, let buf = vb.data.withUnsafeBytes({ device.makeBuffer(bytes: $0.baseAddress!, length: vb.data.count, options: .storageModeShared) }) else {
            throw HarnessError("Vertexpuffer \(vb.slot): leer oder nicht anlegbar")
        }
        if spec.buffers.contains(where: { $0.stage == "vertex" && $0.slot == vb.slot }) {
            throw HarnessError("Slot \(vb.slot) ist gleichzeitig Vertexpuffer und Uniform-Buffer der Vertexstufe")
        }
        enc.setVertexBuffer(buf, offset: 0, index: vb.slot)
        if !vb.perInstance, let st = vb.stride ?? strides[vb.slot], st > 0 { inferredCount = max(inferredCount, vb.data.count / st) }
    }

    for stage in ["vertex", "fragment"] {
        let args = stage == "vertex" ? vArgs : fArgs
        let vbSlots = Set(stage == "vertex" ? spec.vertexBuffers.map { $0.slot } : [])
        for a in args where a.isActive {
            switch a.type {
            case .buffer:
                if vbSlots.contains(a.index) { continue }
                let given = spec.buffers.first { $0.stage == stage && $0.slot == a.index }
                var bytes = [UInt8](repeating: 0, count: max(a.bufferDataSize, given?.minSize ?? 0, 16))
                if let g = given {
                    for w in g.writes {
                        if w.offset + w.data.count > bytes.count { bytes += [UInt8](repeating: 0, count: w.offset + w.data.count - bytes.count) }
                        bytes.replaceSubrange(w.offset..<(w.offset + w.data.count), with: w.data)
                    }
                } else {
                    info.append("WARNUNG: \(stage)-Buffer \(a.index) '\(a.name)' nicht in 'buffers' -> mit Nullen belegt")
                }
                let buf = bytes.withUnsafeBytes { device.makeBuffer(bytes: $0.baseAddress!, length: bytes.count, options: .storageModeShared)! }
                if stage == "vertex" { enc.setVertexBuffer(buf, offset: 0, index: a.index) } else { enc.setFragmentBuffer(buf, offset: 0, index: a.index) }
            case .texture:
                guard let t = textures.first(where: { $0.0.stage == stage && $0.0.slot == a.index }) else {
                    throw HarnessError("\(stage)-Textur \(a.index) '\(a.name)' wird benutzt, ist aber nicht in 'textures' angegeben")
                }
                if stage == "vertex" { enc.setVertexTexture(t.1, index: a.index) } else { enc.setFragmentTexture(t.1, index: a.index) }
            case .sampler:
                guard let t = textures.first(where: { $0.0.stage == stage && $0.0.samplerSlot == a.index }) else {
                    throw HarnessError("\(stage)-Sampler \(a.index) '\(a.name)' wird benutzt, aber keine Textur mit samplerSlot \(a.index)")
                }
                if stage == "vertex" { enc.setVertexSamplerState(t.2, index: a.index) } else { enc.setFragmentSamplerState(t.2, index: a.index) }
            default: break
            }
        }
    }
    for t in spec.textures where !(t.stage == "vertex" ? vArgs : fArgs).contains(where: { $0.type == .texture && $0.index == t.slot && $0.isActive }) {
        info.append("WARNUNG: Textur \(t.stage)/\(t.slot) wird vom Shader nicht benutzt")
    }

    if let idx = spec.indices {
        let data = spec.indexType == .uint16 ? littleEndian(idx.map { UInt16(truncatingIfNeeded: $0) }) : littleEndian(idx)
        if spec.indexType == .uint16, idx.contains(where: { $0 > 0xFFFF }) { throw HarnessError("indices: Wert > 65535 bei uint16") }
        let ib = data.withUnsafeBytes { device.makeBuffer(bytes: $0.baseAddress!, length: data.count, options: .storageModeShared)! }
        enc.drawIndexedPrimitives(type: spec.topology, indexCount: idx.count, indexType: spec.indexType, indexBuffer: ib, indexBufferOffset: 0, instanceCount: spec.instanceCount)
    } else {
        let n = spec.vertexCount > 0 ? spec.vertexCount : inferredCount
        guard n > 0 else { throw HarnessError("vertexCount fehlt und laesst sich nicht aus den Vertexpuffern ableiten") }
        enc.drawPrimitives(type: spec.topology, vertexStart: 0, vertexCount: n, instanceCount: spec.instanceCount)
    }
    encoderOpen = false
    enc.endEncoding()
    cb.commit()
    cb.waitUntilCompleted()
    if let e = cb.error { throw HarnessError("GPU-Fehler: \(e.localizedDescription)") }

    var px = [UInt8](repeating: 0, count: spec.width * spec.height * 4)
    color.getBytes(&px, bytesPerRow: spec.width * 4, from: MTLRegionMake2D(0, 0, spec.width, spec.height), mipmapLevel: 0)
    return RenderResult(width: spec.width, height: spec.height, rgba: px, info: info)
}

/// Schreibt RGBA8 (nicht vormultipliziert) als PNG ueber ImageIO.
func writePNG(_ r: RenderResult, to url: URL) throws {
    let data = Data(r.rgba)
    guard let prov = CGDataProvider(data: data as CFData),
          let img = CGImage(width: r.width, height: r.height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: r.width * 4,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue), provider: prov,
                            decode: nil, shouldInterpolate: false, intent: .defaultIntent),
          let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw HarnessError("PNG-Ausgabe \(url.path) nicht anlegbar")
    }
    CGImageDestinationAddImage(dest, img, nil)
    guard CGImageDestinationFinalize(dest) else { throw HarnessError("PNG schreiben fehlgeschlagen: \(url.path)") }
}

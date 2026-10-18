// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "shader-harness",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "shader-harness",
            path: "Sources/shader-harness"
        )
    ]
)

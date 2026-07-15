// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "Thorn",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Thorn",
            path: "Sources/Thorn"
        ),
        .testTarget(
            name: "ThornTests",
            dependencies: ["Thorn"],
            path: "Tests/ThornTests"
        )
    ]
)

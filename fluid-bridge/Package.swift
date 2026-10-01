// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "FluidBridge",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "FluidBridge", targets: ["FluidBridge"])
    ],
    dependencies: [
        .package(
            url: "https://github.com/FluidInference/FluidAudio.git",
            revision: "c388107348134698135cfd34f3f59dc823b6e7ce"
        )
    ],
    targets: [
        .executableTarget(
            name: "FluidBridge",
            dependencies: [
                .product(name: "FluidAudio", package: "FluidAudio")
            ]
        )
    ],
    swiftLanguageVersions: [.v5]
)

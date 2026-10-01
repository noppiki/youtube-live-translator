import AVFoundation
import FluidAudio
import Foundation

struct BridgeConfig: Decodable {
    var diarization: Bool = false
}

struct Output: Encodable {
    var type: String
    var text: String? = nil
    var final: Bool? = nil
    var speaker: Int? = nil
    var changeAtMs: Int? = nil
    var message: String? = nil
}

final class JSONWriter: @unchecked Sendable {
    private let lock = NSLock()
    private let encoder = JSONEncoder()

    func send(_ output: Output) {
        lock.lock()
        defer { lock.unlock() }
        guard let data = try? encoder.encode(output),
              let line = String(data: data, encoding: .utf8) else { return }
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    }
}

actor SpeakerTracker {
    private let diarizer = SortformerDiarizer(config: .default)
    private var loaded = false
    private var currentSpeaker: Int?
    private var fedSeconds: Float = 0
    private let writer: JSONWriter

    init(writer: JSONWriter) {
        self.writer = writer
    }

    func load() async throws {
        let models = try await SortformerModels.loadFromHuggingFace(config: .default)
        diarizer.initialize(models: models)
        loaded = true
    }

    func feed(_ samples: [Float]) {
        guard loaded else { return }
        diarizer.addAudio(samples)
        fedSeconds += Float(samples.count) / 16_000

        do {
            guard let update = try diarizer.process() else { return }
            guard let latest = (update.finalizedSegments + update.tentativeSegments)
                .max(by: { ($0.endFrame, $0.startFrame) < ($1.endFrame, $1.startFrame) }) else { return }

            if currentSpeaker == nil {
                currentSpeaker = latest.speakerIndex
                writer.send(Output(type: "speaker", speaker: latest.speakerIndex,
                                   changeAtMs: Int(latest.startTime * 1000)))
                return
            }

            if currentSpeaker != latest.speakerIndex, latest.duration >= 0.5 {
                currentSpeaker = latest.speakerIndex
                writer.send(Output(type: "speaker", speaker: latest.speakerIndex,
                                   changeAtMs: Int(latest.startTime * 1000)))
            }
        } catch {
            writer.send(Output(type: "warning", message: "Diarization: \(error.localizedDescription)"))
        }
    }

    func shutdown() {
        diarizer.cleanup()
        loaded = false
    }
}

actor Engine {
    private let writer: JSONWriter
    private var manager: StreamingEouAsrManager?
    private var speakers: SpeakerTracker?
    private var lastText = ""
    private var configured = false

    init(writer: JSONWriter) {
        self.writer = writer
    }

    func configure(_ config: BridgeConfig) async throws {
        guard !configured else { return }

        let asr = StreamingEouAsrManager(chunkSize: .ms320, eouDebounceMs: 960)
        try await asr.loadModels()
        manager = asr

        if config.diarization {
            let tracker = SpeakerTracker(writer: writer)
            do {
                try await tracker.load()
                speakers = tracker
            } catch {
                writer.send(Output(type: "warning",
                                   message: "Speaker diarization unavailable: \(error.localizedDescription)"))
            }
        }

        configured = true
        writer.send(Output(type: "ready"))
    }

    private static func pcmBuffer(_ samples: [Float]) -> AVAudioPCMBuffer? {
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                         sampleRate: 16_000,
                                         channels: 1,
                                         interleaved: false),
              let buffer = AVAudioPCMBuffer(pcmFormat: format,
                                            frameCapacity: AVAudioFrameCount(samples.count)),
              let channel = buffer.floatChannelData else { return nil }

        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer {
            channel[0].update(from: $0.baseAddress!, count: samples.count)
        }
        return buffer
    }

    func feedPCM16(_ data: Data) async {
        guard let manager, configured else { return }

        let samples: [Float] = data.withUnsafeBytes { raw in
            let ints = raw.bindMemory(to: Int16.self)
            return ints.map { Float(Int16(littleEndian: $0)) / 32768.0 }
        }

        if let speakers {
            await speakers.feed(samples)
        }

        guard let buffer = Self.pcmBuffer(samples) else { return }

        do {
            _ = try await manager.process(audioBuffer: buffer)
            let tokens = await manager.getRawTokenStrings()
            let text = tokens.joined()
                .replacingOccurrences(of: "▁", with: " ")
                .replacingOccurrences(of: "  ", with: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)

            if !text.isEmpty, text != lastText {
                lastText = text
                writer.send(Output(type: "partial", text: text, final: false))
            }
        } catch {
            writer.send(Output(type: "error", message: error.localizedDescription))
        }
    }

    func finalize() async {
        guard let manager else { return }
        do {
            let text = try await manager.finish()
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                writer.send(Output(type: "final", text: text, final: true))
            }
            await manager.reset()
            lastText = ""
        } catch {
            writer.send(Output(type: "error", message: error.localizedDescription))
        }
    }

    func shutdown() async {
        if let speakers { await speakers.shutdown() }
        if let manager { await manager.cleanup() }
    }
}

func readExact(_ handle: FileHandle, count: Int) throws -> Data? {
    var data = Data()
    while data.count < count {
        guard let chunk = try handle.read(upToCount: count - data.count), !chunk.isEmpty else {
            return data.isEmpty ? nil : data
        }
        data.append(chunk)
    }
    return data
}

func readFrame(_ handle: FileHandle) throws -> Data? {
    guard let header = try readExact(handle, count: 4), header.count == 4 else { return nil }
    let length = header.withUnsafeBytes { raw -> UInt32 in
        raw.loadUnaligned(as: UInt32.self).littleEndian
    }
    guard length <= 4 * 1024 * 1024 else { throw NSError(domain: "FluidBridge", code: 1) }
    return try readExact(handle, count: Int(length))
}

@main
struct FluidBridge {
    static func main() async {
        let writer = JSONWriter()
        let engine = Engine(writer: writer)
        let input = FileHandle.standardInput

        do {
            while let frame = try readFrame(input), !frame.isEmpty {
                let kind = frame[frame.startIndex]
                let payload = frame.dropFirst()

                switch kind {
                case 0:
                    let config = try JSONDecoder().decode(BridgeConfig.self, from: Data(payload))
                    try await engine.configure(config)
                case 1:
                    await engine.feedPCM16(Data(payload))
                case 2:
                    await engine.finalize()
                default:
                    writer.send(Output(type: "warning", message: "Unknown frame type"))
                }
            }
        } catch {
            writer.send(Output(type: "error", message: error.localizedDescription))
        }

        await engine.shutdown()
    }
}

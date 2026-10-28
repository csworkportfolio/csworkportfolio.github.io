// Converts an iPhone HDR (HLG, BT.2020) video to standard video (SDR, BT.709) with Apple's own tone mapping, the
// way Photos shows it, so footage doesn't come out washed out. Used by tools/ai_marsmen.py.
//   swiftc -O tools/hdr_to_sdr.swift -o /tmp/hdr_to_sdr && /tmp/hdr_to_sdr in.MOV out.mov
import AVFoundation

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: hdr_to_sdr in out"); exit(1) }
let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
let out = URL(fileURLWithPath: args[2])
try? FileManager.default.removeItem(at: out)

let done = DispatchSemaphore(value: 0)
Task {
    do {
        let comp = try await AVMutableVideoComposition.videoComposition(withPropertiesOf: asset)
        comp.colorPrimaries = AVVideoColorPrimaries_ITU_R_709_2
        comp.colorTransferFunction = AVVideoTransferFunction_ITU_R_709_2
        comp.colorYCbCrMatrix = AVVideoYCbCrMatrix_ITU_R_709_2
        guard let export = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetHighestQuality) else { throw NSError(domain: "export", code: 1) }
        export.videoComposition = comp
        try await export.export(to: out, as: .mov)
    } catch {
        print("failed:", error); exit(1)
    }
    done.signal()
}
done.wait()

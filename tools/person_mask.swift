// Writes a grayscale person mask (white = the speaker) for every PNG frame in a folder, with Apple's Vision
// person segmentation, all on this Mac. Used by tools/ai_marsmen.py so captions can sit behind the speaker.
// Build: swiftc -O tools/person_mask.swift -o <somewhere>/person_mask   Run: person_mask <frames> <masks>
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
let inDir = URL(fileURLWithPath: args[1]), outDir = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let files = try FileManager.default.contentsOfDirectory(atPath: inDir.path).filter { $0.hasSuffix(".png") }.sorted()
let ctx = CIContext()
let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = .accurate
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
for name in files {
    let url = inDir.appendingPathComponent(name)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { continue }
    let handler = VNImageRequestHandler(cgImage: img)
    try handler.perform([request])
    guard let buf = request.results?.first?.pixelBuffer else { continue }
    // scale the mask up to the frame's size
    var mask = CIImage(cvPixelBuffer: buf)
    mask = mask.transformed(by: CGAffineTransform(scaleX: CGFloat(img.width) / mask.extent.width, y: CGFloat(img.height) / mask.extent.height))
    guard let cg = ctx.createCGImage(mask, from: CGRect(x: 0, y: 0, width: img.width, height: img.height)) else { continue }
    let dest = CGImageDestinationCreateWithURL(outDir.appendingPathComponent(name) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, cg, nil)
    CGImageDestinationFinalize(dest)
}
print("masks:", files.count)

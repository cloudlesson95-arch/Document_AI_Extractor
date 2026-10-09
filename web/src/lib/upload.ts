// The backend refuses larger files with a 413 (MAX_UPLOAD_MB, default 4). Checking here first also keeps a
// file from reaching Lambda's 6 MB request cap, whose rejection has no CORS headers for the browser to read.
export const MAX_UPLOAD_MB = 4;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

// Photos are redrawn as JPEG at most this long on their longest edge: sharp enough for the model to read
// small print, and a few hundred KB instead of a phone camera's 3-10 MB
export const MAX_IMAGE_EDGE = 2000;
const JPEG_QUALITY = 0.85;

/** The types the backend extracts, for the file picker's `accept`. */
export const ACCEPTED_TYPES = "image/jpeg,image/png,image/webp,application/pdf";
const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

/** The size scaled down to fit maxEdge on its longest side, keeping the aspect ratio; never scaled up. */
export function fitWithin(width: number, height: number, maxEdge = MAX_IMAGE_EDGE): { width: number; height: number } {
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/**
 * The file to upload. An image that is longer than MAX_IMAGE_EDGE, larger than MAX_UPLOAD_MB, or in a type
 * the backend doesn't take (e.g. HEIC, which Safari can decode) is redrawn as a JPEG that fits MAX_IMAGE_EDGE.
 * PDFs, small JPEG/PNG/WebP images and images the browser can't decode are returned as they are.
 */
export async function prepareUpload(file: File): Promise<File> {
  if (!file.type.startsWith("image/")) return file;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" }); // applies a photo's EXIF rotation
  } catch {
    return file; // the backend answers with a 415 if it can't take it either
  }
  try {
    const fits = Math.max(bitmap.width, bitmap.height) <= MAX_IMAGE_EDGE && file.size <= MAX_UPLOAD_BYTES;
    if (fits && ACCEPTED_IMAGE_TYPES.has(file.type)) return file;

    const { width, height } = fitWithin(bitmap.width, bitmap.height);
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.fillStyle = "#fff"; // JPEG has no transparency, which would otherwise turn black
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    const jpeg = await canvas.convertToBlob({ type: "image/jpeg", quality: JPEG_QUALITY });
    return new File([jpeg], `${file.name.replace(/\.[^.]*$/, "")}.jpg`, { type: "image/jpeg" });
  } finally {
    bitmap.close();
  }
}

/** Why this file is too large to upload, or null when it fits. */
export function tooLargeMessage(file: File): string | null {
  if (file.size <= MAX_UPLOAD_BYTES) return null;
  const hint = file.type === "application/pdf" ? "Try a PDF with fewer or smaller pages." : "Try a smaller image.";
  return `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is ${MAX_UPLOAD_MB} MB. ${hint}`;
}

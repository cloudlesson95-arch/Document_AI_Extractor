import { afterEach, describe, expect, it, vi } from "vitest";

import { fitWithin, MAX_UPLOAD_MB, prepareUpload, tooLargeMessage } from "./upload";

afterEach(() => {
  vi.unstubAllGlobals();
});

const MB = 1024 * 1024;

function fileOf(name: string, type: string, size = 1000) {
  return new File([new Uint8Array(size)], name, { type });
}

// Node has no image decoding or canvas: fake a decoded image of this size, and record what gets drawn
function stubBrowserImage(width: number, height: number) {
  const bitmap = { width, height, close: vi.fn() };
  const decode = vi.fn().mockResolvedValue(bitmap);
  const drawn: number[][] = [];
  vi.stubGlobal("createImageBitmap", decode);
  vi.stubGlobal("OffscreenCanvas", class {
    getContext() {
      return { fillRect: vi.fn(), drawImage: (_: unknown, ...box: number[]) => drawn.push(box) };
    }
    convertToBlob(options: { type: string }) {
      return Promise.resolve(new Blob(["jpeg bytes"], { type: options.type }));
    }
  });
  return { bitmap, decode, drawn };
}

describe("fitWithin", () => {
  it("scales the longest edge down to the limit and keeps the aspect ratio", () => {
    expect(fitWithin(4032, 3024)).toEqual({ width: 2000, height: 1500 });
    expect(fitWithin(1000, 3000)).toEqual({ width: 667, height: 2000 });
  });

  it("never scales up", () => {
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 });
  });
});

describe("prepareUpload", () => {
  it("sends a PDF as it is, without decoding it", async () => {
    const { decode } = stubBrowserImage(0, 0);
    const pdf = fileOf("invoice.pdf", "application/pdf", 5 * MB);

    expect(await prepareUpload(pdf)).toBe(pdf);
    expect(decode).not.toHaveBeenCalled();
  });

  it("sends a small JPEG as it is", async () => {
    stubBrowserImage(1200, 900);
    const photo = fileOf("receipt.jpg", "image/jpeg");

    expect(await prepareUpload(photo)).toBe(photo);
  });

  it("redraws a large photo as a JPEG that fits the limit, applying its EXIF rotation", async () => {
    const { bitmap, decode, drawn } = stubBrowserImage(3024, 4032);

    const prepared = await prepareUpload(fileOf("IMG_0042.png", "image/png", 6 * MB));

    expect(decode.mock.calls[0][1]).toEqual({ imageOrientation: "from-image" });
    expect(drawn).toEqual([[0, 0, 1500, 2000]]);
    expect([prepared.name, prepared.type]).toEqual(["IMG_0042.jpg", "image/jpeg"]);
    expect(bitmap.close).toHaveBeenCalled();
  });

  it("redraws an image in a type the backend doesn't take, even when small", async () => {
    const { drawn } = stubBrowserImage(1000, 800);

    const prepared = await prepareUpload(fileOf("IMG_0042.HEIC", "image/heic"));

    expect(drawn).toEqual([[0, 0, 1000, 800]]);
    expect([prepared.name, prepared.type]).toEqual(["IMG_0042.jpg", "image/jpeg"]);
  });

  it("sends an image the browser can't decode as it is", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new DOMException("undecodable")));
    const image = fileOf("scan.tiff", "image/tiff");

    expect(await prepareUpload(image)).toBe(image);
  });
});

describe("tooLargeMessage", () => {
  it("accepts a file at the cap and explains a larger one", () => {
    expect(tooLargeMessage(fileOf("a.pdf", "application/pdf", MAX_UPLOAD_MB * MB))).toBeNull();
    expect(tooLargeMessage(fileOf("a.pdf", "application/pdf", 5 * MB))).toBe(
      "This file is 5.0 MB; the limit is 4 MB. Try a PDF with fewer or smaller pages.");
  });
});

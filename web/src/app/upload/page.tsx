import type { Metadata } from "next";

import UploadForm from "@/components/UploadForm";
import { muted } from "@/components/ui";

export const metadata: Metadata = { title: "Upload · Document AI Extractor" };

export default function UploadPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Upload a receipt</h1>
      <p className={`mt-1 text-sm ${muted}`}>
        A photo or PDF of a receipt or invoice. Avoid documents that show card numbers or personal details:
        they are sent to the extraction model&apos;s provider.
      </p>
      <UploadForm />
    </>
  );
}

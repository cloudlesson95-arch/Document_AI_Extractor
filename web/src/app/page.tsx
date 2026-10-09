import Link from "next/link";

import BackendStatus from "@/components/BackendStatus";
import { muted, primaryButton, secondaryButton } from "@/components/ui";

export default function Home() {
  return (
    <div className="max-w-3xl">
      <h1 className="text-3xl font-semibold tracking-tight">Document AI Extractor</h1>
      <p className={`mt-2 ${muted}`}>
        Upload a receipt or invoice, review the extracted fields, and search your records.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href="/upload" className={primaryButton}>Upload a receipt</Link>
        <Link href="/receipts" className={secondaryButton}>Browse receipts</Link>
      </div>
      <div className="mt-8">
        <BackendStatus />
      </div>
    </div>
  );
}

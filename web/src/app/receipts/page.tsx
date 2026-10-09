import type { Metadata } from "next";
import { Suspense } from "react";

import ReceiptList from "@/components/ReceiptList";
import { muted } from "@/components/ui";

export const metadata: Metadata = { title: "Receipts · Document AI Extractor" };

export default function ReceiptsPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Receipts</h1>
      {/* ReceiptList reads its filters from the URL's query, which isn't known when the page is prerendered */}
      <Suspense fallback={<p className={`mt-6 text-sm ${muted}`}>Loading…</p>}>
        <ReceiptList />
      </Suspense>
    </>
  );
}

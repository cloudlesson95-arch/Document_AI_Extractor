import type { Metadata } from "next";
import { Suspense } from "react";

import ReceiptReview from "@/components/ReceiptReview";
import { muted } from "@/components/ui";

export const metadata: Metadata = { title: "Review · Document AI Extractor" };

export default function ReceiptPage({ params }: PageProps<"/receipts/[id]">) {
  // The id is only known at request time: the page prerenders the fallback and streams in the review
  return (
    <Suspense fallback={<p className={`text-sm ${muted}`}>Loading…</p>}>
      {params.then(({ id }) => <ReceiptReview id={id} />)}
    </Suspense>
  );
}

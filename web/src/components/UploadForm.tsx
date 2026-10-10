"use client";

import Link from "next/link";
import { useState } from "react";

import { api, type Receipt } from "@/lib/api";
import { errorMessage, formatAmount, formatMoney } from "@/lib/format";
import { ACCEPTED_TYPES, prepareUpload, tooLargeMessage } from "@/lib/upload";
import { errorText, muted, primaryButton } from "./ui";

type State =
  | { step: "idle" }
  | { step: "working"; message: string }
  | { step: "done"; receipt: Receipt }
  | { step: "failed"; message: string };

export default function UploadForm() {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<State>({ step: "idle" });

  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setState({ step: "working", message: "Preparing the file…" });
    try {
      const prepared = await prepareUpload(file);
      const tooLarge = tooLargeMessage(prepared);
      if (tooLarge) {
        setState({ step: "failed", message: tooLarge });
        return;
      }
      setState({ step: "working", message: "Extracting the fields; this usually takes 5 to 30 seconds…" });
      setState({ step: "done", receipt: await api.uploadReceipt(prepared) });
    } catch (error) {
      setState({ step: "failed", message: errorMessage(error) });
    }
  }

  return (
    <>
      <form onSubmit={upload} className="mt-6 flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept={ACCEPTED_TYPES}
          aria-label="Receipt file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setState({ step: "idle" });
          }}
          className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-black/5 file:px-3 file:py-2 file:text-sm file:font-medium dark:file:bg-white/10"
        />
        <button type="submit" className={primaryButton} disabled={!file || state.step === "working"}>
          Extract
        </button>
      </form>

      <div aria-live="polite" className="mt-4 text-sm">
        {state.step === "working" && <p className={muted}>{state.message}</p>}
        {state.step === "failed" && <p className={errorText}>{state.message}</p>}
      </div>
      {state.step === "done" && <ExtractedFields receipt={state.receipt} />}
    </>
  );
}

function ExtractedFields({ receipt }: { receipt: Receipt }) {
  return (
    <section className="mt-4 max-w-2xl rounded-lg border border-black/10 p-5 dark:border-white/15">
      <h2 className="font-semibold">Extracted fields</h2>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <dt className={muted}>Vendor</dt>
        <dd>{receipt.vendor ?? "–"}</dd>
        <dt className={muted}>Date</dt>
        <dd>{receipt.date ?? "–"}</dd>
        <dt className={muted}>Total</dt>
        <dd className="tabular-nums">{formatMoney(receipt.total_amount, receipt.currency)}</dd>
        <dt className={muted}>Category</dt>
        <dd>{receipt.category ?? <span className={muted}>None suggested</span>}</dd>
      </dl>

      {receipt.line_items.length > 0 && (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className={`text-left ${muted}`}>
              <th className="py-1 font-normal">Item</th>
              <th className="py-1 text-right font-normal">Qty</th>
              <th className="py-1 text-right font-normal">Unit price</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {receipt.line_items.map((item, index) => (
              <tr key={index} className="border-t border-black/5 dark:border-white/10">
                <td className="py-1">{item.description}</td>
                <td className="py-1 text-right">{item.quantity}</td>
                <td className="py-1 text-right">{formatAmount(item.unit_price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="mt-4 text-sm">
        Something wrong or missing?{" "}
        <Link href={`/receipts/${receipt.id}`} className="font-medium underline underline-offset-4">
          Review and correct it
        </Link>{" "}
        next to the original.
      </p>
    </section>
  );
}

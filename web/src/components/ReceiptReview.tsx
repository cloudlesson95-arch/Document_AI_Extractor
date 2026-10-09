"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, ApiError, fileUrl, type Receipt } from "@/lib/api";
import { errorMessage } from "@/lib/format";
import { hasChanges, newLineItem, toCorrection, toDraft, type LineItemDraft, type ReceiptDraft } from "@/lib/receiptForm";
import { errorText, input, muted, primaryButton, secondaryButton } from "./ui";

/** Loads one receipt, then shows its original next to a form that corrects its fields. */
export default function ReceiptReview({ id }: { id: string }) {
  const [loaded, setLoaded] = useState<{ receipt: Receipt } | { error: string } | null>(null);

  useEffect(() => {
    let active = true;
    api.getReceipt(id).then(
      (receipt) => active && setLoaded({ receipt }),
      (error) => active && setLoaded({ error: errorMessage(error) }),
    );
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <>
      <Link href="/receipts" className={`text-sm ${muted} hover:underline`}>← Receipts</Link>
      <div className="mt-4">
        {loaded === null ? (
          <p className={`text-sm ${muted}`}>Loading…</p>
        ) : "error" in loaded ? (
          <p className={`text-sm ${errorText}`}>{loaded.error}</p>
        ) : (
          <ReviewForm initial={loaded.receipt} />
        )}
      </div>
    </>
  );
}

type Status = { state: "editing" } | { state: "saving" } | { state: "saved"; changed: boolean } | { state: "failed"; message: string };
type TextField = Exclude<keyof ReceiptDraft, "line_items">;
type ItemField = Exclude<keyof LineItemDraft, "key">;

function ReviewForm({ initial }: { initial: Receipt }) {
  const [receipt, setReceipt] = useState(initial);
  const [saved, setSaved] = useState(() => toDraft(initial));
  const [draft, setDraft] = useState(saved);
  // A 422's messages by field path ("total_amount", "line_items.0.quantity"); each clears when its field is edited
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>({ state: "editing" });

  function edit(change: (draft: ReceiptDraft) => ReceiptDraft, clearErrors: (path: string) => boolean) {
    setDraft(change);
    setFieldErrors((errors) => Object.fromEntries(Object.entries(errors).filter(([path]) => !clearErrors(path))));
    setStatus({ state: "editing" });
  }
  const setField = (name: TextField, value: string) =>
    edit((current) => ({ ...current, [name]: value }), (path) => path === name);
  const setItem = (index: number, name: ItemField, value: string) =>
    edit(
      (current) => ({ ...current, line_items: current.line_items.map((item, i) => (i === index ? { ...item, [name]: value } : item)) }),
      (path) => path === `line_items.${index}.${name}`,
    );
  const addItem = () =>
    edit((current) => ({ ...current, line_items: [...current.line_items, newLineItem()] }), () => false);
  // Removing a row shifts the later rows' indexes, so their errors no longer point at the right row
  const removeItem = (index: number) =>
    edit((current) => ({ ...current, line_items: current.line_items.filter((_, i) => i !== index) }),
      (path) => path.startsWith("line_items."));

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus({ state: "saving" });
    try {
      const updated = await api.correctReceipt(receipt.id, toCorrection(draft));
      const next = toDraft(updated);
      // The backend leaves the record alone when no value changed (9.2 and 9.20 are equal)
      setStatus({ state: "saved", changed: updated.updated_at !== receipt.updated_at });
      setReceipt(updated);
      setSaved(next);
      setDraft(next);
      setFieldErrors({});
    } catch (error) {
      const errors = error instanceof ApiError ? error.fieldErrors : {};
      setFieldErrors(errors);
      setStatus({
        state: "failed",
        message: Object.keys(errors).length > 0 ? "Fix the marked fields, then save again." : errorMessage(error),
      });
    }
  }

  const dirty = hasChanges(draft, saved);
  const itemError = (index: number, name: ItemField) => fieldErrors[`line_items.${index}.${name}`];

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <Original receipt={receipt} />

      <form onSubmit={save} className="space-y-5">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{receipt.vendor ?? "Unknown vendor"}</h1>
            <span className="rounded-full border border-black/15 px-2 py-0.5 text-xs dark:border-white/20">
              {receipt.corrected ? "Corrected" : "As extracted"}
            </span>
          </div>
          <p className={`mt-1 text-xs ${muted}`}>Uploaded {new Date(receipt.created_at).toLocaleString()}</p>
        </div>

        <Field label="Vendor" error={fieldErrors.vendor}>
          <input value={draft.vendor} onChange={(e) => setField("vendor", e.target.value)} aria-invalid={Boolean(fieldErrors.vendor)} className={input} />
        </Field>
        <div className="grid grid-cols-[1fr_1fr_6rem] gap-3">
          <Field label="Date" error={fieldErrors.date}>
            <input type="date" value={draft.date} onChange={(e) => setField("date", e.target.value)} aria-invalid={Boolean(fieldErrors.date)} className={input} />
          </Field>
          <Field label="Total" error={fieldErrors.total_amount}>
            <input inputMode="decimal" value={draft.total_amount} onChange={(e) => setField("total_amount", e.target.value)} aria-invalid={Boolean(fieldErrors.total_amount)} className={`${input} tabular-nums`} />
          </Field>
          <Field label="Currency" error={fieldErrors.currency}>
            <input value={draft.currency} maxLength={3} placeholder="EUR" onChange={(e) => setField("currency", e.target.value)} aria-invalid={Boolean(fieldErrors.currency)} className={`${input} uppercase`} />
          </Field>
        </div>

        <fieldset>
          <legend className="text-sm font-medium">Line items</legend>
          {draft.line_items.length === 0 ? (
            <p className={`mt-1 text-sm ${muted}`}>None extracted.</p>
          ) : (
            <table className="mt-1 w-full text-sm">
              <thead>
                <tr className={`text-left text-xs ${muted}`}>
                  <th className="pb-1 font-normal">Description</th>
                  <th className="w-20 pb-1 pl-2 font-normal">Qty</th>
                  <th className="w-28 pb-1 pl-2 font-normal">Unit price</th>
                  <th className="w-8"><span className="sr-only">Remove</span></th>
                </tr>
              </thead>
              <tbody>
                {draft.line_items.map((item, index) => (
                  <tr key={item.key} className="align-top">
                    {(["description", "quantity", "unit_price"] as const).map((name) => (
                      <td key={name} className={`py-1 ${name === "description" ? "" : "pl-2"}`}>
                        <input
                          value={item[name]}
                          inputMode={name === "description" ? undefined : "decimal"}
                          aria-label={`Item ${index + 1} ${name.replace("_", " ")}`}
                          aria-invalid={Boolean(itemError(index, name))}
                          onChange={(e) => setItem(index, name, e.target.value)}
                          className={`${input} ${name === "description" ? "" : "tabular-nums"}`}
                        />
                        {itemError(index, name) && <span className={`mt-1 block text-xs ${errorText}`}>{itemError(index, name)}</span>}
                      </td>
                    ))}
                    <td className="py-1 pl-1">
                      <button type="button" onClick={() => removeItem(index)} aria-label={`Remove item ${index + 1}`} className={`px-2 py-1.5 ${muted} hover:text-red-600`}>
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button type="button" onClick={addItem} className={`mt-2 ${secondaryButton}`}>Add line item</button>
        </fieldset>

        <div className="flex flex-wrap items-center gap-3 border-t border-black/10 pt-4 dark:border-white/15">
          <button type="submit" className={primaryButton} disabled={!dirty || status.state === "saving"}>
            {status.state === "saving" ? "Saving…" : "Save corrections"}
          </button>
          <button
            type="button"
            className={secondaryButton}
            disabled={!dirty || status.state === "saving"}
            onClick={() => edit(() => saved, () => true)}
          >
            Discard changes
          </button>
          <p aria-live="polite" className="text-sm">
            {status.state === "saved" && (status.changed ? "Saved: the receipt is marked as corrected." : "No value changed, so nothing was saved.")}
            {status.state === "failed" && <span className={errorText}>{status.message}</span>}
          </p>
        </div>
      </form>
    </div>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {error && <span className={`mt-1 block text-xs ${errorText}`}>{error}</span>}
    </label>
  );
}

function Original({ receipt }: { receipt: Receipt }) {
  const url = fileUrl(receipt);
  return (
    <section aria-label="Original document">
      {receipt.mime_type === "application/pdf" ? (
        <iframe src={url} title="Original document" className="h-[75vh] w-full rounded-md border border-black/10 dark:border-white/15" />
      ) : (
        // The API serves the original; next/image would have the Next server fetch and re-encode it instead
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="Original receipt" className="w-full rounded-md border border-black/10 dark:border-white/15" />
      )}
      <a href={url} target="_blank" rel="noreferrer" className={`mt-2 inline-block text-sm ${muted} underline underline-offset-4`}>
        Open the original in a new tab
      </a>
    </section>
  );
}

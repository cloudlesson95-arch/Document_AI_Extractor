"use client";

import Form from "next/form";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api, CATEGORIES, toQuery, type Receipt, type ReceiptFilters } from "@/lib/api";
import { errorMessage, formatMoney } from "@/lib/format";
import { errorText, input, muted, primaryButton, secondaryButton } from "./ui";

// The filters live in the URL, so they survive going back from a receipt and a search can be bookmarked
const FILTER_NAMES = ["vendor_contains", "date_from", "date_to", "category"] as const;

function filtersOf(params: URLSearchParams): ReceiptFilters {
  return Object.fromEntries(FILTER_NAMES.map((name) => [name, params.get(name) ?? ""]));
}

type Result = { query: string; receipts: Receipt[] } | { query: string; error: string };

export default function ReceiptList() {
  const searchParams = useSearchParams();
  const filters = filtersOf(searchParams);
  const query = toQuery(filters); // only the filters that are set, so equal searches compare equal
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    let active = true;
    api.listReceipts(filtersOf(new URLSearchParams(query))).then(
      (receipts) => active && setResult({ query, receipts }),
      (error) => active && setResult({ query, error: errorMessage(error) }),
    );
    return () => {
      active = false;
    };
  }, [query]);

  return (
    <>
      {/* A GET form: submitting navigates to /receipts?vendor_contains=...; key resets the inputs when the URL changes */}
      <Form key={query} action="/receipts" replace className="mt-6 flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-sm">
          <span className="font-medium">Vendor</span>
          <input name="vendor_contains" type="search" defaultValue={filters.vendor_contains} placeholder="Part of the name" className={`mt-1 ${input}`} />
        </label>
        <label className="text-sm">
          <span className="font-medium">From</span>
          <input name="date_from" type="date" defaultValue={filters.date_from} className={`mt-1 ${input}`} />
        </label>
        <label className="text-sm">
          <span className="font-medium">To</span>
          <input name="date_to" type="date" defaultValue={filters.date_to} className={`mt-1 ${input}`} />
        </label>
        <label className="text-sm">
          <span className="font-medium">Category</span>
          <select name="category" defaultValue={filters.category} className={`mt-1 ${input}`}>
            <option value="">All</option>
            {CATEGORIES.map((category) => <option key={category}>{category}</option>)}
          </select>
        </label>
        <button type="submit" className={primaryButton}>Search</button>
        {query && <Link href="/receipts" className={secondaryButton}>Clear</Link>}
      </Form>
      {query && <p className={`mt-2 text-xs ${muted}`}>Receipts whose vendor, date or category is unknown never match a filter on it.</p>}

      <div className="mt-6">
        {result?.query !== query ? (
          <p className={`text-sm ${muted}`}>Loading…</p>
        ) : "error" in result ? (
          <p className={`text-sm ${errorText}`}>{result.error}</p>
        ) : result.receipts.length === 0 ? (
          <p className={`text-sm ${muted}`}>
            {query ? "No receipts match these filters." : <>No receipts yet. <Link href="/upload" className="underline underline-offset-4">Upload one</Link>.</>}
          </p>
        ) : (
          <ReceiptTable receipts={result.receipts} />
        )}
      </div>
    </>
  );
}

function ReceiptTable({ receipts }: { receipts: Receipt[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className={`text-left ${muted}`}>
            <th className="py-2 pr-4 font-normal">Vendor</th>
            <th className="py-2 pr-4 font-normal">Date</th>
            <th className="py-2 pr-4 font-normal">Category</th>
            <th className="py-2 pr-4 text-right font-normal">Total</th>
            <th className="py-2 font-normal">Status</th>
          </tr>
        </thead>
        <tbody>
          {receipts.map((receipt) => (
            <tr key={receipt.id} className="border-t border-black/10 dark:border-white/15">
              <td className="py-2 pr-4">
                <Link href={`/receipts/${receipt.id}`} className="font-medium underline-offset-4 hover:underline">
                  {receipt.vendor ?? "Unknown vendor"}
                </Link>
              </td>
              <td className="py-2 pr-4 tabular-nums">{receipt.date ?? "–"}</td>
              <td className={`py-2 pr-4 ${receipt.category ? "" : muted}`}>{receipt.category ?? "Uncategorized"}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{formatMoney(receipt.total_amount, receipt.currency)}</td>
              <td className={`py-2 ${receipt.corrected ? "" : muted}`}>{receipt.corrected ? "Corrected" : "As extracted"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={`mt-3 text-xs ${muted}`}>{receipts.length === 1 ? "1 receipt" : `${receipts.length} receipts`}, newest first</p>
    </div>
  );
}

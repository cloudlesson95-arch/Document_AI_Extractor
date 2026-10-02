import BackendStatus from "@/components/BackendStatus";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Document AI Extractor</h1>
      <p className="mt-2 text-zinc-600 dark:text-zinc-400">
        Upload a receipt or invoice, review the extracted fields, and search your records.
      </p>
      <div className="mt-8">
        <BackendStatus />
      </div>
    </main>
  );
}

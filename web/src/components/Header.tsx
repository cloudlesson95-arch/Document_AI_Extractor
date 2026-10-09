"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

const PAGES = [
  { href: "/upload", label: "Upload" },
  { href: "/receipts", label: "Receipts" },
];

export default function Header() {
  return (
    <header className="border-b border-black/10 dark:border-white/15">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-semibold">
          Document AI Extractor
        </Link>
        <nav className="flex gap-4 text-sm">
          {/* usePathname waits for the URL on /receipts/[id], whose id isn't known when pages are prerendered;
              until then, the links show without the current page marked */}
          <Suspense fallback={<NavLinks pathname={null} />}>
            <CurrentNavLinks />
          </Suspense>
        </nav>
      </div>
    </header>
  );
}

function CurrentNavLinks() {
  return <NavLinks pathname={usePathname()} />;
}

function NavLinks({ pathname }: { pathname: string | null }) {
  return PAGES.map(({ href, label }) => {
    const current = pathname === href || Boolean(pathname?.startsWith(`${href}/`));
    return (
      <Link
        key={href}
        href={href}
        aria-current={current ? "page" : undefined}
        className={current ? "font-medium underline underline-offset-4" : "opacity-70 hover:opacity-100"}
      >
        {label}
      </Link>
    );
  });
}

// Shared Tailwind classes, so buttons and inputs look the same on every page
export const primaryButton =
  "inline-flex items-center rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
export const secondaryButton =
  "inline-flex items-center rounded-md border border-black/15 px-4 py-2 text-sm font-medium hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10";
export const input =
  "w-full rounded-md border border-black/15 bg-transparent px-3 py-1.5 text-sm dark:border-white/20 aria-[invalid=true]:border-red-500";
export const muted = "text-zinc-600 dark:text-zinc-400";
export const errorText = "text-red-600 dark:text-red-400";

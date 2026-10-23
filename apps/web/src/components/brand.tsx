import { cn } from "@/lib/cn";

/** The AgentStudio mark: one step branching into two, on the brand orange. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={cn("size-7", className)}>
      <rect width="64" height="64" rx="16" fill="var(--primary)" />
      <path
        d="M23 32h5c5 0 6-12 12-12h1M28 32c5 0 6 12 12 12h1"
        stroke="var(--primary-foreground)"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="18" cy="32" r="6" fill="var(--primary-foreground)" />
      <circle cx="46" cy="20" r="6" fill="var(--primary-foreground)" />
      <circle cx="46" cy="44" r="6" fill="var(--primary-foreground)" />
    </svg>
  );
}

export function Wordmark({ name, className }: { name: string; className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="text-[15px] font-semibold tracking-tight">{name}</span>
    </span>
  );
}

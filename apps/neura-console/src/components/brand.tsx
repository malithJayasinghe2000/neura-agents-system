/** The wordmark. One definition, so it cannot drift between screens. */
export function Brand({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <span
        aria-hidden
        className="grid size-8 place-items-center rounded-lg bg-foreground text-background text-sm font-semibold tracking-tight"
      >
        5N
      </span>
      <span className="text-base font-semibold tracking-tight">FiveNeurals</span>
    </div>
  );
}

import { cn } from "@/lib/utils"

interface SkeletonProps extends React.ComponentProps<"div"> {
  variant?: "default" | "card" | "text" | "circle"
}

function Skeleton({ className, variant = "default", ...props }: SkeletonProps) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "motion-essential relative overflow-hidden rounded-md bg-muted",
        variant === "card" && "rounded-2xl min-h-[180px]",
        variant === "text" && "rounded h-4",
        variant === "circle" && "rounded-full aspect-square",
        className
      )}
      {...props}
    >
      {/* Sweeping shimmer (token-driven so it stays alive under reduced motion) */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 animate-shimmer-sweep bg-gradient-to-r from-transparent via-white/20 to-transparent dark:via-white/5"
      />
    </div>
  )
}

export { Skeleton }

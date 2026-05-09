import { cn } from "@/lib/utils"

interface SkeletonProps extends React.ComponentProps<"div"> {
  variant?: "default" | "card" | "text" | "circle"
}

function Skeleton({ className, variant = "default", ...props }: SkeletonProps) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "animate-pulse rounded-md bg-muted",
        variant === "card" && "rounded-2xl min-h-[180px]",
        variant === "text" && "rounded h-4",
        variant === "circle" && "rounded-full aspect-square",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
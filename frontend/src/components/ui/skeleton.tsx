import { cn } from "@/lib/utils"

interface SkeletonProps extends React.ComponentProps<"div"> {
  variant?: "default" | "card" | "text" | "circle"
}

function Skeleton({ className, variant = "default", ...props }: SkeletonProps) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "relative overflow-hidden rounded-md bg-muted before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent dark:before:via-white/5",
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
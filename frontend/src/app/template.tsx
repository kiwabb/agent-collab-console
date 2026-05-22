"use client"

// Lightweight page-transition fade. Previously used framer-motion spring
// (260/20) which took ~400ms to fully settle and remounted the whole subtree
// each navigation, making page switches feel sluggish. CSS-only fade keeps
// the polish without the perceived latency.
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <div className="animate-[fadeIn_80ms_ease-out]">
      {children}
    </div>
  )
}

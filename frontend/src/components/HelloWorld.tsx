import * as React from "react";
import { cn } from "@/lib/utils";

interface HelloWorldProps {
  className?: string;
}

export function HelloWorld({ className }: HelloWorldProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-center p-6 rounded-2xl bg-brand/5 border border-brand/20",
        className,
      )}
    >
      <h1 className="text-4xl font-black tracking-tight text-brand">Hello World</h1>
    </div>
  );
}

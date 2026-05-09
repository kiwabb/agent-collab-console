"use client";

import { Component, type ReactNode, type ReactElement } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
  fallback?: ReactElement;
  onRetry?: () => void;
  title?: string;
  description?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    this.props.onRetry?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
          <div className="size-12 rounded-2xl bg-error/10 border border-error/20 flex items-center justify-center">
            <AlertCircle size={24} className="text-error" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-bold text-foreground">
              {this.props.title ?? "Something went wrong"}
            </p>
            {this.props.description && (
              <p className="text-xs text-text-muted">{this.props.description}</p>
            )}
            {this.state.error && (
              <p className="text-[10px] text-text-muted/60 font-mono mt-2 p-2 bg-surface-raised rounded-lg">
                {this.state.error.message}
              </p>
            )}
          </div>
          {this.props.onRetry && (
            <button
              onClick={this.handleRetry}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg bg-error/10 text-error text-xs font-bold",
                "border border-error/20 hover:bg-error/20 transition-all active:scale-[0.98]"
              )}
            >
              <RotateCcw size={14} />
              Retry
            </button>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

interface AsyncBoundaryProps {
  children: ReactNode;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  loadingComponent?: ReactElement;
  skeleton?: ReactElement;
}

export function AsyncBoundary({
  children,
  isLoading = false,
  error,
  onRetry,
  loadingComponent,
  skeleton,
}: AsyncBoundaryProps) {
  if (isLoading) {
    if (loadingComponent) return loadingComponent;
    if (skeleton) return skeleton;
    return (
      <div className="flex items-center justify-center p-8">
        <div className="size-6 rounded-full border-2 border-brand/30 border-t-brand animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
        <div className="size-10 rounded-xl bg-error/10 border border-error/20 flex items-center justify-center">
          <AlertCircle size={20} className="text-error" />
        </div>
        <p className="text-xs text-text-muted">{error}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg bg-error/10 text-error text-xs font-bold",
              "border border-error/20 hover:bg-error/20 transition-all active:scale-[0.98]"
            )}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        )}
      </div>
    );
  }

  return <>{children}</>;
}
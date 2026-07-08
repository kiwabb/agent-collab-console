"use client";

import { Component, type ReactNode, type ReactElement } from "react";
import { AlertCircle, RotateCcw, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactElement;
  onRetry?: () => void;
  title?: string;
  description?: string;
  error?: Error | null;
}

interface State {
  hasError: boolean;
  error: Error | null;
  showStack: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, showStack: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, showStack: false };
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, showStack: false });
    this.props.onRetry?.();
  };

  toggleStack = () => {
    this.setState((prev) => ({ showStack: !prev.showStack }));
  };

  override render() {
    const errorToShow = this.state.error || this.props.error;
    const hasError = this.state.hasError || !!this.props.error;

    if (hasError && errorToShow) {
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
            <div className="mt-3 space-y-2">
              <button
                onClick={this.toggleStack}
                className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-text-muted hover:text-foreground transition-colors"
              >
                {this.state.showStack ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                Error Details
              </button>
              {this.state.showStack && (
                <div className="text-left">
                  <div className="font-mono text-[10px] text-error/80 bg-surface-raised rounded-lg p-3 overflow-x-auto border border-error/20">
                    <div className="font-bold mb-1">
                      {errorToShow.name}: {errorToShow.message}
                    </div>
                    {errorToShow.stack && (
                      <pre className="whitespace-pre-wrap text-[9px] opacity-70 leading-relaxed max-h-48 overflow-y-auto">
                        {errorToShow.stack}
                      </pre>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
          {this.props.onRetry && (
            <button
              onClick={this.handleRetry}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg bg-error/10 text-error text-xs font-bold",
                "border border-error/20 hover:bg-error/20 transition-all active:scale-[0.98]",
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
  errorDetail?: string | null;
  onRetry?: () => void;
  loadingComponent?: ReactElement;
  skeleton?: ReactElement;
}

export function AsyncBoundary({
  children,
  isLoading = false,
  error,
  errorDetail,
  onRetry,
  loadingComponent,
  skeleton,
}: AsyncBoundaryProps) {
  const [showDetail, setShowDetail] = useState(false);

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
        {errorDetail && (
          <div className="space-y-2">
            <button
              onClick={() => setShowDetail(!showDetail)}
              className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-text-muted hover:text-foreground transition-colors"
            >
              {showDetail ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              Technical Details
            </button>
            {showDetail && (
              <pre className="text-[9px] font-mono text-text-muted/60 bg-surface-raised p-3 rounded-lg text-left max-w-md overflow-x-auto border border-border-subtle">
                {errorDetail}
              </pre>
            )}
          </div>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg bg-error/10 text-error text-xs font-bold",
              "border border-error/20 hover:bg-error/20 transition-all active:scale-[0.98]",
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

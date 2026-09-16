import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex min-h-[200px] flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-critical/10">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className="text-critical">
              <path d="M12 3.5 3.5 18.5h17L12 3.5Z" />
              <path d="M12 10v3.5" />
              <path d="M12 16.5h.01" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold">Something went wrong</p>
            <p className="mt-1 max-w-md text-xs text-ink-muted">
              {this.state.error?.message || "An unexpected error occurred."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-2 rounded-lg bg-brand px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-brand-bright"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

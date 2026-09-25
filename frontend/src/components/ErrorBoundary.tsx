import { Component, type ErrorInfo, type ReactNode } from "react";
import { AgentAvatar } from "./AgentAvatar";
import { IconRefresh } from "./icons";
import { Button } from "./ui";

interface Props {
  children: ReactNode;
  /** Changing this clears the error — pass the route so navigating away recovers. */
  resetKey?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error && previous.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    // A chunk that failed to load after a deploy is fixed by a reload, not a retry.
    const staleBuild = /dynamically imported module|Failed to fetch|Loading chunk/i.test(this.state.error.message);
    return (
      <div role="alert" className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 py-16 text-center">
        <AgentAvatar state="error" size="md" />
        <div>
          <p className="text-base font-semibold text-ink">
            {staleBuild ? "A newer version is available" : "This screen hit a snag"}
          </p>
          <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-ink-secondary">
            {staleBuild
              ? "Reload to pick up the latest console."
              : this.state.error.message || "An unexpected error occurred."}
          </p>
        </div>
        <div className="flex gap-2">
          {!staleBuild && (
            <Button icon={<IconRefresh size={14} />} onClick={() => this.setState({ error: null })}>
              Try again
            </Button>
          )}
          <Button variant={staleBuild ? "primary" : "secondary"} onClick={() => window.location.reload()}>
            Reload page
          </Button>
        </div>
      </div>
    );
  }
}

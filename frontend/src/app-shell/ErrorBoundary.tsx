import React from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  public state: ErrorBoundaryState = {
    hasError: false,
    message: '',
  };

  public static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      message: error.message || '前端渲染发生未预期异常。',
    };
  }

  public render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <main className="mx-auto max-w-reading px-4 py-12">
          <div
            role="alert"
            className="rounded-control border border-red-200 bg-surface-raised p-6"
          >
            <h1 className="text-xl font-semibold text-feedback-error">
              页面加载遇到问题
            </h1>
            <p className="mt-2 text-sm text-text-secondary">
              {this.state.message}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 h-10 rounded-control bg-action-primary px-4 text-sm font-semibold text-white hover:bg-action-primary-hover"
            >
              重新加载页面
            </button>
          </div>
        </main>
      );
    }

    return this.props.children;
  }
}

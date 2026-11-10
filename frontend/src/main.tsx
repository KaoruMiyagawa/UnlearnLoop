import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './app-shell/ErrorBoundary';
import { ThemeProvider } from './design-system/ThemeProvider';
import './design-system/tokens.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Failed to locate #root container element in index.html');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <ErrorBoundary><App /></ErrorBoundary>
    </ThemeProvider>
  </React.StrictMode>,
);

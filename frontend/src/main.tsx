import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './app-shell/ErrorBoundary';
import './design-system/tokens.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Failed to locate #root container element in index.html');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);

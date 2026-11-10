import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';

export type ThemeName = 'premium' | 'noir';
const STORAGE_KEY = 'verbatrail.design.theme';
function readTheme(): ThemeName {
  if (typeof document !== 'undefined' && document.documentElement.dataset.theme === 'noir') return 'noir';
  try { return window.localStorage.getItem(STORAGE_KEY) === 'noir' ? 'noir' : 'premium'; } catch { return 'premium'; }
}
interface ThemeContextValue { theme: ThemeName; toggleTheme: () => void }
const ThemeContext = createContext<ThemeContextValue | null>(null);

export const ThemeProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [theme, setTheme] = useState<ThemeName>(readTheme);
  const toggleTheme = useCallback(() => {
    setTheme(current => {
      const next: ThemeName = current === 'premium' ? 'noir' : 'premium';
      document.documentElement.dataset.theme = next;
      try { window.localStorage.setItem(STORAGE_KEY, next); } catch { /* Theme still changes for this page. */ }
      return next;
    });
  }, []);
  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}

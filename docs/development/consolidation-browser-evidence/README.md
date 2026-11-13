# Consolidation browser smoke

The new VerbaTrail checkout was launched locally with a fresh temporary SQLite database at `D:\Temp\verbatrail-consolidation-smoke-20261110.sqlite`. Headless Chrome connected through the Chrome DevTools Protocol. The server was configured with `MODEL_PROVIDER=fake` and remote model calls disabled.

Desktop browser checks confirmed the VerbaTrail home page and both visual themes, retention of the current route while switching themes, restoration of an existing Academic Reading session, and access to a separate General Training Reading session with its own passage and question.

At a 390 CSS-pixel viewport, the Premium and Noir home and Reading pages all measured `document.documentElement.scrollWidth === 390`; the Reading passage remained visible. Screenshots are stored next to this report. The measurements are in `mobile-layout.json` and the machine-readable summary is `browser-smoke.json`.

This was a smoke pass for startup, page navigation, theme persistence, session restoration and examination-mode separation. It did not submit an answer or execute diagnosis in the browser during this consolidation pass. The fake provider does not validate real AI personalized diagnosis. Existing IELTS-1 browser acceptance evidence remains archived at `../theme-visual-acceptance/`.
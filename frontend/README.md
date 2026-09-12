# TripFinder — frontend

Next.js (App Router) + React + TypeScript. This is one of three processes; see the
[root README](../README.md) for what the project is and how to run the whole thing.

```bash
npm install
npm run dev        # http://localhost:3000 — needs the API on :8000
npm run test       # Vitest
npm run lint
npm run typecheck
npx playwright test
```

`NEXT_PUBLIC_API_URL` points at the backend (default `http://localhost:8000`).

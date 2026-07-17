# BI System Frontend

React, TypeScript, Vite, Ant Design, TanStack Query, and React Router power the BI system web shell.

## Commands

- `npm install`: install dependencies from `package-lock.json`.
- `npm run dev`: start the local Vite development server.
- `npm run check`: run lint, Prettier, TypeScript, and Vitest checks.
- `npm run build`: run type checks and create the production build.

The development server proxies `/api/v1` to `http://localhost:8000`. Keep the API on the same origin in production and route `/api` through the deployment reverse proxy. An existing `.env.local` overrides this default and should use `VITE_API_BASE_URL=/api/v1`. A separate API origin is supported only when it remains same-site and the backend `BI_CORS_ORIGINS` allowlist is configured; cross-site authentication requires a separate cookie and CSRF design. Authentication uses the HttpOnly session cookie, and the client never stores tokens in browser storage.

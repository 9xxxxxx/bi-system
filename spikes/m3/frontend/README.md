# M3 chart and layout spike

This isolated spike validates ECharts 6.1.0 with React Grid Layout 2.2.3 and
GridStack 12.6.0 without changing production dependencies.

## Commands

Use the repository-required Node 24.x and npm 11.18.x for final gate evidence.

```powershell
cd C:\Dev\bi-system\spikes\m3\frontend
npm ci
npm test
npm run build
npm run dev -- --port 4175 --strictPort
```

Open `http://127.0.0.1:4175/`. The main canvas uses React Grid Layout. Select
`候选对比` to lazy-load the runnable GridStack comparison.

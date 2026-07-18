# M3 Chart And Layout Spike Evaluation

## 1. Decision

**M3-R0 architecture selection: accepted.**

- Chart library: ECharts 6.1.0, provided the production dashboard preserves the
  proven dynamic import boundary. ECharts is rejected for the initial app
  closure.
- Layout library: React Grid Layout 2.2.3.
- Rejected production alternative: GridStack 12.6.0 remains a lazy spike-only
  fallback.

This decision permits M3-R1 contract and domain implementation to begin. It does
not add a production dependency, route, migration or feature page. The winner
dependencies require a separate reviewable dependency commit, and that commit
must rerun the bundle/license evidence against the production entry.

The runnable source and lockfile remain isolated under `spikes/m3/frontend/`.

## 2. Runtime And Scope

Final evidence used:

- Node 24.18.0 and npm 11.18.0 from the ignored isolated runtime;
- React/React DOM 19.2.7 and Vite 8.1.1;
- Headless Chrome 149 and Microsoft Edge 150;
- desktop 1440 x 900 and mobile 390 x 844;
- default seven-widget dashboard plus deterministic 1/20/50 stress layouts.

The prototype covers KPI, grouped bar, line, donut and detail table rendering;
separate desktop/mobile profiles; layout save/reload; real drag and resize;
typed chart event context; 2x PNG; themes; loading/empty/error states; accessible
tables; and reduced-motion behavior.

Frontend review corrections included in the accepted spike:

- chart clicks use the governed dimension UUID and canonical bucket value;
- serialized layouts are strictly validated before reload;
- the mobile filter is a working read-only disclosure with no edit affordance;
- the grouped bar accessibility table includes both revenue and target;
- ECharts animation is disabled when reduced motion is requested;
- Vite statically defines only `process.env.NODE_ENV`, avoiding a browser Node
  polyfill required by neither the domain nor the production app.

## 3. Candidate Comparison

| Criterion | React Grid Layout 2.2.3 | GridStack 12.6.0 |
|---|---|---|
| License | MIT | MIT |
| React model | Native typed React component/hooks | Imperative DOM engine; React adapter required |
| Runtime | Real drag/resize and snapshot restore pass | Lazy candidate mounts three items and real drag passes |
| Independent profiles | Plain serializable desktop/mobile layout data | Adapter/reconciliation work required |
| Initial gzip | 21.33 kB JS + 0.56 kB CSS | Not initial; 23.57 kB JS + 0.94 kB CSS lazy |
| StrictMode/lifecycle | Documented support; low adapter cost | Explicit initialize/destroy ownership required |
| Keyboard editing | Application controls required | Application controls required |
| Decision | **Winner** | Spike-only fallback |

The winner uses a 12-column grid, 44 px row height, no overlapping items and
vertical compaction. The persisted server contract remains library-neutral.
Desktop and mobile profiles are independent; mobile rendering is read-only.

Neither candidate provides a complete keyboard repositioning workflow. M3-R3
must add explicit move/resize commands or X/Y/W/H controls; pointer drag cannot
be the sole production path.

## 4. License Evidence

`docs/verification/licenses-m3.csv` is generated from the locked installed
production graph. It contains 19 direct/transitive packages:

| License | Packages |
|---|---:|
| MIT | 15 |
| 0BSD | 1 |
| Apache-2.0 | 1 |
| BSD-3-Clause | 1 |
| ISC | 1 |

Every row records the package version, direct/transitive relationship,
license/copyright evidence file and lock path. There are zero unknown licenses,
zero review-required licenses and zero missing evidence files.

## 5. Bundle Evidence

The same Vite configuration builds two production entries:

- baseline: React 19, React DOM, Lucide and shared CSS;
- candidate: the same baseline plus the chart/layout prototype.

`docs/verification/bundle-m3.json` records raw, gzip and brotli sizes from the
Vite manifest on Node 24/npm 11.18:

| Initial closure | Raw bytes | Gzip bytes | Brotli bytes |
|---|---:|---:|---:|
| Baseline | 202,696 | 62,943 | 54,263 |
| Candidate | 286,895 | 87,234 | 75,502 |
| Increment | 84,199 | 24,291 | 21,239 |

The candidate initial groups are only `application` and
`react-grid-layout`. ECharts is loaded by `React.lazy`, producing separate
`EChart` and `echarts` dynamic chunks. The ECharts chunk remains 552,727 bytes
raw / 185,442 bytes level-9 gzip / 156,652 bytes brotli in the structured
evidence and still triggers Vite's 500 kB warning, but it is not in the initial
closure. Vite's console displays 187.47 kB gzip using its reporting compressor;
exact comparisons use `bundle-m3.json` only.

Decision: `echarts_initial_load=deferred`. Production integration must preserve
the dynamic chart boundary and rerun the same evidence; suppressing the warning
or making ECharts initial is not allowed.

The build summary is in `docs/verification/m3-r0-frontend-build.log`; exact
commands are in `docs/verification/m3-r0-commands.log`.

## 6. Browser Evidence

`docs/verification/m3-r0-browser-evidence.json` binds each run to the base Git
SHA, package-lock SHA, session, user agent, duration, viewport and screenshot
hash. `m3-r0-canvas-pixels.json` and `m3-r0-console.json` contain the Canvas and
console results.

| Browser | Viewport | Items | Overlaps | Horizontal overflow | Canvas | Console |
|---|---:|---:|---:|---:|---|---|
| Chrome 149 | 1440 x 900 | 7 | 0 | 0 | 3 varied/nontransparent | 0 errors, 0 warnings |
| Chrome 149 | 390 x 844 | 7 | 0 | 0 | 3 varied/nontransparent | 0 errors, 0 warnings |
| Edge 150 | 1440 x 900 | 7 | 0 | 0 | 3 varied/nontransparent | 0 errors, 0 warnings |
| Edge 150 | 390 x 844 | 7 | 0 | 0 | 3 varied/nontransparent | 0 errors, 0 warnings |

Post-lazy desktop/mobile measurement completes in 1,724 ms on Chrome and 1,483
ms on Edge on this machine. These are spike readiness timings, not the M3
production performance benchmark.

Additional runtime proof:

- a line point returns the sold-on field UUID and canonical `2026-01` filter;
- React Grid Layout moves a KPI and snapshot reload restores it;
- GridStack lazily mounts three items and a real pointer drag changes position;
- mobile filter disclosure expands, while visible edit controls, form controls
  and drag glyphs remain zero;
- a rendered 578 x 181 Canvas exports a nontransparent/nonuniform 1156 x 362
  PNG at pixel ratio 2; the PNG and structured dimensions/hash/pixel record are
  `docs/verification/export-2x-bar-chrome.png` and `m3-r0-export-2x.json`.

Screenshots:

- `docs/verification/m3-r0-chart-layout-desktop.png`
- `docs/verification/m3-r0-chart-layout-mobile.png`
- `docs/verification/m3-r0-chart-layout-edge-desktop.png`
- `docs/verification/m3-r0-chart-layout-edge-mobile.png`

Chrome/Edge mobile PNGs are byte-identical, as are the stress-50 PNGs. This is
disclosed rather than used as proof of browser identity; independent user
agents, sessions, durations and desktop hashes establish separate channel runs.

## 7. Stress Evidence

The URL allowlist `?stress=1|20|50` renders deterministic lightweight widgets
through the same React Grid Layout editor. Invalid or absent values retain the
normal seven-widget dashboard. Unit tests cover count, unique IDs, 12-column
bounds and every pairwise overlap.

Both Chrome 149 and Edge 150 passed all three densities:

| Components | Unique IDs | Initial overlaps | Post-resize overlaps | Real resize changed width |
|---:|---:|---:|---:|---|
| 1 | 1 | 0 | 0 | Yes |
| 20 | 20 | 0 | 0 | Yes |
| 50 | 50 | 0 | 0 | Yes |

Both 50-item runs fit the 1440 px document width. Screenshots are
`m3-r0-chart-layout-chrome-stress-50.png` and
`m3-r0-chart-layout-edge-stress-50.png` under `docs/verification/`.

## 8. Verification

Final Node 24 spike results:

```text
npm test
3 files, 15 tests passed

npm run build:baseline
1774 modules; passed

npm run build
2404 modules; passed; ECharts warning is lazy-only

npm run evidence
19 license rows; bundle decision deferred
```

The spike does not claim production API, permissions, persistence or complete
keyboard editing. Those remain milestone work behind the frozen contracts and
the dependency/dynamic-loading constraints above.

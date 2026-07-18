import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChartLoadingFallback } from "./App";

describe("ECharts bundle boundary", () => {
  it("renders a fixed chart-shell fallback with an accessible status", () => {
    const markup = renderToStaticMarkup(<ChartLoadingFallback componentId="bar" title="区域营收与目标" />);
    expect(markup).toContain('class="widget chart-widget"');
    expect(markup).toContain('class="chart-load-fallback"');
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-label="正在载入区域营收与目标"');
  });
});

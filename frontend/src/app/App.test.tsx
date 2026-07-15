import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../test/TestProviders";
import { App } from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lazy loads the dataset route from the application navigation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          { status: 200 },
        ),
    ),
  );

  render(
    <TestProviders initialEntries={["/datasets"]}>
      <App />
    </TestProviders>,
  );

  expect(
    await screen.findByRole("heading", { name: "数据集" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "数据集" })).toHaveAttribute(
    "href",
    "/datasets",
  );
});

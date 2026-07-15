import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { SystemStatusPage } from "./SystemStatusPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders the backend readiness state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ready", database: "ok" }), {
        status: 200,
      }),
    ),
  );

  render(
    <TestProviders>
      <SystemStatusPage />
    </TestProviders>,
  );

  expect(await screen.findByText("系统运行正常")).toBeInTheDocument();
  expect(screen.getByText("ready")).toBeInTheDocument();
  expect(screen.getByText("ok")).toBeInTheDocument();
});

it("renders an error when the readiness request fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

  render(
    <TestProviders>
      <SystemStatusPage />
    </TestProviders>,
  );

  expect(await screen.findByText("系统连接异常")).toBeInTheDocument();
});

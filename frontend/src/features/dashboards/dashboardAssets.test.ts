import { afterEach, expect, it, vi } from "vitest";

import {
  dashboardAssetContentUrl,
  listDashboardAssets,
  uploadDashboardAsset,
} from "./dashboardAssets";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lists, uploads and resolves governed dashboard assets", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(
        JSON.stringify(
          init?.method === "POST"
            ? {
                id: "asset-2",
                filename: "new.png",
                content_type: "image/png",
                size_bytes: 12,
                created_at: "2026-07-19T00:00:00Z",
              }
            : { items: [], total: 0, offset: 0, limit: 100 },
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );

  await listDashboardAssets();
  await uploadDashboardAsset(
    new File([new Uint8Array([1, 2, 3])], "new.png", {
      type: "image/png",
    }),
  );

  expect(calls[0].url).toMatch(/\/dashboard-assets\?offset=0&limit=100$/);
  expect(calls[1]).toMatchObject({
    url: expect.stringMatching(/\/dashboard-assets$/),
    init: { method: "POST" },
  });
  const uploadBody = calls[1].init?.body;
  expect(uploadBody).toBeInstanceOf(FormData);
  if (!(uploadBody instanceof FormData))
    throw new Error("Expected multipart form data");
  expect(uploadBody.get("file")).toBeInstanceOf(File);
  expect(dashboardAssetContentUrl("asset-2")).toMatch(
    /\/dashboard-assets\/asset-2\/content$/,
  );
});

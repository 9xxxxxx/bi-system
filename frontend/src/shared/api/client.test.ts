import { afterEach, expect, it, vi } from "vitest";

import { requestJson } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("includes browser credentials without storing a token", async () => {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await requestJson<{ status: string }>("/auth/me");

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringMatching(/\/auth\/me$/),
    expect.objectContaining({ credentials: "include" }),
  );
  expect(window.localStorage).toHaveLength(0);
  expect(window.sessionStorage).toHaveLength(0);
});

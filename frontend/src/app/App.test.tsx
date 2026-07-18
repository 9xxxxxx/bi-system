import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import type { PropsWithChildren } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TestProviders } from "../test/TestProviders";
import { App } from "./App";

const currentUser = {
  id: "a3ea0dbf-6415-40de-952d-2692a5f77955",
  workspace_id: "642b1526-21bf-46ef-9dd4-81e40582b1b4",
  username: "analyst",
  display_name: "数据分析员",
  must_change_password: false,
  role_ids: [],
  permissions: ["datasets:read"],
  is_system_admin: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

it("restores the session and lazy loads the dataset route", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const pathname = new URL(url).pathname;
      if (url.endsWith("/auth/me")) {
        return new Response(JSON.stringify(currentUser), { status: 200 });
      }
      if (pathname.endsWith("/datasets")) {
        return new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: "Not found" }), {
        status: 404,
      });
    }),
  );

  render(
    <TestProviders initialEntries={["/datasets"]}>
      <App />
    </TestProviders>,
  );

  expect(
    await screen.findByRole("heading", { name: "数据集" }, { timeout: 5_000 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "数据集" })).toHaveAttribute(
    "href",
    "/datasets",
  );
  expect(screen.getByText("数据分析员")).toBeInTheDocument();
});

it("lazy loads the dashboard list from the primary navigation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) {
        return new Response(JSON.stringify(currentUser), { status: 200 });
      }
      if (new URL(url).pathname.endsWith("/dashboards")) {
        return new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          { status: 200 },
        );
      }
      return apiError(404, "not_found", "Not found");
    }),
  );

  render(
    <TestProviders initialEntries={["/dashboards"]}>
      <App />
    </TestProviders>,
  );

  expect(
    await screen.findByRole("heading", { name: "仪表盘" }, { timeout: 5_000 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "仪表盘" })).toHaveAttribute(
    "href",
    "/dashboards",
  );
});

describe("authentication", () => {
  it("shows login after an unauthorized session check and enters the app", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/me")) {
          return apiError(401, "authentication_required", "需要登录");
        }
        if (url.endsWith("/auth/login") && init?.method === "POST") {
          return new Response(JSON.stringify(currentUser), { status: 200 });
        }
        if (url.endsWith("/health/ready")) {
          return new Response(
            JSON.stringify({ status: "ready", database: "sqlite" }),
            { status: 200 },
          );
        }
        return apiError(404, "not_found", "Not found");
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <TestProviders initialEntries={["/system-status"]}>
        <App />
      </TestProviders>,
    );

    expect(
      await screen.findByRole("heading", { name: "登录 BI System" }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("用户名"), " analyst ");
    await user.type(screen.getByLabelText("密码"), "secret-password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("数据分析员")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "登录 BI System" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/login$/),
      expect.objectContaining({
        body: JSON.stringify({
          username: "analyst",
          password: "secret-password",
        }),
        method: "POST",
      }),
    );
  });

  it("clears cached data after logout and returns to login", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["sensitive-dashboard"], { value: "cached" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/auth/me")) {
          return new Response(JSON.stringify(currentUser), { status: 200 });
        }
        if (url.endsWith("/auth/logout") && init?.method === "POST") {
          return new Response(null, { status: 204 });
        }
        if (url.endsWith("/health/ready")) {
          return new Response(
            JSON.stringify({ status: "ready", database: "sqlite" }),
            { status: 200 },
          );
        }
        return apiError(404, "not_found", "Not found");
      }),
    );
    const user = userEvent.setup();

    render(
      <AuthTestProviders queryClient={queryClient}>
        <App />
      </AuthTestProviders>,
    );

    expect(await screen.findByText("数据分析员")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(
      await screen.findByRole("heading", { name: "登录 BI System" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(queryClient.getQueryData(["sensitive-dashboard"])).toBeUndefined();
    });
  });
});

function AuthTestProviders({
  children,
  queryClient,
}: PropsWithChildren<{ queryClient: QueryClient }>) {
  return (
    <ConfigProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/system-status"]}>
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    </ConfigProvider>
  );
}

function apiError(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ detail: { code, message } }), {
    status,
  });
}

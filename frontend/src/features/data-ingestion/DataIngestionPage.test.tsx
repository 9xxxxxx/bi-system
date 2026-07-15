import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { DataIngestionPage } from "./DataIngestionPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("uploads a CSV and renders the bounded preview", async () => {
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/import-templates")) {
        return new Response("[]", { status: 200 });
      }
      if (url.includes("/import-batches?")) {
        return new Response("[]", { status: 200 });
      }
      if (url.endsWith("/source-files") && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        return new Response(
          JSON.stringify({
            id: "source-1",
            original_name: "sales.csv",
            file_kind: "csv",
            status: "ready",
            size_bytes: 24,
            sha256: "abc",
            media_type: "text/csv",
            created_at: "2026-07-15T00:00:00Z",
            duplicate: false,
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/source-files/source-1/preview")) {
        return new Response(
          JSON.stringify({
            source_file_id: "source-1",
            file_kind: "csv",
            sheet_names: [],
            selected_sheet: null,
            columns: [
              {
                key: "column_1",
                source_name: "amount",
                inferred_type: "decimal",
                null_count: 0,
              },
            ],
            rows: [{ column_1: 120.5 }],
            truncated: false,
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(
    <TestProviders>
      <DataIngestionPage />
    </TestProviders>,
  );

  const file = new File(["amount\n120.5\n"], "sales.csv", {
    type: "text/csv",
  });
  await user.upload(document.querySelector("input[type=file]")!, file);
  await user.click(screen.getByRole("button", { name: /上传并预览/ }));

  expect(await screen.findByText("检查文件内容")).toBeInTheDocument();
  expect(screen.getByText("120.5")).toBeInTheDocument();
  expect(screen.getByText("1 个字段")).toBeInTheDocument();
});

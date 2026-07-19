import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { useState } from "react";

import type { ScopedFilter } from "../charts/types";
import { FilterEditor } from "./FilterEditor";

function Harness() {
  const [value, setValue] = useState<ScopedFilter | null>(null);
  return (
    <>
      <FilterEditor
        label="全局筛选"
        value={value}
        fieldOptions={[
          {
            value: "field-date",
            label: "订单日期",
            role: "dimension",
            dataType: "date",
          },
        ]}
        onChange={setValue}
      />
      <output>{JSON.stringify(value)}</output>
    </>
  );
}

it("builds the exact relative and absolute date filter contracts", () => {
  render(<Harness />);

  fireEvent.click(screen.getByText("相对日期"));
  fireEvent.mouseDown(screen.getByLabelText("全局筛选字段"));
  fireEvent.click(screen.getByText("订单日期"));
  expect(screen.getByRole("status")).toHaveTextContent(
    '"kind":"relative_date"',
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    '"period":"last_30_days"',
  );

  fireEvent.click(screen.getByText("绝对日期"));
  expect(screen.getByRole("status")).toHaveTextContent(
    '"kind":"absolute_date_range"',
  );
  expect(screen.getByRole("status")).toHaveTextContent('"start":"2026-01-01"');
});

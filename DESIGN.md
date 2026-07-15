# BI System Design

## Role

This file is the design source of truth for the BI reporting and bulletin editing system. It guides React and Ant Design implementation; it is not a runtime dependency.

## Product Principles

- Build dense operational screens for repeated analysis work.
- Prefer clear hierarchy, compact spacing, and predictable navigation over decorative layouts.
- Keep chart, table, and editor surfaces calm so business data stays primary.
- Use Ant Design components first; introduce custom components only when the BI workflow requires it.

## Tokens

```yaml
color:
  background: "#f5f7fb"
  surface: "#ffffff"
  sidebar: "#111827"
  text: "#1f2937"
  textSecondary: "#6b7280"
  border: "#e5e7eb"
  primary: "#1677ff"
  success: "#52c41a"
  error: "#ff4d4f"

radius:
  control: 6
  panel: 8

spacing:
  pagePadding: 32
  pagePaddingMobile: 20
  panelPadding: 24
  panelPaddingMobile: 18
  gridGap: 24
```

## Ant Design Mapping

- `primary` maps to `ConfigProvider.theme.token.colorPrimary`.
- `radius.control` maps to `ConfigProvider.theme.token.borderRadius`.
- Page shells use `background`, panels use `surface`, and framed work areas use `border`.
- Cards are for repeated items or framed tools only; do not nest cards inside cards.

## Layout

The first screen should be the working application, not a marketing page. Use a left navigation rail for system-level modules and a constrained content width for forms, settings, and status pages. BI canvases and report editors may expand to full available width.

## Component Rules

- Use Ant Design for navigation, forms, alerts, tables where sufficient, modals, menus, and feedback.
- Use icon buttons for tool actions when the action has a standard symbol.
- Use compact tables and panels for data-heavy workflows.
- Do not introduce Astryx or design.md tooling as production dependencies without a separate evaluation.

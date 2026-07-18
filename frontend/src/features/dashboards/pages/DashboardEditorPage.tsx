import {
  ArrowLeftOutlined,
  CheckOutlined,
  LockOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getDashboard, saveDashboardVersion } from "../api";
import { ComponentPalette } from "../components/ComponentPalette";
import { DashboardCanvas } from "../components/DashboardCanvas";
import {
  DashboardErrorState,
  DashboardLoadingState,
} from "../components/DashboardQueryState";
import { PropertyInspector } from "../components/PropertyInspector";
import {
  componentTypeLabels,
  dashboardErrorDescription,
} from "../presentation";
import { dashboardQueryKeys } from "../queryKeys";
import type {
  DashboardComponent,
  DashboardComponentType,
  DashboardDetail,
  DashboardLayoutProfile,
  DashboardPage,
} from "../types";
import "../dashboards.css";

const mobileQuery = "(max-width: 768px)";

function useMobileViewport(): boolean {
  const [mobile, setMobile] = useState(
    () => window.matchMedia(mobileQuery).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(mobileQuery);
    const update = () => setMobile(media.matches);
    media.addEventListener("change", update);
    update();
    return () => media.removeEventListener("change", update);
  }, []);
  return mobile;
}

function clonePages(pages: DashboardPage[]): DashboardPage[] {
  if (pages.length === 0) {
    return [
      {
        id: crypto.randomUUID(),
        title: "页面 1",
        ordinal: 0,
        components: [],
      },
    ];
  }
  return pages.map((page) => ({
    ...page,
    components: page.components.map((component) => ({
      ...component,
      config: { ...component.config },
    })),
  }));
}

function cloneLayouts(
  layouts: DashboardLayoutProfile[],
): DashboardLayoutProfile[] {
  const cloned = layouts.map((layout) => ({
    ...layout,
    items: layout.items.map((item) => ({ ...item })),
  }));
  for (const profile of ["desktop", "mobile"] as const) {
    if (!cloned.some((layout) => layout.profile === profile)) {
      cloned.push({
        schema_version: 1,
        profile,
        columns: profile === "desktop" ? 12 : 4,
        row_height: 44,
        items: [],
      });
    }
  }
  return cloned;
}

function appendLayoutItem(
  layouts: DashboardLayoutProfile[],
  componentId: string,
): DashboardLayoutProfile[] {
  return layouts.map((layout) => {
    const y = layout.items.reduce(
      (bottom, item) => Math.max(bottom, item.y + item.height),
      0,
    );
    const width = layout.profile === "desktop" ? 4 : layout.columns;
    return {
      ...layout,
      items: [
        ...layout.items,
        {
          component_id: componentId,
          x: 0,
          y,
          width,
          height: 4,
          min_width: Math.min(2, width),
          min_height: 3,
        },
      ],
    };
  });
}

function EditorWorkspace({ dashboard }: { dashboard: DashboardDetail }) {
  const mobile = useMobileViewport();
  const canEdit = dashboard.capabilities.includes("edit");
  const readonly = mobile || !canEdit;
  const [pages, setPages] = useState(() => clonePages(dashboard.pages));
  const [layouts, setLayouts] = useState(() => cloneLayouts(dashboard.layouts));
  const [selectedPageId, setSelectedPageId] = useState(() => pages[0].id);
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(
    () => pages[0].components[0]?.id ?? null,
  );
  const [versionContext, setVersionContext] = useState(() => ({
    version: dashboard.current_version,
    revision: dashboard.revision,
  }));
  const [saveState, setSaveState] = useState("当前为已保存版本");
  const currentPage =
    pages.find((page) => page.id === selectedPageId) ?? pages[0];
  const selectedComponent =
    currentPage.components.find(
      (component) => component.id === selectedComponentId,
    ) ?? null;
  const activeProfile = mobile ? "mobile" : "desktop";
  const activeLayout = layouts.find(
    (layout) => layout.profile === activeProfile,
  )!;
  const saveMutation = useMutation({
    mutationFn: () =>
      saveDashboardVersion(dashboard.id, {
        base_version: versionContext.version,
        expected_revision: versionContext.revision,
        pages,
        layouts,
      }),
    onSuccess: (saved) => {
      setPages(clonePages(saved.pages));
      setLayouts(cloneLayouts(saved.layouts));
      setVersionContext({
        version: saved.current_version,
        revision: saved.revision,
      });
      setSaveState(`已保存 v${saved.current_version}`);
    },
  });

  function markChanged() {
    setSaveState("有未保存更改");
  }

  function addComponent(componentType: DashboardComponentType) {
    const component: DashboardComponent = {
      id: crypto.randomUUID(),
      component_type: componentType,
      title: componentTypeLabels[componentType],
      description: null,
      ordinal: currentPage.components.length,
      config: { schema_version: 1, state: "placeholder" },
    };
    setPages((current) =>
      current.map((page) =>
        page.id === currentPage.id
          ? { ...page, components: [...page.components, component] }
          : page,
      ),
    );
    setLayouts((current) => appendLayoutItem(current, component.id));
    setSelectedComponentId(component.id);
    markChanged();
  }

  function updateComponent(nextComponent: DashboardComponent) {
    setPages((current) =>
      current.map((page) =>
        page.id === currentPage.id
          ? {
              ...page,
              components: page.components.map((component) =>
                component.id === nextComponent.id ? nextComponent : component,
              ),
            }
          : page,
      ),
    );
    markChanged();
  }

  return (
    <section
      className="dashboard-editor"
      aria-labelledby="dashboard-editor-title"
    >
      <header className="dashboard-editor-header">
        <div>
          <Link to="/dashboards" className="dashboard-back-link">
            <ArrowLeftOutlined /> 仪表盘
          </Link>
          <Typography.Title id="dashboard-editor-title" level={2}>
            {dashboard.name}
          </Typography.Title>
          <Typography.Text type="secondary">
            {dashboard.description || "仪表盘编辑工作台"}
          </Typography.Text>
        </div>
        <Space wrap>
          <Tag color={dashboard.status === "active" ? "success" : "default"}>
            {dashboard.status === "active" ? "已发布" : "草稿"}
          </Tag>
          <span className="dashboard-save-state">{saveState}</span>
          {readonly ? (
            <Tag icon={<LockOutlined />}>只读</Tag>
          ) : (
            <Button
              type="primary"
              icon={
                saveMutation.isSuccess ? <CheckOutlined /> : <SaveOutlined />
              }
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              保存新版本
            </Button>
          )}
        </Space>
      </header>
      {mobile ? (
        <Alert
          className="dashboard-mobile-readonly"
          type="info"
          showIcon
          title="移动端为只读模式"
          description="当前展示独立移动布局；请在桌面端编辑组件和属性。"
        />
      ) : !canEdit ? (
        <Alert
          type="info"
          showIcon
          title="当前仪表盘为只读"
          description="你拥有查看权限，但没有编辑权限。"
        />
      ) : null}
      {saveMutation.isError ? (
        <Alert
          type="error"
          showIcon
          title="仪表盘保存失败"
          description={dashboardErrorDescription(saveMutation.error)}
        />
      ) : null}
      <nav className="dashboard-page-tabs" aria-label="仪表盘页面">
        {pages.map((page) => (
          <button
            key={page.id}
            type="button"
            className={`dashboard-page-tab${page.id === currentPage.id ? " is-active" : ""}`}
            aria-current={page.id === currentPage.id ? "page" : undefined}
            onClick={() => {
              setSelectedPageId(page.id);
              setSelectedComponentId(page.components[0]?.id ?? null);
            }}
          >
            {page.title}
          </button>
        ))}
      </nav>
      <div className={`dashboard-editor-grid${readonly ? " is-readonly" : ""}`}>
        {readonly ? null : <ComponentPalette onAdd={addComponent} />}
        <DashboardCanvas
          components={currentPage.components}
          layout={activeLayout}
          selectedComponentId={selectedComponentId}
          readonly={readonly}
          onSelect={setSelectedComponentId}
        />
        {readonly ? null : (
          <PropertyInspector
            component={selectedComponent}
            onChange={updateComponent}
          />
        )}
      </div>
    </section>
  );
}

export function DashboardEditorPage() {
  const { dashboardId } = useParams();
  const dashboardQuery = useQuery({
    queryKey: dashboardQueryKeys.detail(dashboardId ?? "missing"),
    queryFn: () => getDashboard(dashboardId!),
    enabled: Boolean(dashboardId),
  });
  if (dashboardQuery.isLoading || !dashboardId) {
    return <DashboardLoadingState label="正在加载仪表盘编辑器" />;
  }
  if (dashboardQuery.isError) {
    return (
      <DashboardErrorState
        error={dashboardQuery.error}
        onRetry={() => void dashboardQuery.refetch()}
      />
    );
  }
  if (!dashboardQuery.data) {
    return <DashboardLoadingState label="正在加载仪表盘编辑器" />;
  }
  return (
    <EditorWorkspace
      key={`${dashboardQuery.data.id}:${dashboardQuery.data.revision}`}
      dashboard={dashboardQuery.data}
    />
  );
}

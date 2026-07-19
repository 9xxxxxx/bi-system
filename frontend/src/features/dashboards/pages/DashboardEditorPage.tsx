import {
  ArrowLeftOutlined,
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  LeftOutlined,
  LockOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  RocketOutlined,
  SaveOutlined,
  SnippetsOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  Modal,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  activateDashboard,
  createDashboardTemplate,
  getDashboard,
  publishDashboardTemplate,
  saveDashboardVersion,
} from "../api";
import { ComponentPalette } from "../components/ComponentPalette";
import { DashboardCanvas } from "../components/DashboardCanvas";
import { DashboardFilterBar } from "../components/DashboardFilterBar";
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
  DashboardLayoutItem,
  DashboardLayoutProfile,
  DashboardLayoutProfileName,
  DashboardPage,
  DashboardTemplateDetail,
} from "../types";
import { isChartComponentConfig } from "../charts/config";
import type { ScopedFilter } from "../charts/types";
import "../dashboards.css";

const mobileQuery = "(max-width: 768px)";

interface ComponentClipboard {
  component: DashboardComponent;
  layoutItems: Partial<Record<DashboardLayoutProfileName, DashboardLayoutItem>>;
}

type PageNameMode = "add" | "rename";

interface PreviewFilterOverrides {
  globalFilter?: ScopedFilter | null;
  pageFilters: Record<string, ScopedFilter | null>;
  componentFilters: Record<string, ScopedFilter | null>;
}

const editorStatusPresentation: Record<
  DashboardDetail["status"],
  { color: string; label: string }
> = {
  draft: { color: "default", label: "草稿" },
  active: { color: "success", label: "已发布" },
  archived: { color: "warning", label: "已归档" },
  deleted: { color: "error", label: "回收站" },
};

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

function normalizePages(pages: DashboardPage[]): DashboardPage[] {
  return pages.map((page, ordinal) => ({
    ...page,
    ordinal,
    components: page.components.map((component, componentOrdinal) => ({
      ...component,
      ordinal: componentOrdinal,
    })),
  }));
}

function removePageLayoutItems(
  layouts: DashboardLayoutProfile[],
  componentIds: string[],
): DashboardLayoutProfile[] {
  const removedIds = new Set(componentIds);
  return layouts.map((layout) => ({
    ...layout,
    items: layout.items.filter((item) => !removedIds.has(item.component_id)),
  }));
}

function appendLayoutItem(
  layouts: DashboardLayoutProfile[],
  componentId: string,
  pageComponentIds: string[],
): DashboardLayoutProfile[] {
  const pageIds = new Set(pageComponentIds);
  return layouts.map((layout) => {
    const y = layout.items.reduce(
      (bottom, item) =>
        pageIds.has(item.component_id)
          ? Math.max(bottom, item.y + item.height)
          : bottom,
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

function replacePageLayoutItems(
  layouts: DashboardLayoutProfile[],
  profile: DashboardLayoutProfileName,
  pageComponentIds: string[],
  nextItems: DashboardLayoutItem[],
): DashboardLayoutProfile[] {
  const pageIds = new Set(pageComponentIds);
  return layouts.map((layout) =>
    layout.profile === profile
      ? {
          ...layout,
          items: [
            ...layout.items.filter((item) => !pageIds.has(item.component_id)),
            ...nextItems,
          ].toSorted((left, right) =>
            left.component_id.localeCompare(right.component_id),
          ),
        }
      : layout,
  );
}

function appendCopiedLayoutItems(
  layouts: DashboardLayoutProfile[],
  clipboard: ComponentClipboard,
  componentId: string,
  pageComponentIds: string[],
): DashboardLayoutProfile[] {
  const pageIds = new Set(pageComponentIds);
  return layouts.map((layout) => {
    const source = clipboard.layoutItems[layout.profile];
    const width = Math.min(
      layout.columns,
      source?.width ?? (layout.profile === "desktop" ? 4 : layout.columns),
    );
    const y = layout.items.reduce(
      (bottom, item) =>
        pageIds.has(item.component_id)
          ? Math.max(bottom, item.y + item.height)
          : bottom,
      0,
    );
    return {
      ...layout,
      items: [
        ...layout.items,
        {
          component_id: componentId,
          x: 0,
          y,
          width,
          height: source?.height ?? 4,
          min_width: Math.min(source?.min_width ?? 2, width),
          min_height: source?.min_height ?? 3,
        },
      ].toSorted((left, right) =>
        left.component_id.localeCompare(right.component_id),
      ),
    };
  });
}

function EditorWorkspace({ dashboard }: { dashboard: DashboardDetail }) {
  const queryClient = useQueryClient();
  const acceptedDashboard = useRef(dashboard);
  const mobile = useMobileViewport();
  const canEdit = dashboard.capabilities.includes("edit");
  const readonly = mobile || !canEdit;
  const [pages, setPages] = useState(() => clonePages(dashboard.pages));
  const [layouts, setLayouts] = useState(() => cloneLayouts(dashboard.layouts));
  const [globalFilter, setGlobalFilter] = useState<Record<
    string,
    unknown
  > | null>(() => dashboard.global_filter ?? null);
  const [previewFilters, setPreviewFilters] = useState<PreviewFilterOverrides>({
    pageFilters: {},
    componentFilters: {},
  });
  const [selectedPageId, setSelectedPageId] = useState(() => pages[0].id);
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(
    () => pages[0].components[0]?.id ?? null,
  );
  const [clipboard, setClipboard] = useState<ComponentClipboard | null>(null);
  const [pageNameMode, setPageNameMode] = useState<PageNameMode | null>(null);
  const [pageNameDraft, setPageNameDraft] = useState("");
  const [reloadConfirmOpen, setReloadConfirmOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState(`${dashboard.name} 模板`);
  const [templateDraft, setTemplateDraft] =
    useState<DashboardTemplateDetail | null>(null);
  const [operationStatus, setOperationStatus] = useState<string | null>(null);
  const [lifecycleStatus, setLifecycleStatus] = useState(dashboard.status);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [versionContext, setVersionContext] = useState(() => ({
    id: dashboard.current_version_id,
    version: dashboard.current_version,
    revision: dashboard.revision,
  }));
  const [saveState, setSaveState] = useState("当前为已保存版本");
  const currentPage =
    pages.find((page) => page.id === selectedPageId) ?? pages[0];
  const currentPageIndex = pages.findIndex(
    (page) => page.id === currentPage.id,
  );
  const selectedComponent =
    currentPage.components.find(
      (component) => component.id === selectedComponentId,
    ) ?? null;
  const effectiveGlobalFilter =
    readonly &&
    Object.prototype.hasOwnProperty.call(previewFilters, "globalFilter")
      ? (previewFilters.globalFilter ?? null)
      : (globalFilter as ScopedFilter | null);
  const effectivePageFilter =
    readonly &&
    Object.prototype.hasOwnProperty.call(
      previewFilters.pageFilters,
      currentPage.id,
    )
      ? previewFilters.pageFilters[currentPage.id]
      : ((currentPage.page_filter ?? null) as ScopedFilter | null);
  const effectiveComponents = readonly
    ? currentPage.components.map((component) => {
        if (
          !isChartComponentConfig(component.config) ||
          !Object.prototype.hasOwnProperty.call(
            previewFilters.componentFilters,
            component.id,
          )
        ) {
          return component;
        }
        return {
          ...component,
          config: {
            ...component.config,
            component_filter:
              previewFilters.componentFilters[component.id] ?? null,
          },
        };
      })
    : currentPage.components;
  const effectiveSelectedComponent =
    effectiveComponents.find(
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
        global_filter: globalFilter,
        pages,
        layouts,
      }),
    onSuccess: (saved) => {
      setPages(clonePages(saved.pages));
      setLayouts(cloneLayouts(saved.layouts));
      setGlobalFilter(saved.global_filter ?? null);
      setVersionContext({
        id: saved.current_version_id,
        version: saved.current_version,
        revision: saved.revision,
      });
      setLifecycleStatus(saved.status);
      setHasUnsavedChanges(false);
      setSaveState(`已保存 v${saved.current_version}`);
      acceptedDashboard.current = saved;
      queryClient.setQueryData(dashboardQueryKeys.detail(dashboard.id), saved);
      void queryClient.invalidateQueries({
        queryKey: dashboardQueryKeys.lists(),
      });
    },
  });
  const templateMutation = useMutation({
    mutationFn: async () => {
      const draft =
        templateDraft ??
        (await createDashboardTemplate({
          name: templateName.trim(),
          description: dashboard.description,
          source_dashboard_version_id: versionContext.id,
          visibility: "workspace",
        }));
      setTemplateDraft(draft);
      return publishDashboardTemplate(draft.id, draft.revision);
    },
    onSuccess: () => {
      setTemplateOpen(false);
      setTemplateDraft(null);
      setTemplateName(`${dashboard.name} 模板`);
      setOperationStatus("模板已发布");
      void queryClient.invalidateQueries({
        queryKey: dashboardQueryKeys.templateLists(),
      });
    },
  });
  const activateMutation = useMutation({
    mutationFn: () => activateDashboard(dashboard.id, versionContext.revision),
    onSuccess: (activated) => {
      setVersionContext({
        id: activated.current_version_id,
        version: activated.current_version,
        revision: activated.revision,
      });
      setLifecycleStatus(activated.status);
      setOperationStatus("仪表盘已激活");
      acceptedDashboard.current = activated;
      queryClient.setQueryData(
        dashboardQueryKeys.detail(dashboard.id),
        activated,
      );
      void queryClient.invalidateQueries({
        queryKey: dashboardQueryKeys.lists(),
      });
    },
  });
  const reloadMutation = useMutation({
    mutationFn: () => getDashboard(dashboard.id),
    onSuccess: (latest) => {
      const latestPages = clonePages(latest.pages);
      setPages(latestPages);
      setLayouts(cloneLayouts(latest.layouts));
      setGlobalFilter(latest.global_filter ?? null);
      setSelectedPageId(latestPages[0].id);
      setSelectedComponentId(latestPages[0].components[0]?.id ?? null);
      setVersionContext({
        id: latest.current_version_id,
        version: latest.current_version,
        revision: latest.revision,
      });
      setLifecycleStatus(latest.status);
      setPreviewFilters({ pageFilters: {}, componentFilters: {} });
      setHasUnsavedChanges(false);
      setSaveState("已重新加载最新版本");
      setReloadConfirmOpen(false);
      saveMutation.reset();
      acceptedDashboard.current = latest;
      queryClient.setQueryData(dashboardQueryKeys.detail(dashboard.id), latest);
    },
  });
  const saveConflict =
    saveMutation.error instanceof ApiError && saveMutation.error.status === 409;

  useEffect(() => {
    const accepted = acceptedDashboard.current;
    if (dashboard.revision < accepted.revision) {
      queryClient.setQueryData(
        dashboardQueryKeys.detail(dashboard.id),
        accepted,
      );
      return;
    }
    if (dashboard.revision === accepted.revision || hasUnsavedChanges) {
      return;
    }
    acceptedDashboard.current = dashboard;
    const latestPages = clonePages(dashboard.pages);
    setPages(latestPages);
    setLayouts(cloneLayouts(dashboard.layouts));
    setGlobalFilter(dashboard.global_filter ?? null);
    setSelectedPageId(latestPages[0].id);
    setSelectedComponentId(latestPages[0].components[0]?.id ?? null);
    setVersionContext({
      id: dashboard.current_version_id,
      version: dashboard.current_version,
      revision: dashboard.revision,
    });
    setLifecycleStatus(dashboard.status);
    setPreviewFilters({ pageFilters: {}, componentFilters: {} });
    setSaveState("已同步最新版本");
  }, [dashboard, hasUnsavedChanges, queryClient]);

  const copySelectedComponent = useCallback(() => {
    if (!selectedComponent) return;
    setClipboard({
      component: {
        ...selectedComponent,
        config: structuredClone(selectedComponent.config),
      },
      layoutItems: Object.fromEntries(
        layouts.flatMap((layout) => {
          const item = layout.items.find(
            (candidate) => candidate.component_id === selectedComponent.id,
          );
          return item ? [[layout.profile, { ...item }]] : [];
        }),
      ),
    });
  }, [layouts, selectedComponent]);

  const pasteComponent = useCallback(() => {
    if (!clipboard || readonly) return;
    const componentId = crypto.randomUUID();
    const component: DashboardComponent = {
      ...clipboard.component,
      id: componentId,
      title: `${clipboard.component.title} 副本`,
      ordinal: currentPage.components.length,
      config: structuredClone(clipboard.component.config),
    };
    setPages((current) =>
      current.map((page) =>
        page.id === currentPage.id
          ? { ...page, components: [...page.components, component] }
          : page,
      ),
    );
    setLayouts((current) =>
      appendCopiedLayoutItems(
        current,
        clipboard,
        componentId,
        currentPage.components.map((item) => item.id),
      ),
    );
    setSelectedComponentId(componentId);
    setHasUnsavedChanges(true);
    setSaveState("有未保存更改");
  }, [clipboard, currentPage.components, currentPage.id, readonly]);

  useEffect(() => {
    if (readonly) return;
    const handleClipboardShortcut = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        target.closest("input, textarea, select, [contenteditable='true']")
      )
        return;
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "c" && selectedComponent) {
        event.preventDefault();
        copySelectedComponent();
      }
      if (event.key.toLowerCase() === "v" && clipboard) {
        event.preventDefault();
        pasteComponent();
      }
    };
    document.addEventListener("keydown", handleClipboardShortcut);
    return () =>
      document.removeEventListener("keydown", handleClipboardShortcut);
  }, [
    clipboard,
    copySelectedComponent,
    pasteComponent,
    readonly,
    selectedComponent,
  ]);

  function markChanged() {
    if (canEdit) {
      setHasUnsavedChanges(true);
      setSaveState("有未保存更改");
    }
  }

  function openPageName(mode: PageNameMode) {
    setPageNameMode(mode);
    setPageNameDraft(
      mode === "add" ? `页面 ${pages.length + 1}` : currentPage.title,
    );
  }

  function commitPageName() {
    const title = pageNameDraft.trim();
    if (!title || pageNameMode === null) return;
    if (pageNameMode === "add") {
      const page: DashboardPage = {
        id: crypto.randomUUID(),
        title,
        ordinal: pages.length,
        page_filter: null,
        components: [],
      };
      setPages((current) => normalizePages([...current, page]));
      setSelectedPageId(page.id);
      setSelectedComponentId(null);
    } else {
      setPages((current) =>
        normalizePages(
          current.map((page) =>
            page.id === currentPage.id ? { ...page, title } : page,
          ),
        ),
      );
    }
    setPageNameMode(null);
    markChanged();
  }

  function moveCurrentPage(offset: -1 | 1) {
    const currentPageId = currentPage.id;
    setPages((current) => {
      const currentIndex = current.findIndex(
        (page) => page.id === currentPageId,
      );
      const nextIndex = currentIndex + offset;
      if (currentIndex < 0 || nextIndex < 0 || nextIndex >= current.length) {
        return current;
      }
      const reordered = [...current];
      [reordered[currentIndex], reordered[nextIndex]] = [
        reordered[nextIndex],
        reordered[currentIndex],
      ];
      return normalizePages(reordered);
    });
    markChanged();
  }

  function deleteCurrentPage() {
    if (pages.length <= 1) return;
    const currentIndex = pages.findIndex((page) => page.id === currentPage.id);
    const remainingPages = normalizePages(
      pages.filter((page) => page.id !== currentPage.id),
    );
    const selectedPage =
      remainingPages[Math.min(currentIndex, remainingPages.length - 1)];
    setPages(remainingPages);
    setLayouts((current) =>
      removePageLayoutItems(
        current,
        currentPage.components.map((component) => component.id),
      ),
    );
    setSelectedPageId(selectedPage.id);
    setSelectedComponentId(selectedPage.components[0]?.id ?? null);
    markChanged();
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
    setLayouts((current) =>
      appendLayoutItem(
        current,
        component.id,
        currentPage.components.map((item) => item.id),
      ),
    );
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

  function updatePageFilter(nextFilter: ScopedFilter | null) {
    if (readonly) {
      setPreviewFilters((current) => ({
        ...current,
        pageFilters: {
          ...current.pageFilters,
          [currentPage.id]: nextFilter,
        },
      }));
      return;
    }
    setPages((current) =>
      current.map((page) =>
        page.id === currentPage.id
          ? { ...page, page_filter: nextFilter }
          : page,
      ),
    );
    markChanged();
  }

  function updateComponentFilter(nextFilter: ScopedFilter | null) {
    if (!selectedComponent || !isChartComponentConfig(selectedComponent.config))
      return;
    if (readonly) {
      setPreviewFilters((current) => ({
        ...current,
        componentFilters: {
          ...current.componentFilters,
          [selectedComponent.id]: nextFilter,
        },
      }));
      return;
    }
    updateComponent({
      ...selectedComponent,
      config: { ...selectedComponent.config, component_filter: nextFilter },
    });
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
          <Tag color={editorStatusPresentation[lifecycleStatus].color}>
            {editorStatusPresentation[lifecycleStatus].label}
          </Tag>
          {operationStatus ? (
            <Tag color="success">{operationStatus}</Tag>
          ) : null}
          <span className="dashboard-save-state">{saveState}</span>
          {readonly ? (
            <Tag icon={<LockOutlined />}>只读</Tag>
          ) : (
            <>
              <Tooltip title="发布当前已保存版本为模板">
                <Button
                  icon={<FileAddOutlined />}
                  aria-label="发布当前已保存版本为模板"
                  onClick={() => {
                    templateMutation.reset();
                    if (!templateDraft) {
                      setTemplateName(`${dashboard.name} 模板`);
                    }
                    setTemplateOpen(true);
                  }}
                />
              </Tooltip>
              {lifecycleStatus === "active" ? null : (
                <Tooltip title="激活仪表盘">
                  <Button
                    icon={<RocketOutlined />}
                    aria-label="激活仪表盘"
                    loading={activateMutation.isPending}
                    disabled={hasUnsavedChanges}
                    onClick={() => activateMutation.mutate()}
                  />
                </Tooltip>
              )}
              <Tooltip title="复制当前组件 (Ctrl/Cmd+C)">
                <Button
                  icon={<CopyOutlined />}
                  aria-label="复制当前组件"
                  disabled={!selectedComponent}
                  onClick={copySelectedComponent}
                />
              </Tooltip>
              <Tooltip title="粘贴组件 (Ctrl/Cmd+V)">
                <Button
                  icon={<SnippetsOutlined />}
                  aria-label="粘贴组件"
                  disabled={!clipboard}
                  onClick={pasteComponent}
                />
              </Tooltip>
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
            </>
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
          className="dashboard-lifecycle-alert"
          type="error"
          showIcon
          title="仪表盘保存失败"
          description={dashboardErrorDescription(saveMutation.error)}
          action={
            saveConflict ? (
              <Button
                icon={<ReloadOutlined />}
                onClick={() => setReloadConfirmOpen(true)}
              >
                放弃本地更改并重新加载
              </Button>
            ) : undefined
          }
        />
      ) : null}
      {activateMutation.isError ? (
        <Alert
          className="dashboard-lifecycle-alert"
          type="error"
          showIcon
          title="仪表盘激活失败"
          description={dashboardErrorDescription(activateMutation.error)}
        />
      ) : null}
      {reloadMutation.isError ? (
        <Alert
          className="dashboard-lifecycle-alert"
          type="error"
          showIcon
          title="最新版本加载失败"
          description={dashboardErrorDescription(reloadMutation.error)}
        />
      ) : null}
      <DashboardFilterBar
        globalFilter={effectiveGlobalFilter}
        pageFilter={effectivePageFilter}
        componentFilter={
          effectiveSelectedComponent &&
          isChartComponentConfig(effectiveSelectedComponent.config)
            ? effectiveSelectedComponent.config.component_filter
            : null
        }
        datasetId={
          selectedComponent && isChartComponentConfig(selectedComponent.config)
            ? selectedComponent.config.query.dataset_id
            : ""
        }
        canPreview={dashboard.capabilities.includes("view")}
        onGlobalChange={(nextFilter) => {
          if (readonly) {
            setPreviewFilters((current) => ({
              ...current,
              globalFilter: nextFilter,
            }));
            return;
          }
          setGlobalFilter(nextFilter);
          markChanged();
        }}
        onPageChange={updatePageFilter}
        onComponentChange={updateComponentFilter}
      />
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
        {readonly ? null : (
          <Space.Compact>
            <Tooltip title="新增页面">
              <Button
                type="text"
                size="small"
                icon={<PlusOutlined />}
                aria-label="新增页面"
                onClick={() => openPageName("add")}
              />
            </Tooltip>
            <Tooltip title="重命名页面">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                aria-label="重命名页面"
                onClick={() => openPageName("rename")}
              />
            </Tooltip>
            <Tooltip title="页面左移">
              <Button
                type="text"
                size="small"
                icon={<LeftOutlined />}
                aria-label="页面左移"
                disabled={currentPageIndex <= 0}
                onClick={() => moveCurrentPage(-1)}
              />
            </Tooltip>
            <Tooltip title="页面右移">
              <Button
                type="text"
                size="small"
                icon={<RightOutlined />}
                aria-label="页面右移"
                disabled={currentPageIndex >= pages.length - 1}
                onClick={() => moveCurrentPage(1)}
              />
            </Tooltip>
            <Popconfirm
              title="删除当前页面？"
              description="页面内组件及其桌面、移动布局将同时删除。"
              okText="删除"
              cancelText="取消"
              disabled={pages.length <= 1}
              onConfirm={deleteCurrentPage}
            >
              <Tooltip title="删除页面">
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  aria-label="删除页面"
                  disabled={pages.length <= 1}
                />
              </Tooltip>
            </Popconfirm>
          </Space.Compact>
        )}
      </nav>
      <div className={`dashboard-editor-grid${readonly ? " is-readonly" : ""}`}>
        {readonly ? null : <ComponentPalette onAdd={addComponent} />}
        <DashboardCanvas
          dashboardId={dashboard.id}
          dashboardVersionId={versionContext.id}
          pageId={currentPage.id}
          components={effectiveComponents}
          globalFilter={effectiveGlobalFilter}
          pageFilter={effectivePageFilter}
          layout={activeLayout}
          selectedComponentId={selectedComponentId}
          readonly={readonly}
          preview={canEdit}
          onSelect={setSelectedComponentId}
          onLayoutChange={(nextItems) => {
            setLayouts((current) =>
              replacePageLayoutItems(
                current,
                activeProfile,
                currentPage.components.map((component) => component.id),
                nextItems,
              ),
            );
            markChanged();
          }}
        />
        {readonly ? null : (
          <PropertyInspector
            component={selectedComponent}
            onChange={updateComponent}
          />
        )}
      </div>
      <Modal
        open={pageNameMode !== null}
        title={pageNameMode === "add" ? "新增页面" : "重命名页面"}
        okText="确定"
        cancelText="取消"
        okButtonProps={{ disabled: !pageNameDraft.trim() }}
        onOk={commitPageName}
        onCancel={() => setPageNameMode(null)}
      >
        <Input
          autoFocus
          maxLength={128}
          value={pageNameDraft}
          aria-label="页面名称"
          onChange={(event) => setPageNameDraft(event.target.value)}
          onPressEnter={commitPageName}
        />
      </Modal>
      <Modal
        open={templateOpen}
        title="发布当前版本为模板"
        okText="发布"
        cancelText="取消"
        confirmLoading={templateMutation.isPending}
        okButtonProps={{ disabled: !templateName.trim() }}
        onOk={() => templateMutation.mutate()}
        onCancel={() => {
          if (!templateMutation.isPending) setTemplateOpen(false);
        }}
      >
        <Input
          autoFocus
          maxLength={128}
          value={templateName}
          aria-label="模板名称"
          onChange={(event) => setTemplateName(event.target.value)}
          onPressEnter={() => {
            if (templateName.trim()) templateMutation.mutate();
          }}
        />
        {templateMutation.isError ? (
          <Alert
            className="dashboard-template-publish-error"
            type="error"
            showIcon
            title="模板发布失败"
            description={dashboardErrorDescription(templateMutation.error)}
          />
        ) : null}
      </Modal>
      <Modal
        open={reloadConfirmOpen}
        title="放弃本地更改"
        okText="放弃并重新加载"
        cancelText="取消"
        confirmLoading={reloadMutation.isPending}
        okButtonProps={{ danger: true }}
        onOk={() => reloadMutation.mutate()}
        onCancel={() => {
          if (!reloadMutation.isPending) setReloadConfirmOpen(false);
        }}
      >
        <Typography.Text>
          本地未保存更改将被最新服务端版本替换。
        </Typography.Text>
      </Modal>
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
      key={dashboardQuery.data.id}
      dashboard={dashboardQuery.data}
    />
  );
}

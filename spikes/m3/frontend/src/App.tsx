import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { GridLayout as ReactGridLayout, useContainerWidth } from "react-grid-layout/react";
import type { Layout } from "react-grid-layout/core";
import { BarChart3, ChevronDown, GripVertical, Info, Moon, Redo2, Sun, Undo2, X } from "lucide-react";
import { desktopLayout, mobileOrder, regions, revenue, target } from "./data";
import { toggleReadonlyFilterPanel, type ChartInteraction, type DataState } from "./contracts";
import { cloneLayout, deserializeLayout, serializeLayout } from "./layout";
import { stressComponentIds, stressCountFromSearch, stressLayouts, type StressCount } from "./stress";

const GridStackCandidate = lazy(() => import("./GridStackCandidate"));
const EChart = lazy(() => import("./EChart").then((module) => ({ default: module.EChart })));
const dashboardIds = desktopLayout.map((item) => item.i);

function useMobileViewport() {
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 700px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 700px)");
    const update = () => setMobile(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return mobile;
}

interface WidgetProps {
  id: string;
  dark: boolean;
  state: DataState;
  onInteraction: (interaction: ChartInteraction) => void;
}

function Kpi({ id, label, value, delta }: { id: string; label: string; value: string; delta: string }) {
  return (
    <article className="widget kpi-widget" data-component-id={id}>
      <header className="widget-header drag-handle"><span>{label}</span><GripVertical size={16} aria-hidden="true" /></header>
      <div className="kpi-value">{value}</div>
      <div className="kpi-meta"><strong>{delta}</strong><span>较上期</span></div>
    </article>
  );
}

function RankingTable({ state }: { state: DataState }) {
  return (
    <article className="widget table-widget" data-component-id="table">
      <header className="widget-header drag-handle"><div><h2>区域完成度</h2><span>按目标达成率排序</span></div></header>
      <div className="table-scroll no-drag">
        {state !== "ready" ? <div className={`state-panel ${state === "error" ? "error-state" : ""}`}>{state === "loading" ? "正在加载明细" : state === "empty" ? "暂无明细" : "明细查询失败"}</div> : (
          <table>
            <thead><tr><th scope="col">区域</th><th scope="col">营收</th><th scope="col">目标</th><th scope="col">达成率</th></tr></thead>
            <tbody>{regions.map((region, index) => {
              const rate = Math.round((revenue[index] / target[index]) * 100);
              return <tr key={region}><th scope="row">{region}</th><td>{revenue[index]}</td><td>{target[index]}</td><td><span className={rate >= 100 ? "rate good" : "rate"}>{rate}%</span></td></tr>;
            })}</tbody>
          </table>
        )}
      </div>
    </article>
  );
}

export function ChartLoadingFallback({ componentId, title }: { componentId: string; title: string }) {
  return (
    <article className="widget chart-widget" data-component-id={componentId}>
      <header className="widget-header drag-handle"><div><h2>{title}</h2><span>金额：万元</span></div></header>
      <div className="chart-load-fallback" role="status" aria-label={`正在载入${title}`}><span className="spinner" aria-hidden="true" /><span>正在载入图表模块</span></div>
    </article>
  );
}

function LazyChart(props: Parameters<typeof EChart>[0]) {
  return <Suspense fallback={<ChartLoadingFallback componentId={props.componentId} title={props.title} />}><EChart {...props} /></Suspense>;
}

function Widget({ id, dark, state, onInteraction }: WidgetProps) {
  if (id === "kpi-revenue") return <Kpi id={id} label="总营收" value="754 万" delta="+12.4%" />;
  if (id === "kpi-margin") return <Kpi id={id} label="毛利率" value="36.8%" delta="+2.1pp" />;
  if (id === "kpi-orders") return <Kpi id={id} label="订单" value="1,284" delta="+8.7%" />;
  if (id === "bar") return <LazyChart componentId={id} title="区域营收与目标" kind="bar" dark={dark} state={state} onInteraction={onInteraction} />;
  if (id === "line") return <LazyChart componentId={id} title="月度增长趋势" kind="line" dark={dark} state={state} onInteraction={onInteraction} />;
  if (id === "donut") return <LazyChart componentId={id} title="区域营收占比" kind="donut" dark={dark} state={state} onInteraction={onInteraction} />;
  return <RankingTable state={state} />;
}

function StressWidget({ id, index }: { id: string; index: number }) {
  return (
    <article className="widget stress-widget" data-component-id={id}>
      <header className="widget-header drag-handle"><span>压力组件 {index + 1}</span><GripVertical size={16} aria-hidden="true" /></header>
      <div><strong>{String(index + 1).padStart(2, "0")}</strong><span>layout item</span></div>
    </article>
  );
}

interface DashboardGridProps extends Omit<WidgetProps, "id"> {
  stressCount: StressCount | null;
}

function DashboardGrid({ dark, state, onInteraction, stressCount }: DashboardGridProps) {
  const { width, containerRef, mounted } = useContainerWidth({ initialWidth: 1120 });
  const baseLayout = stressCount === null ? desktopLayout : stressLayouts[stressCount];
  const componentIds = stressCount === null ? dashboardIds : stressComponentIds[stressCount];
  const [layout, setLayout] = useState<Layout>(() => cloneLayout(baseLayout));
  const [snapshot, setSnapshot] = useState(() => serializeLayout(baseLayout));
  const [layoutStatus, setLayoutStatus] = useState(() => stressCount === null ? "初始布局已载入" : `压力视图 · ${stressCount} 组件`);
  const saveLayout = useCallback(() => {
    const serialized = serializeLayout(layout);
    setSnapshot(serialized);
    setLayoutStatus(`布局快照已保存 · ${new Blob([serialized]).size} B`);
  }, [layout]);
  const reloadLayout = useCallback(() => {
    setLayout(deserializeLayout(snapshot, componentIds));
    setLayoutStatus("布局快照已重载");
  }, [componentIds, snapshot]);
  return (
    <section className="desktop-grid" aria-label="可编辑仪表盘布局">
      <div className="layout-toolbar no-drag">
        <output aria-live="polite">{layoutStatus}</output>
        <div><button type="button" onClick={saveLayout}>保存布局快照</button><button type="button" onClick={reloadLayout}>重载布局</button></div>
      </div>
      <div ref={containerRef}>
        {mounted ? (
          <ReactGridLayout
            width={width}
            layout={layout}
            onLayoutChange={(nextLayout) => setLayout(cloneLayout(nextLayout))}
            gridConfig={{ cols: 12, rowHeight: 44, margin: [12, 12], containerPadding: [0, 0] }}
            dragConfig={{ enabled: true, handle: ".drag-handle", cancel: ".no-drag" }}
            resizeConfig={{ enabled: true, handles: ["se"] }}
          >
            {componentIds.map((id, index) => <div key={id}>{stressCount === null ? <Widget id={id} dark={dark} state={state} onInteraction={onInteraction} /> : <StressWidget id={id} index={index} />}</div>)}
          </ReactGridLayout>
        ) : <div className="state-panel">正在测量画布</div>}
      </div>
    </section>
  );
}

export function App() {
  const isMobile = useMobileViewport();
  const [stressCount] = useState(() => stressCountFromSearch(window.location.search));
  const [dark, setDark] = useState(false);
  const [state, setState] = useState<DataState>("ready");
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [interaction, setInteraction] = useState<ChartInteraction | null>(null);
  const onInteraction = useCallback((next: ChartInteraction) => setInteraction(next), []);

  return (
    <div className={dark ? "app theme-dark" : "app"}>
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><BarChart3 size={18} /></span><span>衡镜 BI</span><small>M3 技术验证</small></div>
        <div className="topbar-actions">
          <button className="icon-button desktop-only" type="button" aria-label="撤销" title="撤销"><Undo2 size={17} /></button>
          <button className="icon-button desktop-only" type="button" aria-label="重做" title="重做"><Redo2 size={17} /></button>
          <span className="save-status desktop-only">已保存 · 14:32</span>
          <button className="text-button desktop-only" type="button" onClick={() => setComparisonOpen(true)}><Info size={16} />候选对比</button>
          <button className="icon-button" type="button" onClick={() => setDark((value) => !value)} aria-label={dark ? "切换浅色主题" : "切换深色主题"} title={dark ? "浅色主题" : "深色主题"}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
          <button className="primary-button desktop-only" type="button">发布</button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar desktop-only" aria-label="仪表盘配置">
          <div className="sidebar-section"><span className="eyebrow">页面</span><button className="page-row active" type="button"><span>经营总览</span><ChevronDown size={15} /></button></div>
          <div className="sidebar-section">
            <span className="eyebrow">全局筛选</span>
            <label>业务日期<input type="text" value="2026-01 至 2026-06" readOnly /></label>
            <label>区域<select defaultValue="all"><option value="all">全部区域</option><option>华东</option><option>华南</option></select></label>
          </div>
          <div className="sidebar-section"><span className="eyebrow">数据状态</span><select aria-label="模拟数据状态" value={state} onChange={(event) => setState(event.target.value as DataState)}><option value="ready">成功</option><option value="loading">加载中</option><option value="empty">空数据</option><option value="error">错误</option></select></div>
          <div className="sidebar-note"><strong>编辑模式</strong><span>拖动组件标题移动，拖动右下角缩放。</span></div>
        </aside>

        <main className="main-content">
          <div className="dashboard-heading"><div><span className="eyebrow">销售中心 / 经营驾驶舱</span><h1>经营总览</h1></div><div className="period"><span>数据截至</span><strong>2026-06-30</strong></div></div>
          <div className="mobile-filter mobile-only"><span>2026-01 至 2026-06 · 全部区域</span><button type="button" aria-expanded={mobileFiltersOpen} aria-controls="mobile-filter-details" onClick={() => setMobileFiltersOpen(toggleReadonlyFilterPanel)}>筛选</button></div>
          {mobileFiltersOpen ? (
            <section className="mobile-filter-details mobile-only" id="mobile-filter-details" aria-label="当前只读筛选条件">
              <header><strong>当前筛选</strong><span>只读</span></header>
              <dl><div><dt>业务日期</dt><dd>2026-01 至 2026-06</dd></div><div><dt>区域</dt><dd>全部区域</dd></div></dl>
            </section>
          ) : null}
          {isMobile ? (
            <section className="mobile-grid mobile-only" aria-label="移动只读仪表盘">
              {mobileOrder.map((id) => <Widget key={id} id={id} dark={dark} state={state} onInteraction={onInteraction} />)}
            </section>
          ) : <DashboardGrid dark={dark} state={state} onInteraction={onInteraction} stressCount={stressCount} />}
          <output className="event-console" aria-live="polite">
            <strong>交互上下文</strong>
            <code>{interaction ? JSON.stringify(interaction) : "点击任一图形数据点以生成筛选上下文"}</code>
          </output>
        </main>
      </div>

      {comparisonOpen ? (
        <div className="modal-backdrop" role="presentation">
          <section className="comparison-modal" role="dialog" aria-modal="true" aria-labelledby="comparison-title">
            <header><div><span className="eyebrow">布局库运行时验证</span><h2 id="comparison-title">候选方案对比</h2></div><button className="icon-button" type="button" onClick={() => setComparisonOpen(false)} aria-label="关闭候选对比"><X size={18} /></button></header>
            <section className="candidate-block"><h3>候选 A · React Grid Layout 2.2.3</h3><p>React 声明式模型；当前主画布正在运行，可拖拽、缩放并序列化 Layout。</p></section>
            <Suspense fallback={<div className="state-panel">正在按需载入 GridStack 候选</div>}><GridStackCandidate /></Suspense>
          </section>
        </div>
      ) : null}
    </div>
  );
}

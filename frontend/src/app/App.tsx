import {
  ApartmentOutlined,
  DashboardOutlined,
  ImportOutlined,
} from "@ant-design/icons";
import { Layout, Menu, Spin } from "antd";
import { lazy, Suspense } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

const { Content, Sider } = Layout;

const DataIngestionPage = lazy(async () => {
  const module = await import("../features/data-ingestion/DataIngestionPage");
  return { default: module.DataIngestionPage };
});
const DatasetListPage = lazy(async () => {
  const module = await import("../features/data-modeling/DatasetListPage");
  return { default: module.DatasetListPage };
});
const DatasetWorkbenchPage = lazy(async () => {
  const module = await import("../features/data-modeling/DatasetWorkbenchPage");
  return { default: module.DatasetWorkbenchPage };
});
const SystemStatusPage = lazy(async () => {
  const module = await import("../features/system-status/SystemStatusPage");
  return { default: module.SystemStatusPage };
});

function routeKey(pathname: string): string {
  if (pathname.startsWith("/datasets")) return "datasets";
  if (pathname.startsWith("/data-ingestion")) return "ingestion";
  return "status";
}

export function App() {
  const location = useLocation();
  const selectedKey = routeKey(location.pathname);
  const isModelingWorkbench = /^\/datasets\/[^/]+/.test(location.pathname);

  return (
    <Layout className="app-shell">
      <Sider
        breakpoint="lg"
        collapsedWidth="0"
        width={248}
        className="app-sider"
      >
        <div className="brand">
          <DashboardOutlined aria-hidden />
          <span>BI System</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={[
            {
              key: "status",
              icon: <DashboardOutlined />,
              label: <NavLink to="/system-status">系统状态</NavLink>,
            },
            {
              key: "ingestion",
              icon: <ImportOutlined />,
              label: <NavLink to="/data-ingestion">数据导入</NavLink>,
            },
            {
              key: "datasets",
              icon: <ApartmentOutlined />,
              label: <NavLink to="/datasets">数据集</NavLink>,
            },
          ]}
        />
      </Sider>
      <Layout>
        <Content
          className={`app-content${isModelingWorkbench ? " is-workbench" : ""}`}
        >
          <Suspense
            fallback={
              <div className="route-loading" aria-label="页面加载中">
                <Spin size="large" />
              </div>
            }
          >
            <Routes>
              <Route path="/system-status" element={<SystemStatusPage />} />
              <Route path="/data-ingestion" element={<DataIngestionPage />} />
              <Route path="/datasets" element={<DatasetListPage />} />
              <Route
                path="/datasets/:datasetId"
                element={<DatasetWorkbenchPage />}
              />
              <Route
                path="*"
                element={<Navigate to="/data-ingestion" replace />}
              />
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
}

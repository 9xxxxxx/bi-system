import { DashboardOutlined, ImportOutlined } from "@ant-design/icons";
import { Layout, Menu } from "antd";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { DataIngestionPage } from "../features/data-ingestion/DataIngestionPage";
import { SystemStatusPage } from "../features/system-status/SystemStatusPage";

const { Content, Sider } = Layout;

export function App() {
  const location = useLocation();
  const selectedKey = location.pathname.startsWith("/data-ingestion")
    ? "ingestion"
    : "status";

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
          ]}
        />
      </Sider>
      <Layout>
        <Content className="app-content">
          <Routes>
            <Route path="/system-status" element={<SystemStatusPage />} />
            <Route path="/data-ingestion" element={<DataIngestionPage />} />
            <Route
              path="*"
              element={<Navigate to="/data-ingestion" replace />}
            />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}

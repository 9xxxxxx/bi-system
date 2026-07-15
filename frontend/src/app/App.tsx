import { DashboardOutlined } from "@ant-design/icons";
import { Layout, Menu, Typography } from "antd";

import { SystemStatusPage } from "../features/system-status/SystemStatusPage";

const { Content, Sider } = Layout;

export function App() {
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
          selectedKeys={["status"]}
          items={[
            {
              key: "status",
              icon: <DashboardOutlined />,
              label: "系统状态",
            },
          ]}
        />
      </Sider>
      <Layout>
        <Content className="app-content">
          <div className="page-header">
            <Typography.Title level={2}>系统状态</Typography.Title>
            <Typography.Text type="secondary">
              后端服务、数据库连接与前端环境的基础运行状态。
            </Typography.Text>
          </div>
          <SystemStatusPage />
        </Content>
      </Layout>
    </Layout>
  );
}

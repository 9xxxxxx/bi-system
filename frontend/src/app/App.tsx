import {
  ApartmentOutlined,
  DashboardOutlined,
  ImportOutlined,
  LogoutOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Avatar,
  Button,
  Layout,
  Menu,
  Result,
  Space,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import { lazy, Suspense, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { getCurrentUser, logout } from "../features/auth/api";
import { LoginPage } from "../features/auth/LoginPage";
import type { CurrentUser } from "../features/auth/types";
import { ApiError } from "../shared/api/client";

const { Content, Header, Sider } = Layout;
const authQueryKey = ["auth", "me"] as const;

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
  const queryClient = useQueryClient();
  const [sessionOverride, setSessionOverride] = useState<
    CurrentUser | null | undefined
  >(undefined);
  const meQuery = useQuery({
    queryKey: authQueryKey,
    queryFn: getCurrentUser,
    enabled: sessionOverride === undefined,
    retry: false,
  });
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
      setSessionOverride(null);
    },
  });

  const user = sessionOverride ?? meQuery.data;
  const authenticationRequired =
    sessionOverride === undefined &&
    meQuery.isError &&
    meQuery.error instanceof ApiError &&
    meQuery.error.status === 401;

  if (sessionOverride === null || authenticationRequired) {
    return (
      <LoginPage
        onAuthenticated={(nextUser) => {
          queryClient.setQueryData(authQueryKey, nextUser);
          setSessionOverride(nextUser);
        }}
      />
    );
  }
  if (
    meQuery.isLoading ||
    (sessionOverride === undefined && !user && !meQuery.isError)
  ) {
    return (
      <div className="auth-loading" aria-label="正在检查登录状态">
        <Spin size="large" />
        <Typography.Text type="secondary">正在检查登录状态</Typography.Text>
      </div>
    );
  }
  if (meQuery.isError || !user) {
    return (
      <Result
        className="auth-error-page"
        status="error"
        title="无法验证登录状态"
        subTitle={authErrorDescription(meQuery.error)}
        extra={
          <Button type="primary" onClick={() => meQuery.refetch()}>
            重新检查
          </Button>
        }
      />
    );
  }

  return (
    <AuthenticatedShell
      user={user}
      isLoggingOut={logoutMutation.isPending}
      logoutError={logoutMutation.isError ? logoutMutation.error : undefined}
      onLogout={() => logoutMutation.mutate()}
    />
  );
}

interface AuthenticatedShellProps {
  user: CurrentUser;
  isLoggingOut: boolean;
  logoutError?: unknown;
  onLogout: () => void;
}

function AuthenticatedShell({
  user,
  isLoggingOut,
  logoutError,
  onLogout,
}: AuthenticatedShellProps) {
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
        <Header className="app-header">
          <Space className="user-session" size="middle">
            <Avatar icon={<UserOutlined />} />
            <div className="user-session-name">
              <Typography.Text strong>{user.display_name}</Typography.Text>
              <Typography.Text type="secondary">
                @{user.username}
              </Typography.Text>
            </div>
            <Tooltip title="退出登录">
              <Button
                type="text"
                aria-label="退出登录"
                icon={<LogoutOutlined />}
                loading={isLoggingOut}
                onClick={onLogout}
              />
            </Tooltip>
          </Space>
        </Header>
        {logoutError !== undefined && (
          <Alert
            className="auth-action-alert"
            type="error"
            showIcon
            message="退出登录失败"
            description={authErrorDescription(logoutError)}
          />
        )}
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

function authErrorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "请检查网络连接后重试";
}

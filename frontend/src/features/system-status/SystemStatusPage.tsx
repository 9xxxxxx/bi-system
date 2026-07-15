import {
  ApiOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  DatabaseOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Col, Row, Skeleton, Statistic, Typography } from "antd";

import { getBackendReadiness } from "../../shared/api/client";

export function SystemStatusPage() {
  const readiness = useQuery({
    queryKey: ["system-status", "readiness"],
    queryFn: getBackendReadiness,
  });

  if (readiness.isLoading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  if (readiness.isError) {
    return (
      <Alert
        type="error"
        showIcon
        icon={<CloseCircleFilled />}
        title="系统连接异常"
        description="暂时无法获取后端就绪状态，请确认 FastAPI 服务已启动。"
      />
    );
  }

  if (!readiness.data) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  return (
    <div className="status-grid">
      <Alert
        type="success"
        showIcon
        icon={<CheckCircleFilled />}
        title="系统运行正常"
        description="前端已成功连接后端就绪检查接口。"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Statistic
            title="API 状态"
            value={readiness.data.status}
            prefix={<ApiOutlined />}
            styles={{ content: { color: "#1677ff" } }}
          />
        </Col>
        <Col xs={24} md={12}>
          <Statistic
            title="数据库"
            value={readiness.data.database}
            prefix={<DatabaseOutlined />}
            styles={{ content: { color: "#52c41a" } }}
          />
        </Col>
      </Row>
      <Typography.Paragraph type="secondary" className="status-note">
        当前页面用于验证 React、Ant Design、TanStack Query 与 FastAPI
        的基础契约。
      </Typography.Paragraph>
    </div>
  );
}

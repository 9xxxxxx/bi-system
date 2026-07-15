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

  return (
    <div>
      <div className="page-header">
        <Typography.Title level={2}>系统状态</Typography.Title>
        <Typography.Text type="secondary">
          后端服务、数据库连接与前端环境的基础运行状态。
        </Typography.Text>
      </div>
      {readiness.isLoading && <Skeleton active paragraph={{ rows: 4 }} />}
      {readiness.isError && (
        <Alert
          type="error"
          showIcon
          icon={<CloseCircleFilled />}
          title="系统连接异常"
          description="暂时无法获取后端就绪状态，请确认 FastAPI 服务已启动。"
        />
      )}
      {readiness.data && (
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
        </div>
      )}
    </div>
  );
}

import {
  ArrowLeftOutlined,
  AppstoreAddOutlined,
  FileAddOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  Radio,
  Spin,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  createDashboard,
  instantiateDashboardTemplate,
  listDashboardTemplates,
} from "../api";
import { dashboardErrorDescription } from "../presentation";
import { dashboardQueryKeys } from "../queryKeys";
import type { DashboardTemplateSummary } from "../types";
import "../dashboards.css";

type CreationSource = "blank" | "template";

export function DashboardCreatePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [source, setSource] = useState<CreationSource>(() =>
    searchParams.get("source") === "template" ? "template" : "blank",
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTemplate, setSelectedTemplate] =
    useState<DashboardTemplateSummary>();
  const templatesQuery = useQuery({
    queryKey: dashboardQueryKeys.templates(),
    queryFn: () => listDashboardTemplates(),
    enabled: source === "template",
  });
  const createMutation = useMutation({
    mutationFn: () => {
      const request = {
        name: name.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
      };
      if (source === "template" && selectedTemplate) {
        return instantiateDashboardTemplate(selectedTemplate.id, {
          ...request,
          template_version_id: selectedTemplate.latest_version_id,
        });
      }
      return createDashboard(request);
    },
    onSuccess: (dashboard) => {
      void queryClient.invalidateQueries({
        queryKey: dashboardQueryKeys.lists(),
      });
      navigate(`/dashboards/${dashboard.id}`, { replace: true });
    },
  });
  const canCreate =
    Boolean(name.trim()) &&
    (source === "blank" || Boolean(selectedTemplate)) &&
    !createMutation.isPending;

  return (
    <section
      className="dashboard-create-page"
      aria-labelledby="dashboard-create-title"
    >
      <header className="dashboard-create-header">
        <div>
          <Link to="/dashboards" className="dashboard-back-link">
            <ArrowLeftOutlined /> 仪表盘
          </Link>
          <Typography.Title id="dashboard-create-title" level={2}>
            新建仪表盘
          </Typography.Title>
          <Typography.Text type="secondary">
            从空白画布开始，或复制已发布模板
          </Typography.Text>
        </div>
      </header>
      <div className="dashboard-create-body">
        <Form layout="vertical" className="dashboard-create-form">
          <Radio.Group
            optionType="button"
            buttonStyle="solid"
            aria-label="创建来源"
            value={source}
            onChange={(event) => {
              setSource(event.target.value as CreationSource);
              setSelectedTemplate(undefined);
            }}
            options={[
              { label: "空白仪表盘", value: "blank" },
              { label: "团队模板", value: "template" },
            ]}
          />
          <Form.Item label="名称" required>
            <Input
              aria-label="仪表盘名称"
              maxLength={128}
              placeholder="例如：经营总览"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="说明">
            <Input.TextArea
              aria-label="仪表盘说明"
              maxLength={500}
              autoSize={{ minRows: 3, maxRows: 6 }}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Form.Item>
          {source === "template" ? (
            <Form.Item label="模板" required>
              {templatesQuery.isLoading ? (
                <Spin aria-label="正在加载仪表盘模板" />
              ) : templatesQuery.isError ? (
                <Alert
                  type="error"
                  showIcon
                  title="模板加载失败"
                  description={dashboardErrorDescription(templatesQuery.error)}
                  action={
                    <Button
                      size="small"
                      onClick={() => void templatesQuery.refetch()}
                    >
                      重试
                    </Button>
                  }
                />
              ) : (templatesQuery.data?.items.length ?? 0) === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无已发布模板"
                />
              ) : (
                <div className="dashboard-template-picker">
                  {templatesQuery.data?.items.map((template) => (
                    <button
                      key={template.latest_version_id}
                      type="button"
                      className={`dashboard-template-option${selectedTemplate?.latest_version_id === template.latest_version_id ? " is-selected" : ""}`}
                      aria-pressed={
                        selectedTemplate?.latest_version_id ===
                        template.latest_version_id
                      }
                      onClick={() => setSelectedTemplate(template)}
                    >
                      <strong>{template.name}</strong>
                      <span>
                        {template.description ||
                          `${template.page_count} 个页面`}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </Form.Item>
          ) : null}
          {createMutation.isError ? (
            <Alert
              type="error"
              showIcon
              title="仪表盘创建失败"
              description={dashboardErrorDescription(createMutation.error)}
            />
          ) : null}
          <Button
            type="primary"
            size="large"
            icon={
              source === "blank" ? <FileAddOutlined /> : <AppstoreAddOutlined />
            }
            disabled={!canCreate}
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建并进入编辑器
          </Button>
        </Form>
        <aside className="dashboard-create-summary" aria-label="创建结果说明">
          <strong>{source === "blank" ? "空白草稿" : "独立模板副本"}</strong>
          <span>
            {source === "blank"
              ? "创建一个页面和独立桌面、移动布局，之后可添加组件。"
              : "复制模板当前发布版本；模板后续升级不会改变此仪表盘。"}
          </span>
        </aside>
      </div>
    </section>
  );
}

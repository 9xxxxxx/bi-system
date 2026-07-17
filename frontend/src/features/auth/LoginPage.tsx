import { LockOutlined, LoginOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Input, Typography } from "antd";
import { useState } from "react";

import { ApiError } from "../../shared/api/client";
import { login } from "./api";
import type { CurrentUser } from "./types";

interface LoginPageProps {
  onAuthenticated: (user: CurrentUser) => void;
}

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "登录请求失败，请稍后重试";
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: onAuthenticated,
  });

  const canSubmit = username.trim().length > 0 && password.length > 0;

  return (
    <main className="auth-page" aria-labelledby="login-title">
      <section className="auth-panel">
        <div className="auth-mark" aria-hidden>
          <LockOutlined />
        </div>
        <Typography.Title id="login-title" level={2}>
          登录 BI System
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          进入你的数据分析工作区
        </Typography.Paragraph>
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit) {
              loginMutation.mutate({ username: username.trim(), password });
            }
          }}
        >
          <label htmlFor="auth-username">用户名</label>
          <Input
            id="auth-username"
            autoComplete="username"
            prefix={<LoginOutlined aria-hidden />}
            placeholder="输入用户名"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <label htmlFor="auth-password">密码</label>
          <Input.Password
            id="auth-password"
            autoComplete="current-password"
            prefix={<LockOutlined aria-hidden />}
            placeholder="输入密码"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {loginMutation.isError && (
            <Alert
              showIcon
              type="error"
              title="登录失败"
              description={errorDescription(loginMutation.error)}
            />
          )}
          <Button
            block
            type="primary"
            htmlType="submit"
            size="large"
            icon={<LoginOutlined aria-hidden />}
            disabled={!canSubmit}
            loading={loginMutation.isPending}
          >
            登录
          </Button>
        </form>
      </section>
    </main>
  );
}

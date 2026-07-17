import { requestJson } from "../../shared/api/client";
import type { CurrentUser, LoginInput } from "./types";

export function getCurrentUser(): Promise<CurrentUser> {
  return requestJson<CurrentUser>("/auth/me");
}

export function login(input: LoginInput): Promise<CurrentUser> {
  return requestJson<CurrentUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function logout(): Promise<void> {
  return requestJson<void>("/auth/logout", { method: "POST" });
}

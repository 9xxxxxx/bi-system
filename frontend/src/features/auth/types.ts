export interface CurrentUser {
  id: string;
  workspace_id: string;
  username: string;
  display_name: string;
  must_change_password: boolean;
  role_ids: string[];
  permissions: string[];
  is_system_admin: boolean;
}

export interface LoginInput {
  username: string;
  password: string;
}

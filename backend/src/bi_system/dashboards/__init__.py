from bi_system.dashboards.contracts import (
    CreateDashboard,
    CreateDashboardTemplate,
    DashboardComponentInput,
    DashboardLayoutInput,
    DashboardPageInput,
    DashboardPermissionInput,
    ReplaceDashboardPermissions,
    SaveDashboardVersion,
)
from bi_system.dashboards.service import (
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    replace_dashboard_permissions,
    restore_dashboard,
    save_dashboard_version,
)

__all__ = [
    "CreateDashboard",
    "CreateDashboardTemplate",
    "DashboardComponentInput",
    "DashboardLayoutInput",
    "DashboardPageInput",
    "DashboardPermissionInput",
    "ReplaceDashboardPermissions",
    "SaveDashboardVersion",
    "create_dashboard",
    "delete_dashboard",
    "get_dashboard",
    "list_dashboards",
    "replace_dashboard_permissions",
    "restore_dashboard",
    "save_dashboard_version",
]

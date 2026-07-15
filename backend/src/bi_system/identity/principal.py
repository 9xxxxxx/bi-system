from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QueryPrincipal:
    user_id: UUID
    workspace_id: UUID
    role_ids: frozenset[UUID] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_system_admin: bool = False

    def has_permission(self, permission: str) -> bool:
        return self.is_system_admin or permission in self.permissions

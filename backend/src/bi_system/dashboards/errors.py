from dataclasses import dataclass
from uuid import UUID


class DashboardServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DashboardNotFoundError(DashboardServiceError):
    pass


class DashboardForbiddenError(DashboardServiceError):
    pass


class DashboardConflictError(DashboardServiceError):
    pass


class DashboardConfigurationError(DashboardServiceError):
    pass


@dataclass(frozen=True, slots=True)
class DashboardTemplateReference:
    template_id: UUID
    template_name: str
    template_version_id: UUID
    version: int


class DashboardReferenceConflictError(DashboardConflictError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        references: tuple[DashboardTemplateReference, ...],
    ) -> None:
        super().__init__(code, message)
        self.references = references

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


class DashboardReferenceConflictError(DashboardConflictError):
    pass

class ProviderError(RuntimeError):
    def __init__(self, message: str, provider: str, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code

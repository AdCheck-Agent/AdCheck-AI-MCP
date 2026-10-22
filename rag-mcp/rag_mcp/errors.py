class DocumentError(ValueError):
    def __init__(self, message: str, code: str = "INVALID_DOCUMENT", status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


class StorageUnavailable(RuntimeError):
    pass


class EmbeddingUnavailable(RuntimeError):
    pass


class AttachedDocumentsTooLarge(RuntimeError):
    def __init__(self, chars: int, limit: int):
        super().__init__(f"첨부 문서 본문 {chars}자가 상한 {limit}자를 넘습니다.")
        self.chars, self.limit = chars, limit

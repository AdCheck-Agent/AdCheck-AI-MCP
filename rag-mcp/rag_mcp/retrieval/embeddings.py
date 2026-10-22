from typing import Protocol


class Embeddings(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# TODO(AI 2): implement a selected embedding provider and matching Qdrant vector dimension.
# No model or API key is required by the current mock retriever.

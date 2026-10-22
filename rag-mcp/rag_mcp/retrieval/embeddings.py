import asyncio
import math
import threading
from typing import Protocol

from rag_mcp.config import Settings
from rag_mcp.errors import EmbeddingUnavailable


def token_windows(count: int, limit: int, overlap: int) -> list[tuple[int, int]]:
    """Evenly sized windows of at most `limit` tokens, each overlapping by at least `overlap`.

    Fixed-stride splitting left a short tail (often just a citation line) that ranked
    near the top for unrelated queries; spreading the tokens evenly avoids that.
    """
    if count <= limit:
        return [(0, count)] if count else []
    pieces = math.ceil((count - overlap) / (limit - overlap))
    size = math.ceil((count + (pieces - 1) * overlap) / pieces)
    return [
        ((k * (count - size)) // (pieces - 1), (k * (count - size)) // (pieces - 1) + size)
        for k in range(pieces)
    ]


class Embeddings(Protocol):
    profile: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def split(self, text: str) -> list[str]: ...


class LocalEmbeddings:
    """Lazy CPU inference; health/startup never downloads model weights."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile = settings.embedding_profile
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from fastembed import TextEmbedding
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        cache = str(self.settings.rag_model_cache)
        model = TextEmbedding(model_name=self.settings.rag_embedding_model, cache_dir=cache)
        path = hf_hub_download(self.settings.rag_embedding_model, "tokenizer.json", cache_dir=cache)
        tokenizer = Tokenizer.from_file(path)
        tokenizer.no_truncation()
        self._tokenizer, self._model = tokenizer, model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self._load()
            return [vector.tolist() for vector in self._model.embed(texts, batch_size=32)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = await asyncio.to_thread(self._embed, texts)
            if len(vectors) != len(texts) or any(
                len(v) != 384 or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors
            ):
                raise ValueError("임베딩 개수·차원·유효값 불일치")
            return vectors
        except Exception as exc:
            raise EmbeddingUnavailable("임베딩 모델 로드 또는 추론에 실패했습니다.") from exc

    def _split(self, text: str) -> list[str]:
        with self._lock:
            self._load()
            offsets = self._tokenizer.encode(text, add_special_tokens=False).offsets
        windows = token_windows(
            len(offsets), self.settings.rag_chunk_tokens, self.settings.rag_chunk_overlap
        )
        parts = (text[offsets[start][0] : offsets[end - 1][1]].strip() for start, end in windows)
        return [part for part in parts if part]

    async def split(self, text: str) -> list[str]:
        try:
            return await asyncio.to_thread(self._split, text)
        except Exception as exc:
            raise EmbeddingUnavailable("문서 토큰 분할에 실패했습니다.") from exc

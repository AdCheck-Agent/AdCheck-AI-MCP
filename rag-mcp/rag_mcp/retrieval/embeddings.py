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


def register_if_unsupported(settings: Settings) -> None:
    """Register models FastEmbed does not list itself (BAAI/bge-m3) as custom ONNX models.

    bge-m3 dense vectors are the CLS token of the last layer, L2-normalised. Weights are the
    official ONNX export in the model repository (graph file plus one external-data file).
    """
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    name = settings.rag_embedding_model
    if name in {m["model"] for m in TextEmbedding.list_supported_models()}:
        return
    TextEmbedding.add_custom_model(
        model=name,
        pooling=PoolingType.CLS,
        normalization=True,
        sources=ModelSource(hf=name),
        dim=settings.rag_embedding_dim,
        model_file="onnx/model.onnx",
        additional_files=["onnx/model.onnx_data"],
    )


class Embeddings(Protocol):
    profile: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def split(self, text: str) -> list[str]: ...


class LocalEmbeddings:
    """Lazy CPU inference; health/startup never downloads model weights."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile = settings.embedding_profile
        self.dim = settings.rag_embedding_dim
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
        register_if_unsupported(self.settings)
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
                len(v) != self.dim or not all(math.isfinite(x) for x in v) or not any(v)
                for v in vectors
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

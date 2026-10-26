import asyncio
import math
import threading
from typing import Protocol

from rag_mcp.config import Settings
from rag_mcp.errors import EmbeddingUnavailable


def token_windows(count: int, limit: int, overlap: int) -> list[tuple[int, int]]:
    """최대 `limit` 토큰, 서로 최소 `overlap`만큼 겹치는 균등한 크기의 창.

    고정 간격으로 자르면 짧은 끝 조각(대개 출처 한 줄)이 남아 무관한 질문에도
    상위에 올랐다. 토큰을 고르게 나누면 이를 피할 수 있다.
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
    """FastEmbed가 스스로 목록에 두지 않는 모델(BAAI/bge-m3)을 사용자 ONNX 모델로 등록한다.

    bge-m3 dense 벡터는 마지막 층 CLS 토큰을 L2 정규화한 값이다. 가중치는 모델 저장소의
    공식 ONNX 내보내기(그래프 파일과 외부 데이터 파일 하나)다.
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
    """필요할 때 CPU로 추론한다. 헬스체크와 시작 시에는 모델 가중치를 받지 않는다."""

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

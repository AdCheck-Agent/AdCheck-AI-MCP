import pytest
from pydantic import ValidationError
from rag_mcp.config import Settings
from rag_mcp.retrieval.embeddings import register_if_unsupported


def test_defaults_use_bge_m3_with_matching_dimension_and_profile() -> None:
    settings = Settings(_env_file=None)
    assert settings.rag_embedding_model == "BAAI/bge-m3"
    assert settings.rag_embedding_dim == 1024
    assert settings.embedding_profile == "fastembed:BAAI/bge-m3:1024"
    assert (settings.rag_chunk_tokens, settings.rag_chunk_overlap) == (512, 64)


def test_profile_changes_with_model_so_old_databases_are_not_mixed() -> None:
    old = Settings(
        _env_file=None,
        rag_embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        rag_embedding_dim=384,
    )
    assert old.embedding_profile != Settings(_env_file=None).embedding_profile


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_chunk_tokens=64, rag_chunk_overlap=64)


def test_registering_custom_model_twice_is_harmless() -> None:
    settings = Settings(_env_file=None, rag_embedding_model="BAAI/bge-m3")
    register_if_unsupported(settings)
    register_if_unsupported(settings)

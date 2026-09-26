"""B-CR-05：build_chroma_index.main() 不得因引用不存在的 settings 常數崩潰。"""
from elc_audit_engine.rule_repository.embeddings import chroma_store
from elc_audit_engine.rule_repository.scripts import build_chroma_index


def test_main_runs_and_passes_source_version(monkeypatch, tmp_path):
    from config import settings

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(chroma_store, "build_chroma_collection", fake_build)
    monkeypatch.setattr(settings, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAG_DIR", str(tmp_path / "rag"))
    (tmp_path / "docx_trees.json").write_text("[]", encoding="utf-8")

    build_chroma_index.main()

    assert captured["docx_trees_path"].endswith("docx_trees.json")
    assert "source_version" in captured


def test_main_without_docx_trees_is_non_blocking(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(chroma_store, "build_chroma_collection", lambda **kw: {"status": "skipped"})
    monkeypatch.setattr(settings, "DB_DIR", str(tmp_path))
    build_chroma_index.main()

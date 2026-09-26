"""B-WR-14：重建失敗時舊索引須完整保留；未帶版本也要真的更新內容。"""
import json
import sys
import types

from elc_audit_engine.rule_repository.embeddings import chroma_store


class _Coll:
    def __init__(self, store, name):
        self.store, self.name, self.docs = store, name, {}

    def count(self):
        return len(self.docs)

    def get(self, limit=None, include=None):
        return {"metadatas": [m for _, m in list(self.docs.values())[:limit]]}

    def upsert(self, ids, documents, metadatas):
        if self.store.fail_on_upsert:
            raise RuntimeError("embedding download failed")
        for i, d, m in zip(ids, documents, metadatas):
            self.docs[i] = (d, m)

    def modify(self, name):
        self.store.cols[name] = self.store.cols.pop(self.name)
        self.name = name


class _Client:
    def __init__(self, store):
        self.store = store

    def list_collections(self):
        return list(self.store.cols)

    def get_collection(self, name):
        return self.store.cols[name]

    def create_collection(self, name):
        self.store.cols[name] = _Coll(self.store, name)
        return self.store.cols[name]

    def delete_collection(self, name):
        self.store.cols.pop(name)


def _install_fake(monkeypatch, store):
    fake = types.ModuleType("chromadb")
    fake.PersistentClient = lambda path: _Client(store)
    monkeypatch.setitem(sys.modules, "chromadb", fake)


def _trees(tmp_path, text):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"a.docx": {"title": "a", "level": 0, "path": "a", "full_text": text, "children": [], "table_refs": []}},
                            ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_failed_rebuild_keeps_old_index(tmp_path, monkeypatch):
    store = types.SimpleNamespace(cols={}, fail_on_upsert=False)
    _install_fake(monkeypatch, store)
    assert chroma_store.build_chroma_collection(_trees(tmp_path, "舊內容" * 20), str(tmp_path))["status"] == "ok"
    old_docs = dict(store.cols["rule_articles"].docs)

    store.fail_on_upsert = True
    result = chroma_store.build_chroma_collection(_trees(tmp_path, "新內容" * 20), str(tmp_path))
    assert result["status"] == "skipped"
    assert store.cols["rule_articles"].docs == old_docs
    assert "rule_articles__staging" not in store.cols


def test_rebuild_without_version_replaces_content(tmp_path, monkeypatch):
    store = types.SimpleNamespace(cols={}, fail_on_upsert=False)
    _install_fake(monkeypatch, store)
    chroma_store.build_chroma_collection(_trees(tmp_path, "舊內容" * 20), str(tmp_path))
    chroma_store.build_chroma_collection(_trees(tmp_path, "新內容" * 20), str(tmp_path))
    texts = [d for d, _ in store.cols["rule_articles"].docs.values()]
    assert texts and all("新內容" in t for t in texts)


def test_missing_trees_file_does_not_raise(tmp_path):
    result = chroma_store.build_chroma_collection(str(tmp_path / "none.json"), str(tmp_path))
    assert result["status"] == "skipped"

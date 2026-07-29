import os

import pytest

from config import settings


def test_settings_module_importable():
    """config.settings 可載入，且 PROJECT_ROOT 指向一個實際存在的目錄。"""
    assert os.path.isdir(settings.PROJECT_ROOT)


def test_llama_config_defaults():
    """未覆寫環境變數時，LLAMA_CPP_BASE_URL 應為預設的 localhost:8080。"""
    assert settings.LLAMA_CPP_BASE_URL == "http://localhost:8080"


def test_load_llama_config_returns_locked_values():
    """load_llama_config() 應回傳含 D2 鎖定值的 dict（非佔位值）。"""
    cfg = settings.load_llama_config()
    assert cfg["inference"]["n_ctx"] == 32768
    assert cfg["model"]["name"] == "Ornith-1.0-9B"


def test_load_llama_config_missing_file_raises(monkeypatch):
    """指向不存在的路徑時，load_llama_config() 應 fail-fast 拋出 FileNotFoundError。"""
    monkeypatch.setattr(settings, "LLAMA_CONFIG_PATH", "/nonexistent/path/llama_config.json")
    with pytest.raises(FileNotFoundError):
        settings.load_llama_config()

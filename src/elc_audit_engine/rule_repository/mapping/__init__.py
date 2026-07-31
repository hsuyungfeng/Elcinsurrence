"""rule_mapping 預編譯快取建置子模組。

包含 llama.cpp client wrapper（`llm_client.py`）、
候選條文比對 prompt 樣板（`prompts.py`），
以及一次性批次建置腳本（`build_mapping.py`）。

LLM 僅在此建置步驟使用一次（D-04），查詢階段（Phase 3-5）
完全零 LLM，只走 SQLite `rule_mapping` 快取表查表（D-05）。
"""

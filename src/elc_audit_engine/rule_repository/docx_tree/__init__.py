"""docx 樹狀索引模組：自製 PageIndex 風格文件樹狀結構建置。

注意：本模組完全不使用已安裝的 `pageindex` PyPI 套件（該套件為需要
API key、會將文件上傳至 api.pageindex.ai 的雲端 SaaS 服務，違反本專案
D2「病患/文件資料不得離開本機」的鎖定決策）。此處「PageIndex」僅作為
概念名稱（樹狀文件索引），以 python-docx + regex + JSON 自製實作。
"""

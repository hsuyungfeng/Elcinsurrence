# Phase 32 Plan 11: 客戶端 UDP 探索與自動復原 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：C2、C3、D-32-12  

---

## 執行成果

1. **UDP 廣播探測實作 (`deploy/windows_agent/discovery.py`)**：
   - 定義常數 `DISCOVERY_PORT = 5002`、`DISCOVERY_MAGIC = b"ELC_DISCOVER_SERVER_V1"`，與伺服器端一致。
   - 實作 `udp_probe(port, timeout, socket_factory, broadcast_addrs) -> List[str]`：
     - 送出魔術字串至 `255.255.255.255` 及本機 `/24` 廣播位址。
     - 絕不呼叫 `sock.bind`（由作業系統指派動態來源埠，避免觸發 Windows 防火牆彈窗）。
     - 嚴格過濾回覆：大小超過 2048 bytes 丟棄、非 JSON 或非字典丟棄、`service` 不符丟棄、主機位址非私有/回環網段丟棄、主機名稱與來源 IP 不符（防偽造）丟棄。
     - 回傳合格伺服器 URL 清單並自動去重。

2. **位址自動復原與院所代碼驗證 (`rediscover_and_verify`)**：
   - `AgentSettings` 新增 `facility_code: str = ""` 欄位，在 `load_settings` 與 `save_settings` 中保持向後相容。
   - 實作 `rediscover_and_verify(settings, probe, udp_probe_fn, subnet_hosts_provider, port, timeout)`：
     - 若 `facility_code` 為空回傳 `(None, "needs_setup")`。
     - 若 `last_server_url` 連線正常且 `facility_code` 相符，回傳 `(url, "unchanged")`。
     - 若連線失敗，啟動 UDP 廣播與子網掃描進行重新探索；若候選中有 `facility_code` 相同者，自動更新 `settings.last_server_url` 並回傳 `(new_url, "recovered")`。
     - 若候選者代碼皆不符合（不同診所），回傳 `(None, "mismatch")`，絕不擅自切換。
     - 若無任何候選回傳 `(None, "not_found")`。

3. **測試與驗證 (`tests/test_agent_discovery.py`)**：
   - 測試常數比對 (`test_discovery_constants_match_server`)。
   - 偽造 socket 封包過濾測試 (`test_udp_probe_filters_invalid_responses`)。
   - 端對端 loopback 探索測試 (`test_udp_probe_loopback_e2e`)。
   - 自動復原 5 種情境完整測試（unchanged, recovered, mismatch, needs_setup, not_found）。
   - 全數通過（23 passed in 9.06s）。

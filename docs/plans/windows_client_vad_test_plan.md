# Phase 39: Windows Client 分段錄音與 VAD 自動錄音實作與測試作業手冊

> **狀態**：草案與規格指引（Phase 39 Server 端完成後交付，本階段不直接更動 Windows 端原始碼）  
> **目標讀者**：Windows Client (SoapVoice / Traffic Bar) 開發人員、診間現場維護人員、整合測試人員

---

## 一、架構背景與規格

為解決診間醫師因問診繁忙「忘記按下錄音鍵」的臨床痛點，Client 端透過輕量語音活動偵測（VAD）與環形緩衝區（Ring Buffer）實作常駐語音偵測與自動觸發錄音。

### 1.1 核心規格
- **音訊格式**：16 kHz, 16-bit mono PCM WAV。
- **單段上限**：4 MiB（約 2 分鐘音訊）。
- **觸發前綴（Pre-roll）**：常駐 3.0 秒環形記憶體緩衝區（約 96,000 bytes PCM），當偵測到語音活動起點時，將前綴音訊作為分段 `seq: 0` 送出，確保問診第一句話不被截斷。
- **靜音自動完結（Auto-finalize）**：問診結束後若持續 30 秒未偵測到人聲（Speech Absence），Client 自動發起 `POST /api/cycles/<cycle_id>/finalize`。

---

## 二、Windows Client (SoapVoice) 程式碼修改指引

> **注意**：本節提供日後在 `SoapVoice/client/audio_recorder.py` 落地之架構範式，Phase 39 階段請勿在未經簽核前修改檔案。

### 2.1 模組相依
```text
onnxruntime>=1.16.0
numpy>=1.24.0
pyaudio>=0.2.14
```
推薦使用 `silero-vad.onnx`（約 2 MB，單次推論約 1~2 ms，CPU 佔用率 < 1%）。

### 2.2 環形緩衝區與 VAD 監聽邏輯虛擬碼
```python
import collections
import io
import wave
import numpy as np
import onnxruntime as ort

class VadAudioRecorder:
    def __init__(self, sample_rate=16000, preroll_sec=3.0, vad_threshold=0.5):
        self.sample_rate = sample_rate
        self.frame_size = 512  # Silero VAD 標準 512 frames (32ms)
        self.vad_threshold = vad_threshold
        # 3 秒 pre-roll buffer (以 frame 塊為單位)
        max_blocks = int(preroll_sec * sample_rate / self.frame_size)
        self.ring_buffer = collections.deque(maxlen=max_blocks)
        
        # 狀態控制
        self.is_recording = False
        self.silence_blocks_count = 0
        self.max_silence_blocks = int(30.0 * sample_rate / self.frame_size) # 30 秒靜音
        
        # 初始化 ONNX session
        self.vad_session = ort.InferenceSession("models/silero_vad.onnx")

    def process_pcm_block(self, pcm_data: bytes):
        """每 32ms 呼叫一次"""
        # 轉為 float32 正規化音訊給 ONNX
        audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        
        # VAD 評分
        ort_inputs = {"input": audio_float32[np.newaxis, :]}
        speech_prob = self.vad_session.run(None, ort_inputs)[0][0]
        
        if not self.is_recording:
            # 監聽狀態：常態記入環形緩衝區
            self.ring_buffer.append(pcm_data)
            if speech_prob >= self.vad_threshold:
                # 觸發起點！
                self.start_cycle_from_vad()
        else:
            # 錄音中狀態：累積音訊分段
            self.active_chunk_buffer.extend(pcm_data)
            if speech_prob < self.vad_threshold:
                self.silence_blocks_count += 1
                if self.silence_blocks_count >= self.max_silence_blocks:
                    # 連續 30 秒無人聲，自動完成錄音
                    self.stop_and_finalize_cycle()
            else:
                self.silence_blocks_count = 0
```

### 2.3 快捷列狀態與心跳回報 (Heartbeat)
Windows Client 每 5 秒回報心跳至 `POST /api/clients/heartbeat`：
```json
{
  "machine_id": "win-clinic-exam-01",
  "client_version": "1.4.0",
  "vad_listening": true,
  "chunks_pending": 0
}
```
- 當處於背景監聽時，`vad_listening` 帶 `true`（嚴格布林型態）。
- 快捷列燈號對應：
  - **白燈 / 藍燈**：VAD 監聽中（`vad_listening: true`，待命）。
  - **閃爍紅燈**：偵測到語音活動，已自動建立 Cycle 並開始串流分段（`trigger_mode: "vad_auto"`）。
  - **黃燈**：30 秒靜音完結，正在呼叫 `finalize` 並等候後端 ASR/SOAP。

---

## 三、弱網容錯與上傳重試規範

1. **固定分段序號 (`seq`)**：
   - 每個分段產生時編號 `seq = 0, 1, 2...`，不可隨意重編或跳號。
   - `seq: 0` 為 3 秒 pre-roll 緩衝區所封裝之 WAV。
2. **等冪性重送 (Idempotency)**：
   - 遇到網路中斷或逾時（HTTP timeout > 5s），Client 必須將同一段音訊二進位保持不變重送，宣告相同 `sha256`。
   - 伺服器端若已收到該分段，會回傳 `200 OK` 且帶 `{"duplicate": true}`，Client 應將此視為成功並繼續送下一段。
3. **退避演算法 (Exponential Backoff)**：
   - 重試間隔建議：`1s -> 2s -> 4s -> 8s`（最多重試 5 次）。
   - 若重試 5 次皆失敗，將分段寫入本機磁碟暫存，待連線恢復後依 `seq` 依序回放補送。

---

## 四、實體驗測作業檢核表 (Physical Verification Checklist)

本表格供診間實機測試與維護人員逐項驗收簽核：

| 檢驗編號 | 測試項目 | 測試情境與操作說明 | 預期結果 | 測試結果 | 簽核 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **V-01** | **硬體麥克風取樣相容性** | 連接 USB 麥克風或陣列麥克風，開啟 Client 程式。 | 成功建立 16 kHz 16-bit mono 輸入流，無裝置鎖死或雜音。 | [ ] 通過<br>[ ] 失敗 | |
| **V-02** | **鍵盤打字/滑鼠防誤觸** | 醫師不發話，在機械鍵盤/薄膜鍵盤快速打字 30 秒，並點擊滑鼠。 | VAD 機率維持在 0.3 以下，系統不觸發紅燈錄音（不誤判）。 | [ ] 通過<br>[ ] 失敗 | |
| **V-03** | **日常關門/紙張噪音防誤觸** | 模擬診間關門聲、抽屜開關、病歷翻頁聲。 | 能量雖然有峰值，但神經網路 VAD 判定為非語音，不啟動錄音。 | [ ] 通過<br>[ ] 失敗 | |
| **V-04** | **開口即時觸發 (Onset)** | 醫師對病患說「陳先生你好，今天哪裡不舒服？」 | 說話 200ms 內快捷列轉為紅燈錄音，`seq: 0` 包含前置 3 秒音訊。 | [ ] 通過<br>[ ] 失敗 | |
| **V-05** | **問診首句完整性檢驗** | 檢查後端組裝後的 `full.wav` 播放或逐字稿。 | 首句「陳先生你好」完整無缺漏，無開頭吃字現象。 | [ ] 通過<br>[ ] 失敗 | |
| **V-06** | **30 秒靜音自動完結** | 問診結束，醫師與病患停止對話 30 秒。 | 達到 30 秒靜音門檻後，系統自動送出 finalize，燈號轉黃燈處理。 | [ ] 通過<br>[ ] 失敗 | |
| **V-07** | **手動提早結束連動** | 若醫師問診完畢不想等 30 秒，手動點擊快捷列結束。 | 立即送出目前剩餘分段並 finalize，無漏段。 | [ ] 通過<br>[ ] 失敗 | |
| **V-08** | **弱網拔線與恢復補送** | 錄音進行至第 2 段時拔除診間網路線 10 秒後插回。 | Client 正確重試，伺服器收到齊全分段，最終 `full.wav` 正確無損。 | [ ] 通過<br>[ ] 失敗 | |
| **V-09** | **背景待命資源佔用** | 保持 VAD 監聽模式持續運作 4 小時。 | CPU 佔用率持續低於 1.5%，記憶體無洩漏（小於 80 MB）。 | [ ] 通過<br>[ ] 失敗 | |

---

## 五、異常處置與日誌指引

1. **誤判頻繁觸發**：可調整 `SoapVoice` 設定檔中的 `vad_threshold`（預設 0.5，雜音嚴重之診間可調升至 0.65~0.70）。
2. **前綴音訊吃字**：若醫師發話速度極快，可將 `preroll_sec` 由 3.0 秒調升為 4.0 秒。
3. **分段拒絕除錯**：檢查 Windows Client 端日誌是否有 `422 sequence_out_of_range` 或 `413 cycle_limit_exceeded`，確認單段未超過 4 MiB 且總段數未超過 120 段。

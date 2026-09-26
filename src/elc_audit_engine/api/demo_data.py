"""未匯入任何案件時 GET 清單回傳的示範資料（每筆帶 "demo": true）。

僅供 UI 展示工作流；匯入後改回傳 CaseStore 內的真實案件。
"""

DEMO_SAMPLING_CASES = [
    {
        "id": "SAMP-001",
        "demo": True,
        "case_seq": "101",
        "record_no": "M1001",
        "patient_name": "林聰明",
        "order_code": "14050B",
        "order_name": "糖化血色素檢驗 HbA1c",
        "visit_date": "115/07/10",
        "clinic": "家醫科",
        "support_level": "薄弱",
        "verdict": "部分支持",
        "soap": "S: 糖尿病追蹤，無發燒不適。\nO: BP 120/80\nA: DM Type 2\nP: 開立 HbA1c 抽血追蹤",
        "missing_reason": "病歷 SOAP A 欄僅記載簡寫 DM，未附上近三次血糖趨勢與檢驗必要性說明。"
    },
    {
        "id": "SAMP-002",
        "demo": True,
        "case_seq": "102",
        "record_no": "M1002",
        "patient_name": "黃淑芬",
        "order_code": "33084B",
        "order_name": "胸部 X 光攝影 (單視角)",
        "visit_date": "115/07/12",
        "clinic": "胸腔內科",
        "support_level": "充分",
        "verdict": "支持",
        "soap": "S: 咳嗽持續超過兩週，伴隨發燒與黃痰。\nO: Breathing sound: Right lower lung crackles (+), Temp 38.5C\nA: Suspected Pneumonia\nP: Order CXR (Single view)",
        "missing_reason": "病歷完整記載發燒、聽診囉音與臨床適應症，符合預審強支持標準。"
    }
]


DEMO_APPEAL_CASES = [
    {
        "id": "APP-001",
        "demo": True,
        "case_seq": "201",
        "record_no": "M2001",
        "patient_name": "王大明",
        "order_code": "64140C",
        "order_name": "甲床與手指重建術",
        "deduct_amount": 3200,
        "deduction_reason": "病歷未記載甲床損傷範圍與術前影像評估",
        "visit_date": "115/06/20",
        "soap": "S: 右手食指重物壓砸傷後劇痛出血。\nO: 食指末端甲床撕裂，指甲剝離。\nA: Nail bed injury\nP: Schedule nail bed repair surgery.",
        "multisource_evidence": {
            "labs": [
                {"date": "2026-06-20", "name": "CBC/WBC", "result": "11,500 /uL (異常偏高)", "unit": "/uL"}
            ],
            "images": [
                {"date": "2026-06-20", "name": "Finger X-ray", "report": "Distal phalanx fracture with nail bed defect (遠端指骨骨折併甲床缺損)", "dicom_id": "DICOM-9982"}
            ],
            "cloud_sync": [
                {"date": "2026-05-15", "source": "健保雲端跨院病歷", "note": "外院 X 光顯示右食指遠端指骨骨折"}
            ]
        }
    },
    {
        "id": "APP-002",
        "demo": True,
        "case_seq": "202",
        "record_no": "M2002",
        "patient_name": "張美玲",
        "order_code": "14050B",
        "order_name": "糖化血色素檢驗 HbA1c",
        "deduct_amount": 150,
        "deduction_reason": "費用申報與上一次檢驗間隔未滿3個月",
        "visit_date": "115/07/01",
        "soap": "S: 門診追蹤 DM。\nO: FPG 168\nA: DM control poor\nP: Adjust insulin, recheck HbA1c",
        "multisource_evidence": {
            "labs": [
                {"date": "2026-07-01", "name": "HbA1c", "result": "9.1 %", "unit": "%"}
            ],
            "images": [],
            "cloud_sync": [
                {"date": "2026-03-25", "source": "本院歷程", "note": "上次 HbA1c 檢驗日為 2026-03-25 (間隔已達 97 天，符合健保規定)"}
            ]
        }
    }
]

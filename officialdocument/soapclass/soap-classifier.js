/**
 * SOAP 自動分類系統 - 醫療語音文字轉SOAP
 * 基於關鍵詞匹配進行智能分類
 *
 * 功能：
 * - 將語音轉錄的文字自動分類到 S/O/A/P
 * - 支持中文醫學術語
 * - 可自定義關鍵詞庫
 */

// ============================================================================
// 關鍵詞定義
// ============================================================================

const SOAPKeywords = {
    // S - 主訴 (Subjective: 患者主觀症狀)
    subjective: {
        keywords: [
            '疼痛', '痛', '酸', '脹', '痠',
            '頭痛', '頭暈', '暈', '眩暈', '暈眩',
            '咳嗽', '咳', '喉嚨痛', '喉痛',
            '發燒', '發熱', '發汗', '出汗',
            '噁心', '嘔吐', '吐', '腹瀉', '便祕', '便秘',
            '疲勞', '疲倦', '無力', '乏力', '沒精神',
            '失眠', '睡眠不足', '睡眠障礙',
            '食慾', '胃口', '沒胃口', '厭食',
            '腹痛', '肚子痛', '肚痛', '胃痛',
            '四肢無力', '無力感', '肌肉無力',
            '皮膚', '搔癢', '癢', '起疹子', '紅疹',
            '流鼻水', '鼻塞', '打噴嚏',
            '頻尿', '尿頻', '夜間頻尿',
            '心悸', '心跳加速', '心臟跳動',
            '呼吸困難', '喘', '喘不過氣',
            '胸悶', '胸痛', '胸部不適',
            '月經', '生理期', '經期',
            '視力', '眼睛', '看不清', '模糊',
            '耳鳴', '聽力下降',
            '手腳冰冷', '冰冷', '怕冷',
            '口乾', '口渴', '乾渴',
            '體重', '體重下降', '消瘦', '發胖', '肥胖',
        ],
        weight: 1.0
    },

    // O - 客觀 (Objective: 檢查和檢驗結果)
    objective: {
        keywords: [
            // 生命徵象
            '血壓', '心跳', '脈搏', '體溫', '呼吸頻率',
            '血氧', '血糖', '血紅蛋白', 'Hb',

            // 檢驗結果
            '白血球', 'WBC', '紅血球', 'RBC',
            '血小板', '血清', '尿素氮', '肌酸酐',
            '肝功能', '膽紅素', 'GOT', 'GPT', 'AST', 'ALT',
            '血脂', '膽固醇', '三酸甘油酯', '低密度脂蛋白',
            '尿蛋白', '尿糖', '尿潛血',
            '胸部X光', '胸部攝影', 'CT', '核磁共振', 'MRI',
            '超音波', '心電圖', 'EKG', 'ECG',
            '內視鏡', '胃鏡', '大腸鏡',

            // 物理檢查
            '檢查', '觸診', '聽診', '叩診', '視診',
            '瞳孔', '血管', '淋巴結', '肝脾',
            '腹部', '脊椎', '四肢', '關節',
            '神經學檢查', '運動', '感覺', '反射',
            '腺體', '甲狀腺',

            // 影像描述
            '浸潤', '陰影', '實質', '結節', '肫瘤', '腫塊',
            '液體', '積液', '胸水', '腹水',
            '萎縮', '擴大', '肥厚',
        ],
        weight: 0.95
    },

    // A - 評估 (Assessment: 診斷和臨床評估)
    assessment: {
        keywords: [
            // 常見診斷
            '感冒', '流感', '肺炎', '支氣管炎',
            '糖尿病', '高血壓', '高血脂', '心臟病',
            '腎臟病', '肝炎', '肝硬化',
            '甲狀腺', '甲狀腺亢進', '甲狀腺低下',
            '胃炎', '胃潰瘍', '十二指腸潰瘍',
            '腸胃炎', '大腸激躁症',
            '膽囊炎', '膽結石', '膽囊結石',
            '關節炎', '骨關節炎', '類風濕',
            '腰椎', '頸椎', '椎間盤突出',
            '肌肉拉傷', '扭傷', '骨折',
            '皮膚炎', '濕疹', '蕁麻疹', '皮膚病',
            '感染', '發炎', '發炎症狀',
            '貧血', '低血糖', '低血壓',
            '焦慮症', '憂鬱症', '失眠症',
            '過敏', '過敏性', '過敏反應',
            '中風', '腦血管', '腦梗塞',
            '腫瘤', '癌症', '惡性腫瘤',
            '痛風', '尿酸',
            '肥胖症', '代謝症候群',

            // 診斷詞
            '診斷', '診為', '初步診斷', '臨床診斷',
            '疑似', '可能', '符合',
            '排除', '鑑別',
        ],
        weight: 1.0
    },

    // P - 計劃 (Plan: 治療計畫和建議)
    plan: {
        keywords: [
            // 藥物相關
            '藥物', '用藥', '吃藥', '服用', '投予',
            '抗生素', '止痛', '止咳', '退燒',
            '注射', '打針', '肌肉注射', '靜脈注射',
            '點滴', '輸液', '靜脈輸液',
            '膏藥', '貼', '貼布', '貼藥',

            // 治療相關
            '治療', '治療方式', '治療計畫',
            '手術', '開刀', '開刀房', '麻醉',
            '物理治療', '復健', '復建',
            '中醫', '針灸', '拔罐', '刮痧',
            '放射線', '放射治療', '化療', '化學治療',
            '透析', '血液透析', '腹膜透析',

            // 監測和追蹤
            '監測', '追蹤', '追蹤檢查', '複診',
            '定期', '定期檢查', '定期回診',
            '複查', '複驗', '回診',
            '觀察', '居家觀察',
            '衛教', '健康教育', '飲食衛教',

            // 生活方式建議
            '飲食', '飲食控制', '低鹽', '低脂', '低糖',
            '運動', '適度運動', '休息',
            '水分', '補充水分', '多喝水',
            '戒菸', '戒酒', '禁菸', '禁酒',
            '體重控制', '減重', '增重',
            '避免', '禁止', '不要',
            '保暖', '保持溫暖', '不受風',
            '睡眠', '充足睡眠',

            // 其他建議
            '轉介', '轉診', '轉院', '轉送',
            '住院', '出院', '出院後',
            '急診', '急診就醫',
            '備註', '注意事項', '特別注意',
        ],
        weight: 0.95
    }
};

// ============================================================================
// SOAP 分類器
// ============================================================================

class SOAPClassifier {
    constructor(keywords = SOAPKeywords) {
        this.keywords = keywords;
        this.classification = {
            subjective: [],
            objective: [],
            assessment: [],
            plan: []
        };
    }

    /**
     * 分類單個句子到適當的SOAP類別
     */
    classifyText(text) {
        if (!text || text.trim().length === 0) {
            return this.classification;
        }

        // 按句號、句號、感嘆號分割
        const sentences = text.split(/[。.！!？?\n]/);

        for (const sentence of sentences) {
            const trimmed = sentence.trim();
            if (!trimmed) continue;

            const category = this.classifysentence(trimmed);

            if (!this.classification[category].includes(trimmed)) {
                this.classification[category].push(trimmed);
            }
        }

        return this.classification;
    }

    /**
     * 分類單個句子 - 返回類別名稱
     */
    classifysentence(sentence) {
        let scores = {
            subjective: 0,
            objective: 0,
            assessment: 0,
            plan: 0
        };

        // 逐一比較關鍵詞
        for (const [category, data] of Object.entries(this.keywords)) {
            for (const keyword of data.keywords) {
                if (sentence.includes(keyword)) {
                    scores[category] += data.weight;
                }
            }
        }

        // 返回分數最高的類別
        const maxCategory = Object.keys(scores).reduce((a, b) =>
            scores[a] > scores[b] ? a : b
        );

        return scores[maxCategory] > 0 ? maxCategory : 'subjective';
    }

    /**
     * 獲取格式化的SOAP輸出
     */
    getFormattedSOAP() {
        const parts = [];

        if (this.classification.subjective.length > 0) {
            parts.push(`🗣️ 主訴 (S)：\n${this.classification.subjective.join('\n')}`);
        }

        if (this.classification.objective.length > 0) {
            parts.push(`🔬 客觀 (O)：\n${this.classification.objective.join('\n')}`);
        }

        if (this.classification.assessment.length > 0) {
            parts.push(`🏥 評估 (A)：\n${this.classification.assessment.join('\n')}`);
        }

        if (this.classification.plan.length > 0) {
            parts.push(`💊 計劃 (P)：\n${this.classification.plan.join('\n')}`);
        }

        return parts.join('\n\n');
    }

    /**
     * 重置分類
     */
    reset() {
        this.classification = {
            subjective: [],
            objective: [],
            assessment: [],
            plan: []
        };
    }

    /**
     * 獲取原始分類結果
     */
    getClassification() {
        return this.classification;
    }

    /**
     * 添加自定義關鍵詞
     */
    addKeyword(category, keyword, weight = 1.0) {
        if (!this.keywords[category]) {
            console.warn(`類別 ${category} 不存在`);
            return false;
        }
        this.keywords[category].keywords.push(keyword);
        return true;
    }

    /**
     * 移除關鍵詞
     */
    removeKeyword(category, keyword) {
        if (!this.keywords[category]) {
            return false;
        }
        const index = this.keywords[category].keywords.indexOf(keyword);
        if (index > -1) {
            this.keywords[category].keywords.splice(index, 1);
            return true;
        }
        return false;
    }

    /**
     * 獲取統計信息
     */
    getStatistics() {
        return {
            totalSentences: Object.values(this.classification).reduce((sum, arr) => sum + arr.length, 0),
            subjectiveCount: this.classification.subjective.length,
            objectiveCount: this.classification.objective.length,
            assessmentCount: this.classification.assessment.length,
            planCount: this.classification.plan.length
        };
    }
}

// ============================================================================
// 使用示例和集成
// ============================================================================

/**
 * 集成到 Voice Recording 的函數
 * 可在voice-recording-core.js中調用此函數
 */
function classifyTranscriptionToSOAP(transcriptionText) {
    const classifier = new SOAPClassifier();
    classifier.classifyText(transcriptionText);

    return {
        formatted: classifier.getFormattedSOAP(),
        raw: classifier.getClassification(),
        stats: classifier.getStatistics()
    };
}

/**
 * 示例使用
 */
const exampleText = `
患者主訴頭痛、發燒、喉嚨痛已3天。
昨晚體溫39.5度，心跳90次/分，血壓140/90。
白血球計數12000，胸部X光顯示肺部浸潤。
初步診斷為社區取得性肺炎。
開立抗生素，建議服用3天後回診複查。
飲食清淡，充足水分補充，居家觀察。
`;

function demonstrateClassifier() {
    console.log('=== SOAP 自動分類演示 ===\n');

    const result = classifyTranscriptionToSOAP(exampleText);

    console.log('格式化SOAP輸出：');
    console.log(result.formatted);
    console.log('\n原始分類：');
    console.log(JSON.stringify(result.raw, null, 2));
    console.log('\n統計信息：');
    console.log(result.stats);
}

// ============================================================================
// 導出
// ============================================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        SOAPKeywords,
        SOAPClassifier,
        classifyTranscriptionToSOAP,
        demonstrateClassifier
    };
}

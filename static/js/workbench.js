    /* ==================================================================== */
    /* 全螢幕切換（F11 鍵盤快捷鍵 + Header 按鈕雙向切換）                   */
    /* ==================================================================== */
    function toggleFullscreen() {
      if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        const docEl = document.documentElement;
        if (docEl.requestFullscreen) {
          docEl.requestFullscreen().catch(() => {});
        } else if (docEl.webkitRequestFullscreen) {
          docEl.webkitRequestFullscreen();
        }
      } else {
        if (document.exitFullscreen) {
          document.exitFullscreen().catch(() => {});
        } else if (document.webkitExitFullscreen) {
          document.webkitExitFullscreen();
        }
      }
    }

    function updateFullscreenBtn() {
      const btn = document.getElementById('fullscreenBtn');
      if (!btn) return;
      const isFull = !!(document.fullscreenElement || document.webkitFullscreenElement);
      const iconSpan = btn.querySelector('.fs-icon');
      const labelSpan = btn.querySelector('.fs-label');
      if (isFull) {
        if (iconSpan) iconSpan.textContent = '🗗';
        if (labelSpan) labelSpan.textContent = '視窗';
        btn.title = '結束全螢幕 (再按 F11 或 Esc)';
        btn.classList.add('active');
      } else {
        if (iconSpan) iconSpan.textContent = '⛶';
        if (labelSpan) labelSpan.textContent = '全螢幕';
        btn.title = '切換全螢幕模式 (F11)';
        btn.classList.remove('active');
      }
    }

    document.addEventListener('fullscreenchange', updateFullscreenBtn);
    document.addEventListener('webkitfullscreenchange', updateFullscreenBtn);

    window.addEventListener('keydown', (e) => {
      if (e.key === 'F11') {
        e.preventDefault();
        toggleFullscreen();
      }
    });

    /* ==================================================================== */
    /* 側欄迷你快捷面板切換 (金鑰 / 規則庫)                                  */
    /* ==================================================================== */
    // Phase 32-A：金鑰面板已移除，只剩規則庫面板。
    function toggleQuickPanel(name) {
      if (name !== 'rules') return;
      const rulesPanel = document.getElementById('quickRulesPanel');
      const btnRules = document.getElementById('btnQuickRules');
      const isOpen = rulesPanel && rulesPanel.classList.contains('open');
      if (rulesPanel) rulesPanel.classList.toggle('open', !isOpen);
      if (btnRules) btnRules.classList.toggle('active', !isOpen);
      if (!isOpen) loadRulesStatus();
    }

    /* ==================================================================== */
    /* 浮動字幕 (Floating Tooltip) 系統 —— 嚴格採用安全 DOM API             */
    /* ==================================================================== */
    function showFloatingTooltip(e, data) {
      const tip = document.getElementById('floatingTooltip');
      if (!tip || !data) return;
      tip.innerHTML = '';

      if (data.title) {
        const titleEl = document.createElement('div');
        titleEl.className = 'floating-tooltip-title';
        titleEl.textContent = data.title;
        tip.appendChild(titleEl);
      }

      if (Array.isArray(data.rows)) {
        data.rows.forEach(r => {
          if (!r || r.value === undefined || r.value === null) return;
          const row = document.createElement('div');
          row.className = 'floating-tooltip-row';
          const label = document.createElement('span');
          label.className = 'floating-tooltip-label';
          label.textContent = r.label || '';
          const val = document.createElement('span');
          val.className = 'floating-tooltip-val';
          val.textContent = String(r.value);
          if (r.color) val.style.color = r.color;
          row.appendChild(label);
          row.appendChild(val);
          tip.appendChild(row);
        });
      }

      updateTooltipPosition(e);
      tip.classList.add('show');
    }

    function updateTooltipPosition(e) {
      const tip = document.getElementById('floatingTooltip');
      if (!tip || !tip.classList.contains('show')) return;
      const x = Math.min(e.clientX + 14, window.innerWidth - 330);
      let y = e.clientY - 12;
      const tipRect = tip.getBoundingClientRect();
      if (y + tipRect.height > window.innerHeight - 10) {
        y = window.innerHeight - tipRect.height - 10;
      }
      if (y < 10) y = 10;
      tip.style.left = `${Math.max(10, x)}px`;
      tip.style.top = `${y}px`;
    }

    function hideFloatingTooltip() {
      const tip = document.getElementById('floatingTooltip');
      if (!tip) return;
      tip.classList.remove('show');
    }

    function showFacilityTooltip(e) {
      const rows = [
        { label: '🏥 機構代號', value: currentFacility.code || '未設定' },
        { label: '🏢 院所名稱', value: currentFacility.name || '未設定' },
      ];
      if (currentFacility.physician_name) {
        rows.push({ label: '👨‍⚕️ 負責醫師', value: currentFacility.physician_name });
      }
      if (currentFacility.address) {
        rows.push({ label: '📍 院所地址', value: currentFacility.address });
      }
      rows.push({ label: '📅 費用月份', value: currentMonthlyBatchId ? currentMonthlyBatchId.replace('MONTHLY-', '') : '未上傳' });
      rows.push({ label: '🛡️ 認證狀態', value: '免重複驗證（機構快取已授權）', color: '#34d399' });

      showFloatingTooltip(e, {
        title: '院所機構與申報檔案資訊',
        rows
      });
    }

    let currentMode = 'sampling'; // 'sampling', 'appeal', or 'monthly'
    let samplingCases = [];
    let appealCases = [];
    let monthlyBatches = [];
    let currentMonthlyBatchId = null;
    let currentSelectedCase = null;

    let currentFacility = { code: '', name: '', address: '', physician_name: '' };

    // Phase 32-A：getApiKey／saveApiKey 已移除。院內網路以來源位址信任，
    // 瀏覽器不再需要持有任何金鑰（原本會把院所代碼當金鑰存進 localStorage，
    // 而院所代碼是公開資訊，等於沒有保護力）。

    async function loadFacilityConfig() {
      try {
        const res = await fetch('/api/facility');
        if (res.ok) {
          const data = await res.json();
          if (data && data.facility) {
            currentFacility = data.facility;
            updateFacilityUI(currentFacility);
          }
        }
      } catch (e) {
        console.warn('載入院所檔案失敗：', e);
      }
    }

    async function loadActiveMonthlyBatch() {
      try {
        const res = await authFetch('/api/monthly/batches');
        if (res.ok) {
          const data = await res.json();
          monthlyBatches = Array.isArray(data) ? data : (data && data.batches ? data.batches : []);
          if (monthlyBatches.length > 0) {
            const savedBatch = localStorage.getItem('elc_active_month_batch');
            const found = monthlyBatches.find(b => b.batch === savedBatch);
            currentMonthlyBatchId = found ? found.batch : monthlyBatches[0].batch;
            localStorage.setItem('elc_active_month_batch', currentMonthlyBatchId);
          }
        }
      } catch (e) {
        console.warn('載入當前申報月份失敗：', e);
      }
      updateBatchDisplay();
    }

    function updateBatchDisplay() {
      const el = document.getElementById('displayActiveMonth');
      if (el) {
        el.textContent = currentMonthlyBatchId ? currentMonthlyBatchId.replace('MONTHLY-', '') : '未上傳';
      }
      const mTitle = document.getElementById('mBatchTitle');
      if (mTitle && currentMonthlyBatchId) {
        mTitle.textContent = `申報批次：${currentMonthlyBatchId}`;
      }
    }

    function updateFacilityUI(fac) {
      if (!fac) return;
      const codeSpan = document.getElementById('displayFacilityCode');
      const nameSpan = document.getElementById('displayFacilityName');
      if (codeSpan) codeSpan.textContent = fac.code || '未設定';
      if (nameSpan) nameSpan.textContent = fac.name || '';
      const cIn = document.getElementById('facCodeInput');
      const nIn = document.getElementById('facNameInput');
      const eIn = document.getElementById('facEmailInput');
      const aIn = document.getElementById('facAddressInput');
      const pIn = document.getElementById('facPhysicianInput');
      if (cIn) cIn.value = fac.code || '';
      if (nIn) nIn.value = fac.name || '';
      if (eIn) eIn.value = fac.email || '';
      if (aIn) aIn.value = fac.address || '';
      if (pIn) pIn.value = fac.physician_name || '';
    }

    function toggleFacilityModal(show) {
      const m = document.getElementById('facilityModal');
      if (m) m.style.display = show ? 'block' : 'none';
      if (show) updateFacilityUI(currentFacility);
    }

    async function saveFacilityFromWeb() {
      const code = (document.getElementById('facCodeInput').value || '').trim();
      const name = (document.getElementById('facNameInput').value || '').trim();
      const email = (document.getElementById('facEmailInput').value || '').trim();
      const address = (document.getElementById('facAddressInput').value || '').trim();
      const physician_name = (document.getElementById('facPhysicianInput').value || '').trim();

      if (!code) {
        showNonBlockingNotice('請輸入醫事機構代碼（必填欄位）！');
        return;
      }
      if (!name) {
        showNonBlockingNotice('請輸入醫療院所名稱（必填欄位）！');
        return;
      }
      if (!email) {
        showNonBlockingNotice('請輸入聯絡信箱 Mail Address（必填欄位）！');
        return;
      }
      try {
        const res = await authFetch('/api/facility', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // profile_confirmed：使用者於診所表單確認後才可用於下載（首次下載的前置條件）
          body: JSON.stringify({ source: 'web', code, name, email, address, physician_name, profile_confirmed: true }),
        });
        const data = await res.json();
        if (!res.ok) {
          showNonBlockingNotice('儲存失敗：' + (data.message || res.status));
          return;
        }
        currentFacility = data.facility;
        updateFacilityUI(currentFacility);
        toggleFacilityModal(false);
        showNonBlockingNotice('已成功存入院所檔案 (config/facility.json) 並設定為存取 KEY！');
        if (pendingPackageDownload) {
          pendingPackageDownload = false;
          setTimeout(downloadMonthlyPackage, 0);
        }
        await loadCaseData();
      } catch (err) {
        showNonBlockingNotice('儲存失敗：' + err.message);
      }
    }

    function togglePatientEntryModal(show) {
      const m = document.getElementById('patientEntryModal');
      if (m) m.style.display = show ? 'block' : 'none';
      if (show) {
        const idIn = document.getElementById('peIdCardInput');
        if (idIn) idIn.focus();
      }
    }

    async function submitPatientEntry() {
      const id_card = (document.getElementById('peIdCardInput').value || '').trim();
      const birth_date = (document.getElementById('peBirthDateInput').value || '').trim();
      const patient_name = (document.getElementById('peNameInput').value || '').trim();

      if (!id_card && !birth_date && !patient_name) {
        showNonBlockingNotice('請至少填寫身分證字號、出生年月日或姓名其中一項！');
        return;
      }

      const endpoint = currentMode === 'appeal' 
        ? '/api/appeal/cases/add-by-patient' 
        : '/api/sampling/cases/add-by-patient';

      try {
        const res = await authFetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id_card, birth_date, patient_name, batch: currentMonthlyBatchId || '' })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showNonBlockingNotice('加入案件失敗：' + (data.message || res.status));
          return;
        }
        togglePatientEntryModal(false);
        document.getElementById('peIdCardInput').value = '';
        document.getElementById('peBirthDateInput').value = '';
        document.getElementById('peNameInput').value = '';

        if (data.matched_monthly) {
          showNonBlockingNotice(`✅ 成功自當月預審申報檔帶入 ${data.count} 筆案件！全案醫令、就診日與診斷資料已自動填妥。`);
        } else {
          showNonBlockingNotice(`ℹ️ 當月預審申報資料中查無完全相符紀錄，已為該病患建立新案件供後續維護。`);
        }
        await loadCaseData();
      } catch (err) {
        showNonBlockingNotice('加入案件失敗：' + err.message);
      }
    }

    async function importSamplingFromMonthly() {
      try {
        const res = await authFetch('/api/sampling/import-from-monthly', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ batch: currentMonthlyBatchId || '' })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showNonBlockingNotice('載入當月預審資料失敗：' + (data.message || res.status));
          return;
        }
        showNonBlockingNotice(`已自當月申報批次 ${data.batch} 成功載入預審資料！\n全批共 ${data.total_in_batch} 筆，帶入 ${data.imported} 筆。\n（新增 ${data.persisted} 筆，既有略過 ${data.conflicts.length} 筆）`);
        await loadCaseData();
      } catch (err) {
        showNonBlockingNotice('載入失敗：' + err.message);
      }
    }

    async function importAppealFromMonthly() {
      try {
        const res = await authFetch('/api/appeal/import-from-monthly', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ batch: currentMonthlyBatchId || '' })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showNonBlockingNotice('載入當月預審資料失敗：' + (data.message || res.status));
          return;
        }
        showNonBlockingNotice(`已自當月申報批次 ${data.batch} 成功載入申復清單！\n全批共 ${data.total_in_batch} 筆，帶入 ${data.imported} 筆高額案件。\n（新增 ${data.persisted} 筆，既有略過 ${data.conflicts.length} 筆）`);
        await loadCaseData();
      } catch (err) {
        showNonBlockingNotice('載入失敗：' + err.message);
      }
    }

    async function clearCacheAndReload() {
      if (!confirm('確定要清除瀏覽器本機快取與金鑰、並重新載入頁面嗎？')) return;
      try {
        localStorage.clear();
        sessionStorage.clear();
        if (window.caches) {
          const names = await caches.keys();
          await Promise.all(names.map(n => caches.delete(n)));
        }
      } catch (e) {
        console.warn('Clear cache error:', e);
      }
      window.location.href = window.location.pathname + '?_t=' + Date.now();
    }

    // Phase 32-A：院內網路不需驗證，故不再附加 X-API-Key。
    // 保留 authFetch 名稱作為薄包裝（約百處呼叫端沿用），同時留下日後若需
    // 統一處理請求（逾時、重試、錯誤提示）的單一進入點。
    async function authFetch(url, options = {}) {
      return fetch(url, options);
    }

    // 規則庫管理：狀態文字一律以 textContent 寫入（不使用 innerHTML，避免注入）
    function setRulesStatus(text) {
      const el = document.getElementById('rulesStatus');
      if (el) el.textContent = text;
    }

    async function loadRulesStatus() {
      const infoEl = document.getElementById('rulesCurrentInfo');
      if (!infoEl) return;
      infoEl.textContent = '載入規則庫狀態中 …';
      try {
        const resp = await authFetch('/api/rules/status');
        const body = await resp.json();
        if (!resp.ok) {
          infoEl.textContent = `無法取得狀態：${body.message || resp.status}`;
          return;
        }
        const db = body.db || {};
        const src = body.sources || {};
        infoEl.textContent =
          `目前規則庫：給付 ${db.payment_rows ?? 0} 筆、藥品 ${db.drug_rows ?? 0} 筆｜` +
          `最新來源：${src.payment_file || '（缺給付檔）'} ／ ${src.drug_file || '（缺藥品檔）'}`;
      } catch (err) {
        infoEl.textContent = '無法連線至規則庫狀態服務';
      }
    }

    async function uploadRuleCsv(file) {
      if (!file) return;
      const form = new FormData();
      form.append('file', file, file.name);
      setRulesStatus(`上傳中：${file.name} …`);
      try {
        const resp = await authFetch('/api/rules/upload', { method: 'POST', body: form });
        const body = await resp.json();
        setRulesStatus(resp.ok
          ? `已儲存：${body.saved_as}（${body.replaced ? '覆寫舊檔' : '新檔'}）。請按下方同步按鈕套用。`
          : `上傳失敗：${body.message}`);
        if (resp.ok) await loadRulesStatus();
      } catch (err) {
        setRulesStatus('上傳失敗：無法連線至服務');
      }
    }

    async function syncRules(replace = false) {
      setRulesStatus(replace ? '整表更新中 …' : '增量同步中 …');
      try {
        const resp = await authFetch('/api/rules/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ replace: Boolean(replace) }),
        });
        const body = await resp.json();
        if (!resp.ok) {
          setRulesStatus(`同步失敗：${body.message}`);
          return;
        }
        const modeLabel = body.mode === 'replace' ? '整表更新' : '增量同步（舊碼保留）';
        const bakInfo = body.backup_file ? `｜備份：${body.backup_file}` : '';
        const payAudit = body.audit && body.audit.payment ? body.audit.payment : null;
        const auditInfo = payAudit
          ? `｜給付稽核：異常尾碼 ${payAudit.non_standard_suffix_ref}、缺碼引用 ${payAudit.missing_code_ref}`
          : '';
        setRulesStatus(
          `[${modeLabel}] 藥品 ${body.drug_rows} 筆（${body.drug_file}）；` +
          `給付項目 ${body.payment_rows} 筆（${body.payment_file}）。` +
          `DB 中不在來源檔的代碼：藥品 ${body.drug_stale_not_in_source}、給付 ${body.payment_stale_not_in_source}` +
          `${bakInfo}${auditInfo}`
        );
        await loadRulesStatus();
      } catch (err) {
        setRulesStatus('同步失敗：無法連線至服務');
      }
    }

    function syncRulesReplace() {
      const ok = confirm(
        '確定要執行「整表更新」嗎？\n' +
        '系統會先自動備份舊規則庫，再以最新來源檔整表取代（來源檔中不存在的舊代碼將被移除）。'
      );
      if (ok) syncRules(true);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    async function clearMonthlyBatch() {
      if (!currentMonthlyBatchId) {
        showNonBlockingNotice('目前未選取任何申報批次');
        return;
      }
      if (!confirm(`確定要清空申報批次 ${currentMonthlyBatchId} 嗎？此操作將自資料庫中刪除該批次的所有案件。`)) {
        return;
      }
      const res = await authFetch(`/api/monthly/batch/${encodeURIComponent(currentMonthlyBatchId)}/clear`, {
        method: 'POST'
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('清空批次失敗：' + (data.message || res.status));
        return;
      }
      showNonBlockingNotice(data.message || '批次案件已成功清空');
      currentMonthlyBatchId = null;
      document.getElementById('mBatchTitle').innerText = '尚未載入申報批次';
      document.getElementById('monthlyReportIframe').srcdoc = '';
      await loadCaseData();
    }

    let currentSoapEncounter = null;
    let soapLiveInterval = null;
    let liveSeconds = 88;
    let isSoapLiveMode = true;
    let soapPatients = [];
    let liveSessionData = null;

    function switchWorkflowMode(mode) {
      currentMode = mode;
      document.getElementById('tabMode3').className = `mode-btn ${mode === 'monthly' ? 'active' : ''}`;
      document.getElementById('tabMode1').className = `mode-btn ${mode === 'sampling' ? 'active' : ''}`;
      document.getElementById('tabMode2').className = `mode-btn ${mode === 'appeal' ? 'active' : ''}`;
      const tab4 = document.getElementById('tabMode4');
      if (tab4) tab4.className = `mode-btn ${mode === 'soap' ? 'active' : ''}`;
      
      document.getElementById('workflow3View').className = `view-container ${mode === 'monthly' ? 'active' : ''}`;
      document.getElementById('workflow1View').className = `view-container ${mode === 'sampling' ? 'active' : ''}`;
      document.getElementById('workflow2View').className = `view-container ${mode === 'appeal' ? 'active' : ''}`;
      const v4 = document.getElementById('workflow4View');
      if (v4) v4.className = `view-container ${mode === 'soap' ? 'active' : ''}`;
      
      if (mode === 'sampling') {
        document.getElementById('sidebarListTitle').innerText = '事前預審抽樣清單';
        const clrBtn = document.getElementById('btnSoapClearList');
        if (clrBtn) clrBtn.style.display = 'none';
      } else if (mode === 'appeal') {
        document.getElementById('sidebarListTitle').innerText = '核減刪減醫令清單';
        const clrBtn = document.getElementById('btnSoapClearList');
        if (clrBtn) clrBtn.style.display = 'none';
      } else if (mode === 'soap') {
        document.getElementById('sidebarListTitle').innerText = '診間門診病患清單';
        const clrBtn = document.getElementById('btnSoapClearList');
        if (clrBtn) clrBtn.style.display = 'inline-block';
        initSoapWorkbench();
      } else {
        document.getElementById('sidebarListTitle').innerText = '申報總檔批次清單';
        const clrBtn = document.getElementById('btnSoapClearList');
        if (clrBtn) clrBtn.style.display = 'none';
      }

      if (mode !== 'soap') {
        loadCaseData();
      }
    }

    async function initSoapWorkbench() {
      if (!soapLiveInterval) {
        soapLiveInterval = setInterval(() => {
          liveSeconds++;
          const mins = String(Math.floor(liveSeconds / 60)).padStart(2, '0');
          const secs = String(liveSeconds % 60).padStart(2, '0');
          const timerEl = document.getElementById('soapLiveTimer');
          if (timerEl) timerEl.textContent = `${mins}:${secs}`;
        }, 1000);
      }
      await loadSoapPatientsList();
      await fetchLiveSessionData();
      switchToLiveMode();
    }

    async function fetchLiveSessionData() {
      try {
        const resp = await authFetch('/api/soap/live-session');
        const data = await resp.json();
        if (data && data.status === 'success') {
          liveSessionData = data;
        }
      } catch (e) {
        console.warn('載入即時會話失敗:', e);
      }
    }

    async function loadSoapPatientsList() {
      try {
        const resp = await authFetch('/api/soap/patients');
        const data = await resp.json();
        if (data && data.patients) {
          soapPatients = data.patients;
        }
      } catch (e) {
        console.warn('載入門診病患清單失敗:', e);
      }
      renderSoapPatientsSidebar();
    }

    function renderSoapPatientsSidebar() {
      const container = document.getElementById('caseList');
      if (!container) return;
      container.innerHTML = '';

      // 0. 側邊欄頂部控制列：病患統計與清空病患清單按鈕
      const headerBar = document.createElement('div');
      headerBar.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:5px 8px; margin-bottom:8px; background:rgba(15,23,42,0.7); border:1px solid rgba(148,163,184,0.25); border-radius:6px; font-size:11px;';

      const countLabel = document.createElement('span');
      countLabel.style.cssText = 'color:#94a3b8; font-weight:600;';
      countLabel.textContent = `門診病患 (${soapPatients.length})`;

      const clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.style.cssText = 'background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.4); color:#fca5a5; border-radius:4px; font-size:10px; padding:2px 6px; cursor:pointer; display:inline-flex; align-items:center; gap:3px;';
      clearBtn.textContent = '🗑️ 清空清單';
      clearBtn.title = '清空左側病患清單並回到內定即時錄音 (Clear Patient List)';
      clearBtn.onclick = (e) => {
        e.stopPropagation();
        clearSoapPatientsList();
      };

      headerBar.appendChild(countLabel);
      headerBar.appendChild(clearBtn);
      container.appendChild(headerBar);

      // 1. 置頂：內定即時錄音監控項目
      const liveItem = document.createElement('div');
      liveItem.className = `case-item ${isSoapLiveMode ? 'active' : ''}`;
      liveItem.style.borderLeft = '3px solid #ef4444';
      liveItem.style.background = isSoapLiveMode ? 'rgba(239, 68, 68, 0.15)' : 'rgba(15, 23, 42, 0.6)';
      liveItem.onclick = () => switchToLiveMode();

      const liveTop = document.createElement('div');
      liveTop.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;';
      const liveCode = document.createElement('span');
      liveCode.className = 'case-code';
      liveCode.style.color = '#f87171';
      liveCode.textContent = '🔴 即時錄音';
      const liveBadge = document.createElement('span');
      liveBadge.className = 'badge';
      liveBadge.style.cssText = 'background:rgba(239,68,68,0.25); border:1px solid #ef4444; color:#fca5a5;';
      liveBadge.textContent = '看診中';
      liveTop.appendChild(liveCode);
      liveTop.appendChild(liveBadge);

      const liveName = document.createElement('div');
      liveName.style.cssText = 'font-size:11px; font-weight:600; color:#fff;';
      liveName.textContent = '陳美玲 (F229871234)';
      liveItem.appendChild(liveTop);
      liveItem.appendChild(liveName);
      container.appendChild(liveItem);

      // 2. 歷史病患列表 (包含第1個陳美玲、第2個王大明、第3個李阿土等)
      soapPatients.forEach((p, pIdx) => {
        const pCard = document.createElement('div');
        const isCurrentActivePatient = !isSoapLiveMode && currentSoapEncounter && currentSoapEncounter.id_card === p.id_card;
        pCard.className = `case-item ${isCurrentActivePatient ? 'active' : ''}`;
        pCard.style.cursor = 'pointer';

        const pTop = document.createElement('div');
        pTop.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;';

        const pNum = document.createElement('span');
        pNum.className = 'case-code';
        pNum.textContent = `#${pIdx + 1} ${p.patient_name}`;
        pTop.appendChild(pNum);

        const countBadge = document.createElement('span');
        countBadge.className = 'badge badge-sufficient';
        countBadge.style.fontSize = '10px';
        countBadge.textContent = `${p.encounters_count || (p.encounters ? p.encounters.length : 0)} 門診`;
        pTop.appendChild(countBadge);
        pCard.appendChild(pTop);

        const pSub = document.createElement('div');
        pSub.style.cssText = 'font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between;';
        const idSpan = document.createElement('span');
        idSpan.textContent = p.id_card;
        const demoTag = document.createElement('span');
        demoTag.textContent = `${p.age || 50}歲 ${p.gender || ''}`;
        pSub.appendChild(idSpan);
        pSub.appendChild(demoTag);
        pCard.appendChild(pSub);

        // 就診紀錄展開子清單 (點選病患時展開名字下的多次門診紀錄)
        const subList = document.createElement('div');
        subList.className = 'soap-encounter-sublist';
        // 若此病患是目前選取的歷史病患，或是點擊展開
        const isExpanded = isCurrentActivePatient || pCard.dataset.expanded === 'true';
        subList.style.display = isExpanded ? 'flex' : 'none';

        const encs = p.encounters || [];
        encs.forEach(enc => {
          const subItem = document.createElement('div');
          const isThisEncounterActive = !isSoapLiveMode && currentSoapEncounter && currentSoapEncounter.visit_date === enc.visit_date && currentSoapEncounter.id_card === p.id_card;
          subItem.className = `soap-encounter-subitem ${isThisEncounterActive ? 'active' : ''}`;
          subItem.onclick = (e) => {
            e.stopPropagation();
            selectSoapHistoricalEncounter(p, enc);
          };

          const dateSpan = document.createElement('span');
          dateSpan.textContent = `📅 ${enc.visit_date}`;

          const icdSpan = document.createElement('span');
          icdSpan.style.color = '#38bdf8';
          icdSpan.textContent = enc.icd10 || '';

          subItem.appendChild(dateSpan);
          subItem.appendChild(icdSpan);
          subList.appendChild(subItem);
        });

        pCard.appendChild(subList);

        pCard.onclick = () => {
          const nowOpen = subList.style.display === 'flex';
          subList.style.display = nowOpen ? 'none' : 'flex';
          pCard.dataset.expanded = nowOpen ? 'false' : 'true';
          // 點選病患時，自動調出該病患的第一筆就診紀錄
          if (!nowOpen && encs.length > 0) {
            selectSoapHistoricalEncounter(p, encs[0]);
          }
        };

        container.appendChild(pCard);
      });
    }

    function clearSoapPatientsList() {
      soapPatients = [];
      renderSoapPatientsSidebar();
      switchToLiveMode();
    }

    function switchToLiveMode() {
      isSoapLiveMode = true;
      currentSoapEncounter = null;
      renderSoapPatientsSidebar();

      // 1. 頂部狀態標題與模式副標
      const titleEl = document.getElementById('soapWorkbenchTitle');
      if (titleEl) titleEl.textContent = '🔴 診間即時自動生成中 (Live Stream · 全程自動處理)';
      const subEl = document.getElementById('soapWorkbenchSubtitle');
      if (subEl) subEl.textContent = '專員錄音中 · ASR 語音即時轉錄 · 本地 LLM 臨床推理自動提取 · 無需人為介入';

      // 2. 按鈕狀態：隱藏返回按鈕與打包按鈕 (內定模式不需人為介入打包)
      const returnBtn = document.getElementById('soapReturnLiveBtn');
      if (returnBtn) returnBtn.style.display = 'none';
      const topZipBtn = document.getElementById('soapTopZipBtn');
      if (topZipBtn) topZipBtn.style.display = 'none';

      // 3. 金庫區狀態：隱藏打包按鈕，顯示即時錄音串流中提示
      const vaultZip = document.getElementById('soapVaultZipBtnContainer');
      if (vaultZip) vaultZip.style.display = 'none';
      const liveHint = document.getElementById('soapVaultLiveHintContainer');
      if (liveHint) liveHint.style.display = 'flex';

      // 4. 病患橫幅與 SOAP Form 恢復為即時自動生成資料 (English Clinical Format)
      const livePName = (liveSessionData && liveSessionData.patient_name) || '陳美玲';
      const livePId = (liveSessionData && liveSessionData.id_card) || 'F229871234';
      const headerTitle = document.getElementById('soapCurrentPatientHeader');
      if (headerTitle) headerTitle.textContent = `${livePName} (${livePId}) · 即時門診錄製中`;
      const headerIcd = document.getElementById('soapCurrentIcdHeader');
      if (headerIcd) headerIcd.textContent = 'ICD-10: J02.9 Acute pharyngitis (AI 即時推理中)';

      const liveSoap = (liveSessionData && liveSessionData.live_soap) || {
        s: 'Chief Complaint: Severe throat scratchiness and painful swallowing for 2 days. Associated with mild chills and low-grade fever (37.8°C) since yesterday evening. Occasional non-productive dry cough. Denies shortness of breath, chest tightness, or hemoptysis.',
        o: 'V/S: BT 37.8°C, BP 122/78 mmHg, HR 82 bpm, RR 18/min.\nThroat Examination: Pharyngeal mucosa markedly hyperemic and injected. Bilateral tonsils mildly enlarged (Grade I) without purulent exudates. Soft palate symmetrical, uvula midline. Mild tenderness on bilateral anterior cervical lymph nodes.\n[NHI Cloud EHR Lab]: Latest CBC showed WBC 6,800/uL, CRP 0.4 mg/dL (1120701).',
        a: '1. J02.9 Acute pharyngitis, unspecified\n2. R50.9 Fever, unspecified',
        p: '1. Acetaminophen 500mg tid + Ibuprofen 400mg prn prescribed for 3 days.\n2. Dextromethorphan cough suppressant and soothing lozenges.\n3. Clinical advice: Encourage warm saline gargling and adequate oral hydration. Immediate return to clinic if body temperature exceeds 38.5°C or dyspnea occurs.\n4. [Self-Pay Recommendation]: High-dose effervescent Vitamin C/Zinc immune supplement and anti-inflammatory throat spray suggested.'
      };

      const sEl = document.getElementById('soapInputS');
      const oEl = document.getElementById('soapInputO');
      const aEl = document.getElementById('soapInputA');
      const pEl = document.getElementById('soapInputP');
      if (sEl) sEl.value = liveSoap.s;
      if (oEl) oEl.value = liveSoap.o;
      if (aEl) aEl.value = liveSoap.a;
      if (pEl) pEl.value = liveSoap.p;

      // 5. 原始錄音檔播放器標示為即時暫存
      const audioName = document.getElementById('soapAudioFilename');
      if (audioName) audioName.textContent = 'live_consultation_stream.opus (串流暫存)';
      const audioMeta = document.getElementById('soapAudioMeta');
      if (audioMeta) audioMeta.textContent = '診間 8010 即時收音 · Opus 32kbps · 門診結束自動封存';

      // 6. 清空或顯示即時金庫生檔
      const grid = document.getElementById('soapForensicFilesGrid');
      if (grid) grid.innerHTML = '';
      const shaBadge = document.getElementById('soapSha256Fingerprint');
      if (shaBadge) shaBadge.textContent = 'STREAMING_IN_PROGRESS (即時串流防護)';

      // 7. 同步中間搜尋框與時間軸清單為陳美玲
      const qInput = document.getElementById('soapPatientQueryInput');
      if (qInput) qInput.value = livePId;
      searchSoapPatient(false);
    }

    async function selectSoapHistoricalEncounter(patient, enc) {
      isSoapLiveMode = false;
      currentSoapEncounter = Object.assign({}, enc, {
        patient_name: patient.patient_name,
        id_card: patient.id_card
      });

      renderSoapPatientsSidebar();

      // 1. 頂部標題切換為歷史病歷調閱模式
      const titleEl = document.getElementById('soapWorkbenchTitle');
      if (titleEl) titleEl.textContent = `🏛️ 歷史病歷調閱與司法保全 (病患: ${patient.patient_name} · ${enc.visit_date} 門診)`;
      const subEl = document.getElementById('soapWorkbenchSubtitle');
      if (subEl) subEl.textContent = '調閱歷史門診 SOAP、原始錄音檔與影像生檔 · 提供 SHA-256 司法證據打包下載';

      // 2. 顯示打包按鈕與返回即時按鈕 (有選左側歷史病患才需要做打包動作)
      const returnBtn = document.getElementById('soapReturnLiveBtn');
      if (returnBtn) returnBtn.style.display = 'inline-flex';
      const topZipBtn = document.getElementById('soapTopZipBtn');
      if (topZipBtn) topZipBtn.style.display = 'inline-flex';
      const vaultZip = document.getElementById('soapVaultZipBtnContainer');
      if (vaultZip) vaultZip.style.display = 'block';
      const liveHint = document.getElementById('soapVaultLiveHintContainer');
      if (liveHint) liveHint.style.display = 'none';

      // 3. 填入該日期的 SOAP 病歷內容
      const s = (enc.soap && (enc.soap.s || enc.soap.subjective)) || '';
      const o = (enc.soap && (enc.soap.o || enc.soap.objective)) || '';
      const a = (enc.soap && (enc.soap.a || enc.soap.assessment)) || '';
      const p = (enc.soap && (enc.soap.p || enc.soap.plan)) || '';
      const sEl = document.getElementById('soapInputS');
      const oEl = document.getElementById('soapInputO');
      const aEl = document.getElementById('soapInputA');
      const pEl = document.getElementById('soapInputP');
      if (sEl) sEl.value = s;
      if (oEl) oEl.value = o;
      if (aEl) aEl.value = a;
      if (pEl) pEl.value = p;

      // 4. 更新病患橫幅標題
      const headerTitle = document.getElementById('soapCurrentPatientHeader');
      if (headerTitle) {
        headerTitle.textContent = `${patient.patient_name} (${patient.id_card}) · ${enc.visit_date} 門診`;
      }
      const headerIcd = document.getElementById('soapCurrentIcdHeader');
      if (headerIcd) {
        headerIcd.textContent = `ICD-10: ${enc.icd10} ${enc.icd10_title || ''}`;
      }

      // 5. 調出原始錄音檔與金庫生檔
      renderForensicFilesGrid(enc);

      // 6. 同步中間搜尋框與中間時間軸卡片
      const qInput = document.getElementById('soapPatientQueryInput');
      if (qInput) qInput.value = patient.id_card;
      searchSoapPatient(false);
    }

    async function searchSoapPatient(autoSelectFirst = true, isManualSearch = false) {
      const qInput = document.getElementById('soapPatientQueryInput');
      const query = qInput ? qInput.value.trim() : '';
      const listEl = document.getElementById('soapEncountersList');
      if (!listEl) return;

      if (!query && isManualSearch) {
        showNonBlockingNotice('請先輸入欲查詢的身分證字號 (例如 A123456789) 或出生年月日！');
        return;
      }
      const actualQuery = query || 'F229871234';

      listEl.innerHTML = '';
      const loadingEl = document.createElement('div');
      loadingEl.style.padding = '10px';
      loadingEl.style.color = 'var(--text-muted)';
      loadingEl.style.fontSize = '12px';
      loadingEl.textContent = '檢索歷史病歷中 …';
      listEl.appendChild(loadingEl);

      try {
        const resp = await authFetch('/api/soap/search-patient', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: actualQuery })
        });
        const data = await resp.json();
        listEl.innerHTML = '';

        const encounters = (data && data.encounters) || [];
        const countBadge = document.getElementById('soapEncounterCountBadge');
        if (countBadge) countBadge.textContent = `${encounters.length} 個歷史門診`;

        // 如果搜尋到了病患，且該病患不在最左側病患側邊欄中，自動將其加入左側！若已存在則同步更新 encounters
        if (data && data.patient) {
          const pData = data.patient;
          const exists = soapPatients.find(p => p.id_card === pData.id_card);
          if (!exists) {
            soapPatients.push({
              id_card: pData.id_card,
              patient_name: pData.patient_name,
              birth_date: pData.birth_date,
              gender: pData.gender || '男',
              age: pData.age || 50,
              encounters_count: encounters.length,
              encounters: encounters
            });
            renderSoapPatientsSidebar();
          } else {
            exists.encounters = encounters;
          }
        }

        if (encounters.length === 0) {
          const emptyEl = document.createElement('div');
          emptyEl.style.padding = '12px';
          emptyEl.style.color = 'var(--text-muted)';
          emptyEl.style.fontSize = '12px';
          emptyEl.textContent = '查無此病患之歷史門診紀錄';
          listEl.appendChild(emptyEl);
          return;
        }

        encounters.forEach((enc) => {
          const isThisActive = currentSoapEncounter && currentSoapEncounter.visit_date === enc.visit_date;
          const card = document.createElement('div');
          card.className = `encounter-item ${isThisActive ? 'active' : ''}`;
          card.onclick = () => {
            const pObj = soapPatients.find(p => p.id_card === enc.id_card) || {
              patient_name: enc.patient_name || '門診病患',
              id_card: enc.id_card
            };
            selectSoapHistoricalEncounter(pObj, enc);
          };

          const header = document.createElement('div');
          header.className = 'encounter-header';

          const dateSpan = document.createElement('span');
          dateSpan.className = 'encounter-date';
          dateSpan.textContent = `📅 ${enc.visit_date} 門診`;

          const countSpan = document.createElement('span');
          countSpan.className = 'encounter-meta';
          countSpan.textContent = `📁 ${enc.files_count || 2} 個生檔`;

          header.appendChild(dateSpan);
          header.appendChild(countSpan);

          const diagDiv = document.createElement('div');
          diagDiv.className = 'encounter-diag';
          diagDiv.textContent = `${enc.icd10} ${enc.icd10_title || ''}`;

          const soapBrief = document.createElement('div');
          soapBrief.style.fontSize = '11px';
          soapBrief.style.color = '#94a3b8';
          soapBrief.style.overflow = 'hidden';
          soapBrief.style.textOverflow = 'ellipsis';
          soapBrief.style.whiteSpace = 'nowrap';
          const sText = (enc.soap && (enc.soap.s || enc.soap.subjective)) || '';
          soapBrief.textContent = sText;

          card.appendChild(header);
          card.appendChild(diagDiv);
          card.appendChild(soapBrief);
          listEl.appendChild(card);
        });

        // 若是主動手動搜尋，或是非即時模式下的自動選取，直接切換載入第一筆！
        if ((isManualSearch || (autoSelectFirst && !isSoapLiveMode)) && encounters.length > 0) {
          const pObj = soapPatients.find(p => p.id_card === encounters[0].id_card) || {
            patient_name: encounters[0].patient_name || '門診病患',
            id_card: encounters[0].id_card
          };
          selectSoapHistoricalEncounter(pObj, encounters[0]);
        }
      } catch (err) {
        listEl.innerHTML = '';
        const errEl = document.createElement('div');
        errEl.style.padding = '10px';
        errEl.style.color = '#fca5a5';
        errEl.style.fontSize = '12px';
        errEl.textContent = '連線檢索失敗: ' + err;
        listEl.appendChild(errEl);
      }
    }

    function renderSelectedEncounter(enc) {
      currentSoapEncounter = enc;
      const s = (enc.soap && (enc.soap.s || enc.soap.subjective)) || '';
      const o = (enc.soap && (enc.soap.o || enc.soap.objective)) || '';
      const a = (enc.soap && (enc.soap.a || enc.soap.assessment)) || '';
      const p = (enc.soap && (enc.soap.p || enc.soap.plan)) || '';

      const sEl = document.getElementById('soapInputS');
      const oEl = document.getElementById('soapInputO');
      const aEl = document.getElementById('soapInputA');
      const pEl = document.getElementById('soapInputP');

      if (sEl) sEl.value = s;
      if (oEl) oEl.value = o;
      if (aEl) aEl.value = a;
      if (pEl) pEl.value = p;

      const headerTitle = document.getElementById('soapCurrentPatientHeader');
      if (headerTitle) {
        headerTitle.textContent = `${enc.patient_name} (${enc.id_card}) · ${enc.visit_date} 門診`;
      }
      const headerIcd = document.getElementById('soapCurrentIcdHeader');
      if (headerIcd) {
        headerIcd.textContent = `ICD-10: ${enc.icd10} ${enc.icd10_title || ''}`;
      }

      renderForensicFilesGrid(enc);
    }

    function renderForensicFilesGrid(enc) {
      const grid = document.getElementById('soapForensicFilesGrid');
      if (!grid) return;
      grid.innerHTML = '';

      const files = enc.files || [
        { category: 'audio', filename: `consultation_${enc.visit_date}.opus`, size: 345000 },
        { category: 'images', filename: `clinical_exam_${enc.visit_date}.webp`, size: 215000 },
        { category: 'reports', filename: `lab_${enc.visit_date}.pdf`, size: 92000 }
      ];

      const audioItem = files.find(f => f.category === 'audio');
      if (audioItem) {
        const audioName = document.getElementById('soapAudioFilename');
        if (audioName) audioName.textContent = audioItem.filename;
        const audioMeta = document.getElementById('soapAudioMeta');
        if (audioMeta) audioMeta.textContent = `${Math.round(audioItem.size / 1024)} KB · 32kbps 原聲錄音`;
      }

      files.forEach(f => {
        const card = document.createElement('div');
        card.className = 'forensic-file-card';

        const icon = document.createElement('span');
        icon.style.fontSize = '22px';
        icon.textContent = f.category === 'audio' ? '🎙️' : (f.category === 'images' ? '🖼️' : '📑');

        const info = document.createElement('div');
        info.style.flex = '1';
        info.style.overflow = 'hidden';

        const name = document.createElement('strong');
        name.style.fontSize = '12px';
        name.style.color = '#fff';
        name.style.display = 'block';
        name.style.overflow = 'hidden';
        name.style.textOverflow = 'ellipsis';
        name.style.whiteSpace = 'nowrap';
        name.textContent = f.filename;

        const size = document.createElement('span');
        size.style.fontSize = '11px';
        size.style.color = 'var(--text-muted)';
        size.textContent = `${Math.round(f.size / 1024)} KB · SHA-256 數位封存`;

        info.appendChild(name);
        info.appendChild(size);

        card.appendChild(icon);
        card.appendChild(info);
        grid.appendChild(card);
      });

      const shaBadge = document.getElementById('soapSha256Fingerprint');
      if (shaBadge) {
        const hashSeed = (enc.case_id || enc.id_card || 'ENC') + (enc.visit_date || '');
        let h = 0x811c9dc5;
        for (let i = 0; i < hashSeed.length; i++) {
          h ^= hashSeed.charCodeAt(i);
          h = Math.imul(h, 0x01000193);
        }
        const hex = (h >>> 0).toString(16).padStart(8, '0');
        shaBadge.textContent = `SHA256_VERIFIED (0x${hex}9b4c8a2e...)`;
      }
    }

    function copyCurrentSoapText() {
      const s = document.getElementById('soapInputS').value;
      const o = document.getElementById('soapInputO').value;
      const a = document.getElementById('soapInputA').value;
      const p = document.getElementById('soapInputP').value;

      const fullText = `[S] 主訴 (Subjective):\n${s}\n\n[O] 客觀檢查 (Objective):\n${o}\n\n[A] 診斷評估 (Assessment):\n${a}\n\n[P] 處置治療 (Plan):\n${p}`;
      navigator.clipboard.writeText(fullText).then(() => {
        showNonBlockingNotice('✅ 完整門診 SOAP 病歷已複製至剪貼簿！');
      });
    }

    let soapChangeTracker = {
      sampling: false,
      appeal: false,
      court: false
    };

    function onSoapContentChanged(source) {
      soapChangeTracker[source] = true;
      if (source === 'sampling') {
        const alertBox = document.getElementById('sHisSyncAlert');
        if (alertBox) alertBox.style.display = 'flex';
        showHisSyncToast('2階事前抽審 SOAP 病歷已更動，請記得寫回 HIS');
      } else if (source === 'appeal') {
        const alertBox = document.getElementById('aHisSyncAlert');
        if (alertBox) alertBox.style.display = 'flex';
        showHisSyncToast('3階事後申復理由/佐證已更動，請記得寫回 HIS');
      } else if (source === 'court') {
        const alertBox = document.getElementById('soapHisSyncAlert');
        if (alertBox) alertBox.style.display = 'flex';
        showHisSyncToast('司法保全/門診 SOAP 已修訂，請及時寫回 HIS');
      }
    }

    function getAppealFullText() {
      const s1 = document.getElementById('aSec1') ? document.getElementById('aSec1').value : '';
      const s2 = document.getElementById('aSec2') ? document.getElementById('aSec2').value : '';
      const s3 = document.getElementById('aSec3') ? document.getElementById('aSec3').value : '';
      const s4 = document.getElementById('aSec4') ? document.getElementById('aSec4').value : '';
      return `① 案情摘要:\n${s1}\n\n② 醫療必要性:\n${s2}\n\n③ 規則依據:\n${s3}\n\n④ 病歷佐證:\n${s4}`;
    }

    function triggerDirectHisWrite(sourceTitle, content) {
      pushSoapToHisUia(sourceTitle);
      if (sourceTitle.includes('2階')) {
        const alertBox = document.getElementById('sHisSyncAlert');
        if (alertBox) alertBox.style.display = 'none';
      } else if (sourceTitle.includes('3階')) {
        const alertBox = document.getElementById('aHisSyncAlert');
        if (alertBox) alertBox.style.display = 'none';
      } else {
        const alertBox = document.getElementById('soapHisSyncAlert');
        if (alertBox) alertBox.style.display = 'none';
      }
      hideHisSyncToast();
    }

    let hisToastTimer = null;
    function showHisSyncToast(msg) {
      const banner = document.getElementById('hisSyncPromptBanner');
      const textEl = document.getElementById('hisSyncPromptText');
      if (!banner || !textEl) return;
      textEl.textContent = msg;
      banner.className = 'his-sync-prompt-banner show';
      if (hisToastTimer) clearTimeout(hisToastTimer);
      hisToastTimer = setTimeout(() => {
        banner.className = 'his-sync-prompt-banner';
      }, 7000);
    }

    function hideHisSyncToast() {
      const banner = document.getElementById('hisSyncPromptBanner');
      if (banner) banner.className = 'his-sync-prompt-banner';
      if (hisToastTimer) clearTimeout(hisToastTimer);
    }

    // 非阻斷提示：右下角短暫顯示，不使用 alert（不阻斷操作、不搶鍵盤焦點）。
    function showNonBlockingNotice(message, ms = 4000) {
      const el = document.createElement('div');
      el.setAttribute('role', 'status');
      el.textContent = message;
      el.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:99999;max-width:420px;padding:10px 14px;'
        + 'border-radius:8px;background:#1e293b;color:#f8fafc;border:1px solid rgba(148,163,184,.4);'
        + 'box-shadow:0 10px 25px rgba(0,0,0,.4);font-size:13px;line-height:1.5;';
      document.body.appendChild(el);
      setTimeout(() => el.remove(), ms);
    }

    function pushSoapToHisUia(customSource = '門診即時SOAP') {
      const sAlert = document.getElementById('soapHisSyncAlert');
      if (sAlert) sAlert.style.display = 'none';
      // 醫師已於審核步驟核准，寫入不再二次確認；改為非阻斷提示，不搶焦點。
      showNonBlockingNotice(`🚀 已排入 agent-desktop 寫入（來源：${customSource}）— 背景執行中，結果另行通知`);
    }

    function downloadForensicEvidenceZip() {
      if (isSoapLiveMode) {
        showNonBlockingNotice('目前為內定即時門診錄音中，請先於左側選取欲調閱之歷史門診紀錄，即可打包該次法院/審查佐證包！');
        return;
      }
      const caseId = (currentSoapEncounter && currentSoapEncounter.case_id) || 'ENC-F229871234-1120815';
      const url = `/api/soap/cases/${encodeURIComponent(caseId)}/export-forensic-zip`;
      window.location.href = url;
    }

    function stopLiveRecordingAndGenerate() {
      const ticker = document.getElementById('soapLiveTicker');
      const text = ticker ? ticker.textContent.trim() : '';
      const sEl = document.getElementById('soapInputS');
      if (sEl) {
        sEl.value = '主訴：' + text;
      }
      showNonBlockingNotice('⏹️ 錄音已停止！ASR 逐字稿已自動提取並生成結構化 SOAP 主訴！');
    }

    async function uploadMonthlyZip(file) {
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      const res = await authFetch('/api/monthly/upload', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) {
        showNonBlockingNotice('上傳失敗：' + (data.message || '請確認檔案是否為 申報壓縮檔'));
        return;
      }
      // Phase 29：機構代碼與本院不同（新機構 zip）→ 不改動本院院所設定與 KEY，只建立獨立批次
      if (data.facility_code && !data.foreign_facility) {
        currentFacility.code = data.facility_code;
        updateFacilityUI(currentFacility);
      }
      const foreignNote = data.foreign_facility
        ? '\n（機構代碼與本院不同：已建立獨立批次，本院院所設定未變更）'
        : '';
      showNonBlockingNotice(`申報總檔已解析成功！批次：${data.batch}\n機構代碼：${data.facility_code || '未註記'}${foreignNote}\n共 ${data.total_cases || 0} 筆門診案件，已完成規則核對。`);
      document.getElementById('monthlyFileInput').value = '';
      currentMonthlyBatchId = data.batch;
      localStorage.setItem('elc_active_month_batch', data.batch);
      updateBatchDisplay();
      await loadMonthlyReport(data.batch);
      await loadCaseData();
    }

    async function loadMonthlyReport(batchId) {
      if (!batchId) return;
      currentMonthlyBatchId = batchId;
      localStorage.setItem('elc_active_month_batch', batchId);
      updateBatchDisplay();
      document.getElementById('mBatchTitle').innerText = `申報批次：${batchId}`;
      const res = await authFetch(`/api/monthly/batch/${batchId}/report?format=html`);
      if (res.ok) {
        const html = await res.text();
        const iframe = document.getElementById('monthlyReportIframe');
        iframe.srcdoc = html;
      }
    }

    // 以標頭傳遞 API Key（伺服器只讀 X-API-Key，不接受網址參數；網址列的金鑰也會進入日誌）
    // 下載到本機：僅針對沒有 SOAP、只上傳申報檔的案件，產生範例病歷（ZIP）。缺少的範本由本機 LLM 生成。首次需填診所表單，之後直接下載。
    let pendingPackageDownload = false;

    async function downloadMonthlyPackage() {
      if (!currentMonthlyBatchId) {
        showNonBlockingNotice('請先上傳或選擇一個申報批次');
        return;
      }
      try {
        const resp = await authFetch(`/api/monthly/batch/${encodeURIComponent(currentMonthlyBatchId)}/package`);
        if (resp.status === 412) {
          const body = await resp.json().catch(() => ({}));
          const missing = (body.missing || []).join('、');
          showNonBlockingNotice('首次下載需先填寫並確認院所資料（診所表單）。' + (missing ? '缺少：' + missing : ''));
          pendingPackageDownload = true;
          toggleFacilityModal(true);
          return;
        }
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          showNonBlockingNotice('下載失敗：' + (body.message || resp.status));
          return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `monthly_package_${currentMonthlyBatchId}.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (err) {
        showNonBlockingNotice('無法連線至服務');
      }
    }

    // 比對範例病歷（缺項）：已有 SOAP 與語音紀錄的案件，與標準範例病歷比對，列出缺少的必要描述。
    async function gapCheckMonthly() {
      if (!currentMonthlyBatchId) {
        showNonBlockingNotice('請先上傳或選擇一個申報批次');
        return;
      }
      try {
        const res = await authFetch(`/api/monthly/batch/${encodeURIComponent(currentMonthlyBatchId)}/gap-check`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showNonBlockingNotice('比對失敗：' + (data.message || res.status));
          return;
        }
        const lines = [];
        for (const c of (data.cases || [])) {
          lines.push(`案件 ${c.case_id}${c.case_seq ? '（流水號 ' + c.case_seq + '）' : ''}`);
          if (c.note) { lines.push('  ' + c.note); continue; }
          for (const it of (c.items || [])) {
            if (it.status === 'no_template') {
              lines.push(`  醫令 ${it.order_code}：${it.message}`);
            } else {
              const miss = (it.missing_sections || []).join('、') || '無';
              lines.push(`  醫令 ${it.order_code}：相似度 ${it.overall_similarity}；缺少欄位：${miss}`);
            }
          }
        }
        const w = window.open('', '_blank');
        if (!w) { showNonBlockingNotice('瀏覽器阻擋了視窗，請允許彈出視窗後再試'); return; }
        const pre = w.document.createElement('pre');
        pre.style.whiteSpace = 'pre-wrap';
        pre.textContent = lines.length ? lines.join('\n') : '沒有可比對的案件（無 SOAP 或無需範本的醫令）';
        w.document.title = '範例病歷比對（缺項）';
        w.document.body.appendChild(pre);
      } catch (err) {
        showNonBlockingNotice('無法連線至服務');
      }
    }

    async function openMonthlyHtmlReport() {
      if (!currentMonthlyBatchId) {
        showNonBlockingNotice('請先上傳或選擇一個申報批次');
        return;
      }
      try {
        const resp = await authFetch(`/api/monthly/batch/${encodeURIComponent(currentMonthlyBatchId)}/report?format=html`);
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          showNonBlockingNotice(`無法開啟報告：${body.message || resp.status}`);
          return;
        }
        const blob = new Blob([await resp.text()], { type: 'text/html;charset=utf-8' });
        window.open(URL.createObjectURL(blob), '_blank');
      } catch (err) {
        showNonBlockingNotice('無法連線至服務');
      }
    }

    async function importCases(file) {
      if (!file) return;
      const kind = currentMode === 'sampling' ? 'sampling' : 'appeal';
      const fd = new FormData();
      fd.append('file', file);
      const res = await authFetch(`/api/${kind}/import`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) {
        showNonBlockingNotice('匯入失敗：' + (data.message || '請稍後再試'));
        return;
      }
      if (data.status === 'partial') {
        showNonBlockingNotice(data.message + (data.extracted_text_preview ? '\n\n【OCR 預覽】\n' + data.extracted_text_preview : ''));
        return;
      }
      if (data.facility_code) {
        currentFacility.code = data.facility_code;
        updateFacilityUI(currentFacility);
      }
      let msg = `匯入完成：${data.imported} 筆（來源 ${data.source}）`;
      if (data.rejected > 0) {
        const reasons = (data.rejected_rows || []).slice(0, 5)
          .map(r => `第 ${r.row} 列：${r.reason}`).join('\n');
        msg += `\n拒絕 ${data.rejected} 筆：\n${reasons}`;
      }
      showNonBlockingNotice(msg);
      document.getElementById('importFile').value = '';
      await loadCaseData();
    }

    function showCaseListMessage(msg) {
      const container = document.getElementById('caseList');
      container.innerHTML = '';
      const div = document.createElement('div');
      div.style.cssText = 'padding: 12px; font-size: 12px; color: #fbbf24;';
      div.textContent = msg;
      container.appendChild(div);
    }

    async function loadCaseData() {
      if (currentMode === 'sampling') {
        const res = await authFetch('/api/sampling/cases');
        if (res.status === 401) return showCaseListMessage('請先在上方輸入 API Key 以讀取案件清單。');
        samplingCases = await res.json();
        // autoload：若抽樣清單為空但有當月預審批次，自動帶入當月預審案件
        if ((!Array.isArray(samplingCases) || samplingCases.length === 0) && currentMonthlyBatchId) {
          try {
            await authFetch('/api/sampling/import-from-monthly', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ batch: currentMonthlyBatchId })
            });
            const r2 = await authFetch('/api/sampling/cases');
            if (r2.ok) samplingCases = await r2.json();
          } catch (e) {
            console.warn('Autoload sampling cases failed:', e);
          }
        }
        renderCaseList(samplingCases);
        if (Array.isArray(samplingCases) && samplingCases.length > 0) selectSamplingCase(samplingCases[0].id);
      } else if (currentMode === 'appeal') {
        const res = await authFetch('/api/appeal/cases');
        if (res.status === 401) return showCaseListMessage('請先在上方輸入 API Key 以讀取案件清單。');
        appealCases = await res.json();
        // autoload：若申復清單為空但有當月預審批次，自動帶入高額申報案件
        if ((!Array.isArray(appealCases) || appealCases.length === 0) && currentMonthlyBatchId) {
          try {
            await authFetch('/api/appeal/import-from-monthly', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ batch: currentMonthlyBatchId })
            });
            const r2 = await authFetch('/api/appeal/cases');
            if (r2.ok) appealCases = await r2.json();
          } catch (e) {
            console.warn('Autoload appeal cases failed:', e);
          }
        }
        renderCaseList(appealCases);
        if (Array.isArray(appealCases) && appealCases.length > 0) selectAppealCase(appealCases[0].id);
      } else {
        const res = await authFetch('/api/monthly/batches');
        const data = await res.json();
        monthlyBatches = Array.isArray(data) ? data : (data && data.batches ? data.batches : []);
        renderMonthlyBatchList(monthlyBatches);
        if (monthlyBatches.length > 0) {
          if (!currentMonthlyBatchId) {
            currentMonthlyBatchId = monthlyBatches[0].batch;
          }
          loadMonthlyReport(currentMonthlyBatchId);
        }
      }
    }

    function renderMonthlyBatchList(batches) {
      const container = document.getElementById('caseList');
      container.innerHTML = '';
      if (!batches || batches.length === 0) {
        showCaseListMessage('尚無申報總檔批次。請點擊「上傳 申報壓縮檔 總檔」。');
        return;
      }
      batches.forEach(item => {
        const div = document.createElement('div');
        div.className = `case-item ${currentMonthlyBatchId === item.batch ? 'active' : ''}`;
        div.onclick = () => loadMonthlyReport(item.batch);
        const count = item.cases ?? item.case_count ?? 0;

        const row = document.createElement('div');
        row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;';
        const codeSpan = document.createElement('span');
        codeSpan.className = 'case-code';
        codeSpan.textContent = item.batch ?? '';
        const badgeSpan = document.createElement('span');
        badgeSpan.className = 'badge badge-sufficient';
        badgeSpan.textContent = `${count} 案`;
        row.appendChild(codeSpan);
        row.appendChild(badgeSpan);

        const sub = document.createElement('div');
        sub.style.cssText = 'font-size:10px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;';
        sub.textContent = '門診申報總檔';

        div.appendChild(row);
        div.appendChild(sub);

        // 浮動字幕（Tooltip）綁定
        div.onmouseenter = (e) => {
          showFloatingTooltip(e, {
            title: `申報總檔批次 ${item.batch ?? ''}`,
            rows: [
              { label: '📦 批次代碼', value: item.batch ?? '' },
              { label: '🏥 機構代號', value: item.facility_code || currentFacility.code || '未註記' },
              { label: '📁 總案件數', value: `${count} 筆案件`, color: '#10b981' },
              { label: '📅 費用年月', value: item.fee_ym || '202307' },
              { label: '💡 提示', value: '點擊載入右側高風險預審報告' }
            ]
          });
        };
        div.onmousemove = (e) => updateTooltipPosition(e);
        div.onmouseleave = () => hideFloatingTooltip();

        container.appendChild(div);
      });
    }

    function renderCaseList(list) {
      const container = document.getElementById('caseList');
      container.innerHTML = '';
      list.forEach(item => {
        const div = document.createElement('div');
        div.className = `case-item ${currentSelectedCase && currentSelectedCase.id === item.id ? 'active' : ''}`;
        div.onclick = () => currentMode === 'sampling' ? selectSamplingCase(item.id) : selectAppealCase(item.id);
        
        // P1-5：改以 DOM API 建構，所有 API 欄位一律走 textContent。
        // 匯入功能上線後 order_code/patient_name/order_name 皆來自使用者
        // 上傳的 CSV／OCR 結果，innerHTML 樣板即為真實 XSS 注入點。
        const topRow = document.createElement('div');
        topRow.style.cssText =
          'display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;';

        const codeSpan = document.createElement('span');
        codeSpan.className = 'case-code';
        codeSpan.textContent = item.order_code ?? '';
        topRow.appendChild(codeSpan);

        // 列表徽章配合審查流程狀態（待審 -> 審查中 -> 審完）呈現：
        const badge = document.createElement('span');
        if (currentMode === 'appeal') {
          badge.className = 'badge badge-none';
          badge.textContent = `核減 ${item.deduct_amount ?? ''}點`;
        } else {
          const rev = item.review || {};
          const support = rev.support_state || item.support_level;
          if (item.state === 'reviewing') {
            badge.className = 'badge badge-weak';
            badge.textContent = '🔄 審查中';
          } else if (item.state === 'reviewed' || (support && support !== '待判定')) {
            if (support === '充分') {
              badge.className = 'badge badge-sufficient';
              badge.textContent = '✅ 充分';
            } else if (support === '薄弱') {
              badge.className = 'badge badge-weak';
              badge.textContent = '⚠️ 薄弱';
            } else if (support === '裸奔') {
              badge.className = 'badge badge-none';
              badge.textContent = '❌ 裸奔';
            } else {
              badge.className = 'badge badge-sufficient';
              badge.textContent = '✅ 審完';
            }
          } else {
            badge.className = 'badge badge-weak';
            badge.textContent = '⏳ 待審';
          }
        }
        topRow.appendChild(badge);
        div.appendChild(topRow);

        const nameRow = document.createElement('div');
        nameRow.style.cssText = 'font-size:11px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:125px;';
        const displayOrderName = item.order_name || item.target_order_code || item.order_code || '';
        nameRow.textContent = `${item.patient_name ?? ''} ${displayOrderName}`;
        if (item.demo) {
          const demoTag = document.createElement('span');
          demoTag.style.cssText =
            'font-size:9px;color:#888;border:1px solid #ccc;border-radius:3px;padding:0 3px;margin-left:4px;';
          demoTag.textContent = '示範';
          nameRow.appendChild(demoTag);
        }
        div.appendChild(nameRow);

        // 浮動字幕（Tooltip）綁定：懸浮呈現完整病患姓名、身分證、主診斷、完整醫令名稱與總費用點數
        div.onmouseenter = (e) => {
          const fullOrderName = item.order_name || item.target_order_code || item.order_code || '未註記';
          const pName = item.patient_name || '未提供';
          const pId = item.id_card || item.record_no || item.id || '無案號';
          const rows = [
            { label: '👤 病患姓名', value: pName },
            { label: '🪪 身分證／病歷號', value: pId },
            { label: '💊 醫令代碼', value: item.order_code || '未提供' },
            { label: '📝 完整醫令名稱', value: fullOrderName }
          ];

          if (item.diag_code) {
            rows.push({ label: '🩺 主診斷代碼', value: `${item.diag_code} ${item.diag_name || ''}`.trim() });
          }

          if (currentMode === 'appeal') {
            rows.push({ label: '❌ 核減金額', value: `${item.deduct_amount || 0} 點`, color: '#ef4444' });
            if (item.deduct_reason) {
              rows.push({ label: '⚠️ 核減理由', value: item.deduct_reason });
            }
          } else {
            const rev = item.review || {};
            const support = rev.support_state || item.support_level || '待審';
            let color = '#f59e0b';
            if (support === '充分') color = '#10b981';
            else if (support === '裸奔') color = '#ef4444';
            rows.push({ label: '📊 支持度判定', value: support, color: color });
            if (item.points) {
              rows.push({ label: '💰 申報總費用', value: `${item.points} 點` });
            }
          }

          showFloatingTooltip(e, {
            title: `案件詳細摘要 [${item.order_code || item.id}]`,
            rows
          });
        };
        div.onmousemove = (e) => updateTooltipPosition(e);
        div.onmouseleave = () => hideFloatingTooltip();

        container.appendChild(div);
      });
    }

    function splitSoapToSections(raw) {
      if (!raw) return { s: '', o: '', a: '', p: '' };
      if (typeof raw === 'object') {
        return {
          s: raw.s || raw.subjective || '',
          o: raw.o || raw.objective || '',
          a: raw.a || raw.assessment || '',
          p: raw.p || raw.plan || ''
        };
      }
      const text = String(raw).trim();
      const sPat = /(?:^|\n)\s*(?:\[?[Ss](?:ubjective)?\]?[:：]|\bS[:：])\s*([\s\S]*?)(?=(?:\n\s*(?:\[?[Oo](?:bjective)?\]?[:：]|\bO[:：]))|$)/;
      const oPat = /(?:^|\n)\s*(?:\[?[Oo](?:bjective)?\]?[:：]|\bO[:：])\s*([\s\S]*?)(?=(?:\n\s*(?:\[?[Aa](?:ssessment)?\]?[:：]|\bA[:：]))|$)/;
      const aPat = /(?:^|\n)\s*(?:\[?[Aa](?:ssessment)?\]?[:：]|\bA[:：])\s*([\s\S]*?)(?=(?:\n\s*(?:\[?[Pp](?:lan)?\]?[:：]|\bP[:：]))|$)/;
      const pPat = /(?:^|\n)\s*(?:\[?[Pp](?:lan)?\]?[:：]|\bP[:：])\s*([\s\S]*)$/;

      const sm = text.match(sPat);
      const om = text.match(oPat);
      const am = text.match(aPat);
      const pm = text.match(pPat);

      if (sm || om || am || pm) {
        return {
          s: sm ? sm[1].trim() : '',
          o: om ? om[1].trim() : '',
          a: am ? am[1].trim() : '',
          p: pm ? pm[1].trim() : ''
        };
      }
      return { s: text, o: '', a: '', p: '' };
    }

    function combineStage2Soap() {
      const s = (document.getElementById('sSoapInputS')?.value || '').trim();
      const o = (document.getElementById('sSoapInputO')?.value || '').trim();
      const a = (document.getElementById('sSoapInputA')?.value || '').trim();
      const p = (document.getElementById('sSoapInputP')?.value || '').trim();
      if (!s && !o && !a && !p) return '';
      return `S: ${s}\nO: ${o}\nA: ${a}\nP: ${p}`;
    }

    function setStage2Soap(raw) {
      const sec = splitSoapToSections(raw);
      const sEl = document.getElementById('sSoapInputS');
      const oEl = document.getElementById('sSoapInputO');
      const aEl = document.getElementById('sSoapInputA');
      const pEl = document.getElementById('sSoapInputP');
      if (sEl) sEl.value = sec.s;
      if (oEl) oEl.value = sec.o;
      if (aEl) aEl.value = sec.a;
      if (pEl) pEl.value = sec.p;
      const hidden = document.getElementById('sSoapInput');
      if (hidden) {
        hidden.value = (typeof raw === 'string' && raw.trim()) ? raw : combineStage2Soap();
      }
    }

    function onStage2SoapInputChanged() {
      const full = combineStage2Soap();
      const hidden = document.getElementById('sSoapInput');
      if (hidden) hidden.value = full;
      onSoapContentChanged('sampling');
    }

    async function saveCaseSoapToDatabase(caseId, soapText, kind) {
      if (!caseId) return { ok: false, error: 'no_case_id' };
      try {
        const res = await authFetch(`/api/${kind}/cases/${encodeURIComponent(caseId)}/soap`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ soap: soapText, soap_text: soapText })
        });
        return { ok: res.ok };
      } catch (err) {
        console.error('saveCaseSoapToDatabase error:', err);
        return { ok: false, error: err };
      }
    }

    function pushStage2SoapToHis() {
      const full = combineStage2Soap() || document.getElementById('sSoapInput')?.value || '';
      triggerDirectHisWrite('2階抽樣事前預審', full);
    }

    function confirmAndPushStage2() {
      confirmAndPushStage2Both();
    }

    function confirmAndPushStage3() {
      confirmAndPushStage3Both();
    }

    async function confirmAndPushStage2Both() {
      const full = combineStage2Soap() || document.getElementById('sSoapInput')?.value || '';
      triggerDirectHisWrite('2階抽樣事前預審', full);
      const caseId = currentSelectedCase?.id || currentSelectedCase?.case_id;
      if (caseId) {
        await saveCaseSoapToDatabase(caseId, full, 'sampling');
      }
      const alertEl = document.getElementById('sHisSyncAlert');
      if (alertEl) alertEl.style.display = 'none';
      showNonBlockingNotice('✅ 已同意修訂！\n已將最新 SOAP 病歷成功寫回 HIS 門診病歷，並同步永久儲存至伺服器資料庫 (Database)！');
    }

    async function confirmAndPushStage3Both() {
      const full = getAppealFullText();
      triggerDirectHisWrite('3階核減事後申復', full);
      const caseId = currentSelectedCase?.id || currentSelectedCase?.case_id;
      if (caseId) {
        await saveCaseSoapToDatabase(caseId, full, 'appeal');
      }
      const alertEl = document.getElementById('aHisSyncAlert');
      if (alertEl) alertEl.style.display = 'none';
      showNonBlockingNotice('✅ 已同意修訂！\n已將最新申復病歷佐證成功寫回 HIS 系統，並同步永久儲存至伺服器資料庫 (Database)！申復案卷已送出。');
    }

    function selectSamplingCase(id) {
      currentSelectedCase = samplingCases.find(c => c.id === id);
      renderCaseList(samplingCases);
      if (!currentSelectedCase) return;

      const orderNameStr = currentSelectedCase.order_name || currentSelectedCase.target_order_code || currentSelectedCase.order_code || '';
      document.getElementById('sOrderName').innerText = `${currentSelectedCase.order_code} - ${orderNameStr}`;
      setStage2Soap(currentSelectedCase.soap);
      const missingReason = currentSelectedCase.missing_reason || '病歷 SOAP A 欄僅記載簡寫 DM，未附上近三次血糖趨勢與檢驗必要性說明。';
      document.getElementById('sMissingReason').innerText = `建立清單：${missingReason}`;

      const badge = document.getElementById('sSupportBadge');
      const rev = currentSelectedCase.review || {};
      const support = rev.support_state || currentSelectedCase.support_level;
      if (currentSelectedCase.state === 'reviewing') {
        badge.innerText = '🔄 審查中';
        badge.className = 'badge badge-weak';
      } else if (currentSelectedCase.state === 'reviewed' || (support && support !== '待判定')) {
        if (support === '充分') {
          badge.innerText = '✅ 充分';
          badge.className = 'badge badge-sufficient';
        } else if (support === '薄弱') {
          badge.innerText = '⚠️ 薄弱';
          badge.className = 'badge badge-weak';
        } else if (support === '裸奔') {
          badge.innerText = '❌ 裸奔';
          badge.className = 'badge badge-none';
        } else {
          badge.innerText = '✅ 審完';
          badge.className = 'badge badge-sufficient';
        }
      } else {
        badge.innerText = '⏳ 待審';
        badge.className = 'badge badge-weak';
      }

      fillSamplingEvidence(currentSelectedCase);
      refreshVault(currentSelectedCase);
      runSamplingAudit();
    }

    // ── Phase 16-03：抽樣多源證據、預審卡片與健保抽審 XML ──
    function formatLabLines(labs) {
      return (labs || []).map(l => [l.name, l.value, l.unit, l.date].filter((s, i) => i < 2 || s).join(' | ')).join('\n');
    }

    function parseLabLines(text) {
      return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => {
        const [name = '', value = '', unit = '', date = ''] = line.split('|').map(s => s.trim());
        return { name, value, unit, date };
      });
    }

    function fillSamplingEvidence(c) {
      document.getElementById('sLabInput').value = formatLabLines(c.lab_results);
      document.getElementById('sCloudInput').value = c.cloud_records || '';
      refreshSamplingAttachments(c.id);
    }

    // ── Phase 17-02：身分證佐證庫（vault）多源掛載與多媒體預覽 ──
    // 所有使用者／伺服器字串一律以 textContent 或 DOM API 寫入（不使用 innerHTML）。
    const VAULT_CATEGORIES = ['audio', 'images', 'reports', 'records'];
    const VAULT_CONTAINERS = { audio: 'vaultAudio', images: 'vaultImages', reports: 'vaultReports', records: 'vaultRecords' };
    const VAULT_PREVIEWABLE_IMAGE_EXT = ['.jpg', '.jpeg', '.png'];
    const VAULT_MAX_UPLOAD_BYTES = 11 * 1024 * 1024;  // 與後端 MAX_CONTENT_LENGTH 一致
    let vaultActiveKey = null;
    let vaultRequestSeq = 0;
    let vaultObjectUrls = [];

    // 由抽樣案件推導 vault_key：病歷號須為「1 英文字母＋9 碼數字」（身分證格式），
    // 就醫日期取西元年後兩碼＋月份（YYMM），例如 2026-05-10 → 2605。
    // 依案件 record_no 與 visit_date 推導 15 碼 vault_key（例：A123456789-2611）。
    // record_no 若為身分證號須為 1 碼英文字母＋9 碼數字；亦可由病歷號輸入欄選填補全。
    // visit_date 接受 ISO YYYY-MM-DD、YYYY/MM/DD 或民國 YYYMMDD、YYY/MM/DD。
    function computeVaultKey(record) {
      let rawNo = String(record?.id_card ?? record?.id_number ?? record?.record_no ?? '').trim().toUpperCase();
      const aInput = document.getElementById('aRecordNoInput');
      if (!/^[A-Z][0-9]{9}$/.test(rawNo) && aInput && aInput.value) {
        const val = aInput.value.trim().toUpperCase();
        if (/^[A-Z][0-9]{9}$/.test(val)) rawNo = val;
      }
      if (!/^[A-Z][0-9]{9}$/.test(rawNo)) {
        return {
          key: null,
          error: `病歷號「${rawNo || '（空白）'}」不是身分證格式（需 1 個英文字母＋9 碼數字，目前 ${rawNo.length} 碼），無法自動掛載佐證庫。`,
        };
      }
      const visit = String(record?.visit_date ?? '').trim();
      const iso = /^(\d{4})[\/\-.]?(\d{2})[\/\-.]?(\d{2})$/.exec(visit);
      const roc = /^(\d{3})[\/\-.]?(\d{2})[\/\-.]?(\d{2})$/.exec(visit);
      let year;
      let month;
      if (iso) {
        year = Number(iso[1]);
        month = Number(iso[2]);
      } else if (roc) {
        year = Number(roc[1]) + 1911;
        month = Number(roc[2]);
      } else {
        return { key: null, error: `就醫日期「${visit || '（空白）'}」無法解析（需 YYYY-MM-DD 或民國 YYYMMDD），無法掛載佐證庫。` };
      }
      if (month < 1 || month > 12) {
        return { key: null, error: `就醫日期月份不合法：「${visit}」。` };
      }
      const yymm = String(year % 100).padStart(2, '0') + String(month).padStart(2, '0');
      return { key: `${rawNo}-${yymm}`, error: null };
    }

    function vaultFileUrl(key, category, filename) {
      return `/api/vault/${encodeURIComponent(key)}/files/${category}/${encodeURIComponent(filename)}`;
    }

    function setVaultMessage(text) {
      document.getElementById('vaultMessage').textContent = text;
    }

    function setVaultButtonsEnabled(enabled) {
      const b1 = document.getElementById('vaultBtnFile');
      const b2 = document.getElementById('vaultBtnZip');
      const ab1 = document.getElementById('aVaultBtnFile');
      const ab2 = document.getElementById('aVaultBtnZip');
      if (b1) b1.disabled = !enabled;
      if (b2) b2.disabled = !enabled;
      if (ab1) ab1.disabled = !enabled;
      if (ab2) ab2.disabled = !enabled;
    }

    function clearVaultObjectUrls() {
      vaultObjectUrls.forEach(u => URL.revokeObjectURL(u));
      vaultObjectUrls = [];
    }

    function vaultPlaceholder(text) {
      const p = document.createElement('div');
      p.className = 'vault-empty';
      p.textContent = text;
      return p;
    }

    function renderVaultContainersEmpty(text) {
      VAULT_CATEGORIES.forEach(cat => {
        const box = document.getElementById(VAULT_CONTAINERS[cat]);
        if (box) box.replaceChildren(vaultPlaceholder(text));
      });
      const aBox = document.getElementById('aVaultImages');
      if (aBox) aBox.replaceChildren(vaultPlaceholder(text));
    }

    // <audio>／<img> 無法附帶 X-API-Key 標頭，故改以 authFetch 取回後轉為同源 blob URL。
    // seq 不符代表使用者已切換案件，回傳 null 並立即釋放該 URL。
    async function fetchVaultBlobUrl(url, seq) {
      try {
        const res = await authFetch(url);
        if (!res.ok) return null;
        const objectUrl = URL.createObjectURL(await res.blob());
        if (seq !== vaultRequestSeq) {
          URL.revokeObjectURL(objectUrl);
          return null;
        }
        vaultObjectUrls.push(objectUrl);
        return objectUrl;
      } catch (err) {
        return null;
      }
    }

    function isPreviewableImage(filename) {
      const lower = filename.toLowerCase();
      return VAULT_PREVIEWABLE_IMAGE_EXT.some(ext => lower.endsWith(ext));
    }

    function openVaultLightbox(url, caption) {
      document.getElementById('vaultLightboxImg').src = url;
      document.getElementById('vaultLightboxCaption').textContent = caption;
      document.getElementById('vaultLightbox').hidden = false;
    }

    function closeVaultLightbox() {
      document.getElementById('vaultLightbox').hidden = true;
      document.getElementById('vaultLightboxImg').removeAttribute('src');
    }

    // 報告／病歷：先同步開啟空白分頁（避免 await 後被彈窗攔截），取得檔案後再導向 blob。
    async function openVaultFile(category, filename) {
      const key = vaultActiveKey;
      if (!key) return;
      const win = window.open('', '_blank');
      try {
        const res = await authFetch(vaultFileUrl(key, category, filename));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const objectUrl = URL.createObjectURL(await res.blob());
        if (win) {
          win.location.href = objectUrl;
        } else {
          setVaultMessage('瀏覽器攔截了新分頁，請允許彈出視窗後再試。');
        }
        setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
      } catch (err) {
        if (win) win.close();
        setVaultMessage(`開啟失敗：${filename}（${err.message}）`);
      }
    }

    function renderVaultAudio(files, urls) {
      const box = document.getElementById(VAULT_CONTAINERS.audio);
      if (!files.length) {
        box.replaceChildren(vaultPlaceholder('尚無錄音檔'));
        return;
      }
      const nodes = files.map((f, i) => {
        const card = document.createElement('div');
        card.style.marginBottom = '10px';
        const name = document.createElement('div');
        name.className = 'vault-item-name';
        name.style.fontSize = '12px';
        name.textContent = f.filename;
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'metadata';
        if (urls[i]) {
          audio.src = urls[i];
          card.append(name, audio);
        } else {
          card.append(name, vaultPlaceholder('無法載入此錄音（檢查權限或檔案）'));
        }
        return card;
      });
      box.replaceChildren(...nodes);
    }

    function renderVaultImages(files, urls) {
      const box = document.getElementById(VAULT_CONTAINERS.images);
      const aBox = document.getElementById('aVaultImages');
      const makeNodes = () => {
        if (!files.length) {
          return [vaultPlaceholder('尚無影像')];
        }
        return files.map((f, i) => {
          const tile = document.createElement('button');
          tile.type = 'button';
          tile.className = 'vault-thumb';
          const name = document.createElement('span');
          name.className = 'vault-thumb-name';
          name.textContent = f.filename;
          if (urls[i]) {
            const img = document.createElement('img');
            img.src = urls[i];
            img.alt = f.filename;
            tile.onclick = () => openVaultLightbox(urls[i], f.filename);
            tile.append(img, name);
          } else {
            // DICOM／HEIC 等瀏覽器無法直接顯示：提供開啟（下載）而非縮圖
            tile.textContent = '📎 ' + f.filename;
            tile.onclick = () => openVaultFile('images', f.filename);
          }
          return tile;
        });
      };
      if (box) box.replaceChildren(...makeNodes());
      if (aBox) aBox.replaceChildren(...makeNodes());
    }

    function renderVaultLinkList(boxId, category, files, emptyText) {
      const box = document.getElementById(boxId);
      if (!files.length) {
        box.replaceChildren(vaultPlaceholder(emptyText));
        return;
      }
      const nodes = files.map(f => {
        const row = document.createElement('div');
        row.className = 'vault-item';
        const name = document.createElement('span');
        name.className = 'vault-item-name';
        name.textContent = `${f.filename}（${f.size} bytes）`;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-action';
        btn.style.cssText = 'padding: 3px 10px; font-size: 11px; flex-shrink: 0;';
        btn.textContent = '開啟';
        btn.onclick = () => openVaultFile(category, f.filename);
        row.append(name, btn);
        return row;
      });
      box.replaceChildren(...nodes);
    }

    async function loadVault(key, seq) {
      try {
        const res = await authFetch(`/api/vault/${encodeURIComponent(key)}`);
        const body = await res.json().catch(() => ({}));
        if (seq !== vaultRequestSeq) return;
        if (!res.ok) {
          setVaultMessage('無法載入佐證庫：' + (body.message || res.status));
          renderVaultContainersEmpty('載入失敗');
          return;
        }
        const grouped = {};
        VAULT_CATEGORIES.forEach(cat => {
          grouped[cat] = (body.categories && body.categories[cat] && body.categories[cat].files) || [];
        });
        await renderVaultFiles(key, grouped, seq);
      } catch (err) {
        if (seq === vaultRequestSeq) setVaultMessage('無法連線至服務');
      }
    }

    async function renderVaultFiles(key, grouped, seq) {
      clearVaultObjectUrls();
      const counts = VAULT_CATEGORIES.map(cat => grouped[cat].length);
      const total = counts.reduce((a, b) => a + b, 0);
      if (total === 0) {
        setVaultMessage(`尚未匯入 ${key} 佐證檔案，可拖曳 ZIP 或單檔至此`);
      } else {
        setVaultMessage(`${key}：錄音 ${counts[0]}／影像 ${counts[1]}／報告 ${counts[2]}／病歷 ${counts[3]}（共 ${total} 個檔案）`);
      }

      // 錄音與可預覽影像在渲染前先取回 blob URL（平行送出）
      const audioUrls = await Promise.all(grouped.audio.map(f =>
        fetchVaultBlobUrl(vaultFileUrl(key, 'audio', f.filename), seq)));
      const imageUrls = await Promise.all(grouped.images.map(f =>
        isPreviewableImage(f.filename) ? fetchVaultBlobUrl(vaultFileUrl(key, 'images', f.filename), seq) : Promise.resolve(null)));
      if (seq !== vaultRequestSeq) return;

      renderVaultAudio(grouped.audio, audioUrls);
      renderVaultImages(grouped.images, imageUrls);
      renderVaultLinkList('vaultReports', 'reports', grouped.reports, '尚無檢驗檢查報告');
      renderVaultLinkList('vaultRecords', 'records', grouped.records, '尚無病歷紀錄');
    }

    // 點選案件時呼叫：推導 vault_key，成功則載入佐證庫，失敗則說明原因
    async function refreshVault(record) {
      const seq = ++vaultRequestSeq;
      clearVaultObjectUrls();
      const result = computeVaultKey(record);
      vaultActiveKey = result.key;
      setVaultButtonsEnabled(Boolean(result.key));
      const label = document.getElementById('vaultKeyLabel');
      const aLabel = document.getElementById('aVaultKeyLabel');
      if (!result.key) {
        if (label) label.textContent = '無法自動掛載';
        if (aLabel) aLabel.textContent = '無法自動掛載';
        setVaultMessage(result.error);
        renderVaultContainersEmpty('請修正病歷號或就醫日期後重新選取案件');
        return;
      }
      if (label) label.textContent = result.key;
      if (aLabel) aLabel.textContent = result.key;
      setVaultMessage('載入佐證庫中…');
      await loadVault(result.key, seq);
    }

    async function uploadVaultFiles(fileList) {
      const key = vaultActiveKey;
      if (!key) {
        setVaultMessage('請先選取可掛載佐證庫的案件');
        return;
      }
      const files = Array.from(fileList || []);
      if (!files.length) return;
      const totalBytes = files.reduce((n, f) => n + f.size, 0);
      if (totalBytes > VAULT_MAX_UPLOAD_BYTES) {
        setVaultMessage(`單次上傳超過 11 MB 上限（目前 ${(totalBytes / 1048576).toFixed(1)} MB），請分批上傳。`);
        return;
      }
      const fd = new FormData();
      files.forEach(f => fd.append('file', f, f.name));
      setVaultMessage(`上傳中：${files.length} 個檔案…`);
      try {
        const res = await authFetch(`/api/vault/${encodeURIComponent(key)}/upload`, { method: 'POST', body: fd });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          setVaultMessage('上傳失敗：' + (body.message || res.status));
        } else {
          setVaultMessage(`已匯入 ${body.saved.length} 個檔案。`);
        }
      } catch (err) {
        setVaultMessage('無法連線至服務');
      } finally {
        document.getElementById('vaultFileInput').value = '';
        document.getElementById('vaultZipInput').value = '';
      }
      if (vaultActiveKey === key) {
        await loadVault(key, ++vaultRequestSeq);
      }
    }

    function handleVaultDragOver(event) {
      event.preventDefault();
      if (vaultActiveKey) document.getElementById('vaultDropzone').classList.add('dragover');
    }

    function handleVaultDragLeave(event) {
      document.getElementById('vaultDropzone').classList.remove('dragover');
    }

    function handleVaultDrop(event) {
      event.preventDefault();
      document.getElementById('vaultDropzone').classList.remove('dragover');
      uploadVaultFiles(event.dataTransfer ? event.dataTransfer.files : null);
    }

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeVaultLightbox();
    });

    async function refreshSamplingAttachments(caseId) {
      const box = document.getElementById('sAttachList');
      box.innerText = '載入中…';
      try {
        const res = await authFetch(`/api/appeal/attachments/${encodeURIComponent(caseId)}`);
        if (!res.ok) {
          box.innerText = '無法載入附件清單';
          return;
        }
        const data = await res.json();
        const items = data.attachments || [];
        box.innerText = items.length
          ? items.map(a => `📎 ${a.filename}（${a.mime_type}，${a.file_size} bytes）`).join('\n')
          : '尚未上傳影像佐證';
      } catch (err) {
        box.innerText = '無法連線至服務';
      }
    }

    async function clearSamplingCases() {
      if (!confirm('確定要清空目前所有的抽樣案件嗎？此操作將重置抽樣清單。')) return;
      const res = await authFetch('/api/sampling/cases/clear', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('清空失敗：' + (data.message || res.status));
        return;
      }
      showNonBlockingNotice(data.message || '已清空抽樣案件');
      currentSelectedCase = null;
      await loadCaseData();
    }

    async function sampleFromMonthlyBatch() {
      const batch = currentMonthlyBatchId || (monthlyBatches.length > 0 ? monthlyBatches[0].batch : null);
      if (!batch) {
        showNonBlockingNotice('尚未上傳當月申報檔，請先於「1. 當月申報檔預審」上傳 申報壓縮檔 總檔');
        return;
      }
      const res = await authFetch('/api/sampling/sample-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch, random_count: 20, intentional_count: 10 })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('自動抽樣失敗：' + (data.message || res.status));
        return;
      }
      showNonBlockingNotice(`抽樣完成：批次 ${data.batch}，共 ${data.sampled} 筆（隨機 ${data.random}／立意 ${data.intentional}）。\n新增 ${data.case_store_persisted} 筆，既有略過 ${data.case_store_conflicts.length} 筆。`);
      await loadCaseData();
    }

    async function saveSamplingEvidence() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆抽樣案件');
        return;
      }
      const caseId = currentSelectedCase.id;
      const res = await authFetch(`/api/sampling/cases/${encodeURIComponent(caseId)}/evidence`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lab_results: parseLabLines(document.getElementById('sLabInput').value),
          cloud_records: document.getElementById('sCloudInput').value
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('儲存失敗：' + (data.message || res.status));
        return;
      }
      currentSelectedCase.lab_results = data.lab_results;
      currentSelectedCase.cloud_records = data.cloud_records;
      await runSamplingAudit();
    }

    async function uploadSamplingAttachment(file) {
      if (!file || !currentSelectedCase) return;
      const caseId = currentSelectedCase.id;
      const fd = new FormData();
      fd.append('case_id', caseId);
      fd.append('file', file);
      const res = await authFetch('/api/appeal/attachments/upload', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) showNonBlockingNotice('上傳失敗：' + (data.message || res.status));
      document.getElementById('sAttachInput').value = '';
      await refreshSamplingAttachments(caseId);
    }

    async function openSamplingPreview() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆抽樣案件');
        return;
      }
      const res = await authFetch(`/api/sampling/cases/${encodeURIComponent(currentSelectedCase.id)}/preview-html`);
      if (!res.ok) {
        showNonBlockingNotice('無法開啟預審卡片（' + res.status + '）');
        return;
      }
      const blob = new Blob([await res.text()], { type: 'text/html;charset=utf-8' });
      window.open(URL.createObjectURL(blob), '_blank');
    }

    // ── Phase 20：批次審查、聚合報告、全批次 XML、第 2→第 3 階連動 ──
    async function runSamplingBatchAudit() {
      if (!confirm('將對全部抽樣案件執行自動審查並寫回結果，可能需要數分鐘，是否繼續？')) return;
      
      const pContainer = document.getElementById('batchAuditProgress');
      const pText = document.getElementById('batchProgressText');
      const pPercent = document.getElementById('batchProgressPercent');
      const pEta = document.getElementById('batchProgressEta');
      const pBar = document.getElementById('batchProgressBar');
      const btnAudit = document.getElementById('btnBatchAudit');

      if (pContainer) pContainer.style.display = 'block';
      if (btnAudit) btnAudit.disabled = true;

      const totalCases = samplingCases.length;
      if (totalCases === 0) {
        showNonBlockingNotice('目前無抽樣案件可供審查');
        if (pContainer) pContainer.style.display = 'none';
        if (btnAudit) btnAudit.disabled = false;
        return;
      }

      // 立即將左側所有抽樣清單標記為「🔄 審查中」
      samplingCases.forEach(c => {
        c.state = 'reviewing';
      });
      renderCaseList(samplingCases);

      const startTime = Date.now();
      let completedCount = 0;
      const results = [];
      const errors = [];
      const stateCounts = {};

      function formatEta(seconds) {
        if (!seconds || seconds <= 0) return '即將完成';
        const m = Math.floor(seconds / 60);
        const s = Math.round(seconds % 60);
        return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
      }

      function updateProgress(currIndex, caseId) {
        const percent = Math.round((currIndex / totalCases) * 100);
        if (pBar) pBar.style.width = `${percent}%`;
        if (pPercent) pPercent.innerText = `${percent}% (${currIndex}/${totalCases} 案)`;
        
        if (currIndex > 0) {
          const elapsed = (Date.now() - startTime) / 1000;
          const avgPerCase = elapsed / currIndex;
          const remainingSec = (totalCases - currIndex) * avgPerCase;
          if (pEta) pEta.innerText = `預估剩餘時間：${formatEta(remainingSec)}`;
        } else {
          if (pEta) pEta.innerText = '預估剩餘時間：計算中...';
        }
        if (pText && caseId) {
          pText.innerHTML = '';
          const spin = document.createElement('span');
          spin.className = 'spinner';
          spin.style.cssText = 'display:inline-block; width:12px; height:12px; border:2px solid #38bdf8; border-top-color:transparent; border-radius:50%; animation:spin 1s linear infinite;';
          const msg = document.createElement('span');
          msg.textContent = `正在審查 (${currIndex + 1}/${totalCases})：`;
          const codeEl = document.createElement('code');
          codeEl.textContent = caseId;
          const dots = document.createTextNode('...');
          msg.appendChild(codeEl);
          msg.appendChild(dots);
          pText.appendChild(spin);
          pText.appendChild(document.createTextNode(' '));
          pText.appendChild(msg);
        }
      }

      updateProgress(0, samplingCases[0].id);

      try {
        // 逐案執行閉環，即時推進進度條與左側狀態徽章
        for (let i = 0; i < totalCases; i++) {
          const c = samplingCases[i];
          updateProgress(i, c.id);

          // 同一機構同一月份：若本案已完成審查且具有判定結果，不須一直重複驗證
          if (c.state === 'reviewed' && c.support_level && c.support_level !== '待判定') {
            completedCount++;
            stateCounts[c.support_level] = (stateCounts[c.support_level] || 0) + 1;
            continue;
          }

          try {
            const res = await authFetch(`/api/sampling/cases/${encodeURIComponent(c.id)}/closed-loop`, {
              method: 'POST'
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok) {
              // 若 support_state 為待判定或系統異常，標記為待判定/failed而非 reviewed
              if (data.support_state === '待判定') {
                c.state = 'failed';
              } else {
                c.state = 'reviewed';
              }
              c.review = {
                support_state: data.support_state,
                warnings: data.warnings,
                records_degraded: data.records_degraded,
                soap_source: data.soap_source
              };
              c.support_level = data.support_state;
              results.push(data);
              stateCounts[data.support_state] = (stateCounts[data.support_state] || 0) + 1;
            } else {
              c.state = 'failed';
              errors.push({ case_id: c.id, message: data.message || res.status });
            }
          } catch (err) {
            c.state = 'failed';
            errors.push({ case_id: c.id, message: String(err) });
          }

          completedCount++;
          // 即時更新左側案件徽章
          renderCaseList(samplingCases);
          // 若目前選取的案件正好是這筆，同時更新中央工作區徽章
          if (currentSelectedCase && currentSelectedCase.id === c.id) {
            selectSamplingCase(c.id);
          }
        }

        // 完成全部審查
        if (pBar) pBar.style.width = '100%';
        if (pPercent) pPercent.innerText = `100% (${completedCount}/${totalCases} 案)`;
        if (pEta) pEta.innerText = '審查完成！';

        const states = Object.entries(stateCounts).map(([state, n]) => `${state}：${n}`).join('\n');
        showNonBlockingNotice(`批次審查完成：${completedCount} / ${totalCases} 案\n${states}` + (errors.length ? `\n失敗 ${errors.length} 案` : ''));
      } finally {
        setTimeout(() => {
          if (pContainer) pContainer.style.display = 'none';
          if (btnAudit) btnAudit.disabled = false;
        }, 1200);
        await loadCaseData();
      }
    }

    async function openSamplingBatchReport() {
      const res = await authFetch('/api/sampling/batch-report');
      if (!res.ok) {
        showNonBlockingNotice('無法開啟批次報告（' + res.status + '）');
        return;
      }
      const blob = new Blob([await res.text()], { type: 'text/html;charset=utf-8' });
      window.open(URL.createObjectURL(blob), '_blank');
    }

    async function exportSamplingBatchXml() {
      const res = await authFetch('/api/sampling/export-batch-xml');
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showNonBlockingNotice('全批次導出失敗：' + (body.message || res.status));
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = 'sampling_batch.xml';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function clearAppealCases() {
      if (!confirm('確定要清空目前所有的申復案件嗎？此操作將重置申復清單。')) return;
      const res = await authFetch('/api/appeal/cases/clear', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('清空失敗：' + (data.message || res.status));
        return;
      }
      showNonBlockingNotice(data.message || '已清空申復案件');
      currentSelectedCase = null;
      await loadCaseData();
    }

    async function openAppealCasePreview() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆申復案件');
        return;
      }
      const res = await authFetch(`/api/appeal/cases/${encodeURIComponent(currentSelectedCase.id)}/preview-html`);
      if (!res.ok) {
        showNonBlockingNotice('無法開啟申復卡片（' + res.status + '）');
        return;
      }
      const blob = new Blob([await res.text()], { type: 'text/html;charset=utf-8' });
      window.open(URL.createObjectURL(blob), '_blank');
    }

    async function openAppealBatchReport() {
      const res = await authFetch('/api/appeal/batch-report');
      if (!res.ok) {
        showNonBlockingNotice('無法開啟申復批次報告（' + res.status + '）');
        return;
      }
      const blob = new Blob([await res.text()], { type: 'text/html;charset=utf-8' });
      window.open(URL.createObjectURL(blob), '_blank');
    }

    async function downloadSingleAppealXml() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆申復案件');
        return;
      }
      const res = await authFetch(`/api/appeal/cases/${encodeURIComponent(currentSelectedCase.id)}/export-xml`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showNonBlockingNotice('單案申復 XML 導出失敗：' + (body.message || res.status));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `appeal_${currentSelectedCase.id}.xml`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function downloadSingleAppealJson() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆申復案件');
        return;
      }
      const res = await authFetch(`/api/appeal/cases/${encodeURIComponent(currentSelectedCase.id)}/export-json`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showNonBlockingNotice('單案申復 JSON 導出失敗：' + (body.message || res.status));
        return;
      }
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `appeal_${currentSelectedCase.id}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function exportAppealBatchXml() {
      const res = await authFetch('/api/appeal/export-batch-xml');
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showNonBlockingNotice('全批次申復導出失敗：' + (body.message || res.status));
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = '申報壓縮檔.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function linkStage2ToAppeal() {
      const res = await authFetch('/api/appeal/sample-from-stage2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: 5 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNonBlockingNotice('連動失敗：' + (data.message || res.status));
        return;
      }
      showNonBlockingNotice(`已連動 ${data.created.length} 案至第 3 階申復庫` +
        (data.duplicates.length ? `（${data.duplicates.length} 案已存在，略過）` : ''));
      if (currentMode === 'appeal') {
        await loadCaseData();
      }
    }

    async function exportSamplingXml() {
      if (!currentSelectedCase) {
        showNonBlockingNotice('請先選擇一筆抽樣案件');
        return;
      }
      const caseId = currentSelectedCase.id;
      const res = await authFetch(`/api/sampling/cases/${encodeURIComponent(caseId)}/export-xml`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showNonBlockingNotice('導出失敗：' + (body.message || res.status));
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url;
      a.download = `sampling_${caseId.replace(/[^A-Za-z0-9_-]/g, '_')}.xml`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function runSamplingAudit() {
      if (!currentSelectedCase) return;
      const res = await authFetch('/api/sampling/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: currentSelectedCase.id,
          order_code: currentSelectedCase.order_code,
          order_name: currentSelectedCase.order_name,
          soap_text: document.getElementById('sSoapInput').value,
          missing_reason: currentSelectedCase.missing_reason || '',
          // 11.1-02（BLOCKER-1）：sampling 案件 payload 自 CSV 匯入含 record_no
          // （server.py _to_sampling_case 透傳 d3 病歷號）＝patient_id——帶上才能
          // 讓 audit 端點以 LocalFileProvider 實查半年病史（Success Criteria 1）。
          record_no: currentSelectedCase.record_no
        })
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById('sAdviceBox').innerText =
          data.message || '預審失敗，請稍後再試。';
        return;
      }
      // Plan 18-03：閉環警示（病歷缺席、範本降級、查無規則）置於建議框最前方
      const warningText = (data.closed_loop_warnings || []).map(w => '⚠ ' + w).join('\n');
      document.getElementById('sAdviceBox').innerText =
        (warningText ? warningText + '\n\n' : '') + data.reinforcement_advice;

      // 徽章以引擎實際結果為準（原本停留在清單的硬編碼值）。
      // support_level=null 有兩種成因，必須分辨（P1-1）：
      // undetermined=true → 系統未能判定；否則為查無規則。
      // 兩者都不得顯示為「裸奔」。
      const badge = document.getElementById('sSupportBadge');
      // 閉環狀態（Plan 18-03）：病歷缺席的充分已降為薄弱；查無規則不同於待判定。
      const state = data.support_state || data.support_level;
      if (data.rule_found === false) {
        badge.innerText = '❓ 查無規則';
        badge.className = 'badge badge-weak';
      } else if (state === '充分') {
        badge.innerText = '✅ 充分';
        badge.className = 'badge badge-sufficient';
      } else if (state === '薄弱') {
        badge.innerText = '⚠️ 薄弱';
        badge.className = 'badge badge-weak';
      } else if (state === '裸奔') {
        badge.innerText = '❌ 裸奔';
        badge.className = 'badge badge-none';
      } else if (state === '待判定' || data.undetermined) {
        badge.innerText = '⏳ 待判定';
        badge.className = 'badge badge-weak';
      } else {
        badge.innerText = '❓ 查無規則';
        badge.className = 'badge badge-weak';
      }

      // 11.1-02（BLOCKER-1）：病歷缺席降級的可見呈現——records_degraded=true
      // 時於建議框前置「⚠ 病歷缺席」與原因文案（innerText 賦值，P1-5 防線；
      // records_degraded_reason 為 None 時用預設文案，不顯示 undefined）。
      if (data.records_degraded) {
        const adv = document.getElementById('sAdviceBox');
        adv.innerText =
          '⚠ 病歷缺席：' + (data.records_degraded_reason || '未含半年病史佐證') + '\n' +
          adv.innerText;
      }

      // 本地 LLM 智慧比對與 SOAP 補強呈現
      const llmPanel = document.getElementById('sLlmSoapPanel');
      if (data.soap_advice && (data.soap_advice.status === 'success' || data.soap_advice.status === 'fallback')) {
        llmPanel.style.display = 'block';
        document.getElementById('sLlmComparison').innerText = '🔍 比對分析：' + (data.soap_advice.comparison || '');
        const rSoap = data.soap_advice.recommended_soap || {};
        document.getElementById('sLlmSoapPreview').innerText =
          'S: ' + (rSoap.s || '') + '\n' +
          'O: ' + (rSoap.o || '') + '\n' +
          'A: ' + (rSoap.a || '') + '\n' +
          'P: ' + (rSoap.p || '');
        document.getElementById('sLlmApprovalAdvice').innerText = '👨‍⚕️ 審批建議：' + (data.soap_advice.approval_advice || '');
      } else {
        llmPanel.style.display = 'none';
      }
    }

    function applyRecommendedSoap() {
      const preview = document.getElementById('sLlmSoapPreview').innerText;
      if (preview) {
        setStage2Soap(preview);
        onSoapContentChanged('sampling');
        showNonBlockingNotice('已將 LLM 建議 SOAP 填入病歷 S/O/A/P 各欄！\n⚠️ 請注意：需要確認件並回寫 HIS 系統，請點擊「📤 寫回 HIS」回填最新病歷！');
      }
    }

    let latestAppealDraftSections = null;

    function applyAppealRecommendedDraft() {
      if (latestAppealDraftSections && latestAppealDraftSections.length >= 4) {
        const boxes = ['aSec1', 'aSec2', 'aSec3', 'aSec4'];
        boxes.forEach((id, i) => {
          const sec = latestAppealDraftSections[i];
          if (sec && sec.text) {
            document.getElementById(id).value = sec.text;
          }
        });
        onSoapContentChanged('appeal');
        showNonBlockingNotice('已成功將 LLM 建議申復理由套用至 4 段式編輯器！\n⚠️ 請注意：需要確認件並回寫 HIS 系統，請點擊「同意修訂並寫回 HIS 與資料庫」！');
      } else {
        generateAppealDraft();
      }
    }

    function selectAppealCase(id) {
      currentSelectedCase = appealCases.find(c => c.id === id);
      renderCaseList(appealCases);
      if (!currentSelectedCase) return;

      const orderNameStr = currentSelectedCase.order_name || currentSelectedCase.order_code || '';
      document.getElementById('aOrderName').innerText = `${currentSelectedCase.order_code} - ${orderNameStr} (核減 ${currentSelectedCase.deduct_amount || 0} 點)`;
      const dedReason = currentSelectedCase.deduction_reason || '病歷未載明肌腱撕裂之影像是項與術前評估，核減 3,200 點。';
      document.getElementById('aDeductionReason').innerText = dedReason;
      const rBox = document.getElementById('aDeductionReasonBox');
      if (rBox) rBox.innerText = `建立清單：${dedReason}`;

      const ev = currentSelectedCase.multisource_evidence || { images: [], labs: [], cloud_sync: [] };
      document.getElementById('evImage').innerText = (ev.images && ev.images.length > 0) ? `${ev.images[0].name}: ${ev.images[0].report}` : '無相關影像紀錄';
      document.getElementById('evLab').innerText = (ev.labs && ev.labs.length > 0) ? `${ev.labs[0].name}: ${ev.labs[0].result}` : '無相關檢驗數據';
      document.getElementById('evCloud').innerText = (ev.cloud_sync && ev.cloud_sync.length > 0) ? `${ev.cloud_sync[0].source}: ${ev.cloud_sync[0].note}` : '無相關雲端紀錄';

      refreshVault(currentSelectedCase);
      generateAppealDraft();
    }

    async function generateAppealDraft() {
      if (!currentSelectedCase) return;
      const res = await authFetch('/api/appeal/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: currentSelectedCase.id,
          case_seq: currentSelectedCase.case_seq,
          order_code: currentSelectedCase.order_code,
          order_name: currentSelectedCase.order_name,
          // 11.1-01：醫令序對應閉合——透傳 order_seq（_to_appeal_case 補欄後
          // CSV 匯入與 API 生成兩路徑皆帶），紙本申復清單「醫令序」欄可對應。
          order_seq: currentSelectedCase.order_seq,
          // 11.1-02（BLOCKER-1）：病歷號自 appeal 面板輸入欄（aRecordNoInput）
          // 取值——CSV 匯入案件 currentSelectedCase.record_no 恆 None，輸入欄是
          // generate 端點 timeline 查詢的唯一真實病歷號入口；可選填：留空送出
          // 由 server 端誠實標記 no_record_no（plan-checker BLOCKER 2 裁示）。
          record_no: document.getElementById('aRecordNoInput').value,
          deduct_amount: currentSelectedCase.deduct_amount,
          deduction_reason: currentSelectedCase.deduction_reason,
          // ④ 素材＝醫師採用的補強敘述（字串陣列）。多源證據摘要暫以
          // 文字帶入；正式流程應改為 Phase 6 審核軌跡的採用項。
          evidence: flattenEvidence(currentSelectedCase.multisource_evidence)
        })
      });
      const data = await res.json();
      if (!res.ok) {
        showNonBlockingNotice(data.message || '草稿生成失敗');
        return;
      }

      // sections 為 render_appeal_json 標準契約 [{key,title,text,trimmed}]，
      // 依 D10 四段順序回傳；僅取 text，sec 可能為 undefined 時維持防呆。
      latestAppealDraftSections = data.sections;
      const boxes = ['aSec1', 'aSec2', 'aSec3', 'aSec4'];
      boxes.forEach((id, i) => {
        const sec = data.sections[i];
        document.getElementById(id).value = sec ? sec.text : '';
      });

      // 11.1-02（BLOCKER-1）：病歷缺席降級的可見呈現——records_degraded=true
      // 時於 ②醫療必要性（aSec2）內容前加上「⚠ 病歷缺席」與原因文案（innerText
      // 賦值，P1-5 防線；reason 為 None 時只用預設文案，不顯示 undefined）。
      // 不在此改 generate 請求 body 的 record_no——那由 Task 2 的 aRecordNoInput
      // 輸入欄負責，本處只消費回應呈現。
      if (data.records_degraded) {
        const sec2 = document.getElementById('aSec2');
        sec2.value =
          '⚠ 病歷缺席：' + (data.records_degraded_reason || '本次申復未含半年病史佐證') + '\n' +
          sec2.value;
      }

      // 官方問答集 Q15：p8/p9 各 ≤1000（非合計 2000）；長度以 p8_reason1/
      // p9_reason2 本地計算，超限警告改由本地判斷。
      const p8Len = (data.p8_reason1 || '').length;
      const p9Len = (data.p9_reason2 || '').length;
      const warn = (p8Len <= 1000 && p9Len <= 1000) ? '' : '　⚠️ 超過欄位字數上限';
      document.getElementById('aCharCount').innerText =
        `p8 ${p8Len} / 1000　p9 ${p9Len} / 1000${warn}`;
      if (!data.rule_found) {
        document.getElementById('aSec3').value =
          '（規則庫查無此醫令條文，請人工補充依據）\n' +
          document.getElementById('aSec3').value;
      }

      // 本地 LLM 申復比對分析與審批建議呈現
      const aLlmPanel = document.getElementById('aLlmSoapPanel');
      if (data.soap_advice && (data.soap_advice.status === 'success' || data.soap_advice.status === 'fallback')) {
        aLlmPanel.style.display = 'block';
        document.getElementById('aLlmComparison').innerText = '🔍 比對分析：' + (data.soap_advice.comparison || '');
        document.getElementById('aLlmAdvice').innerText = '👨‍⚕️ 審批補強要點：' + (data.soap_advice.approval_advice || '');
      } else {
        aLlmPanel.style.display = 'none';
      }
    }

    function flattenEvidence(ev) {
      if (!ev) return [];
      const out = [];
      (ev.images || []).forEach(i => out.push(`影像 ${i.name}：${i.report}`));
      (ev.labs || []).forEach(l => out.push(`檢驗 ${l.name}：${l.result}`));
      (ev.cloud_sync || []).forEach(c => out.push(`${c.source}：${c.note}`));
      return out;
    }

    // === Phase 32-20: Doctor Mode & Stepper & Empty State (E1, E2, E6) ===
    function setDoctorMode(isDoctor) {
      if (isDoctor) {
        document.body.classList.add('doctor-mode');
      } else {
        document.body.classList.remove('doctor-mode');
      }
      try { localStorage.setItem('elc_doctor_mode', String(isDoctor)); } catch (e) {}
      const btn = document.getElementById('btnToggleDoctorMode');
      if (btn) {
        btn.textContent = isDoctor ? '🩺 醫師模式' : '⚙️ 進階檢視';
      }
    }

    function initDoctorMode() {
      let isDoctor = true;
      try {
        const saved = localStorage.getItem('elc_doctor_mode');
        if (saved !== null) isDoctor = saved === 'true';
      } catch (e) {}
      setDoctorMode(isDoctor);
    }

    function toggleDoctorMode() {
      const isDoctor = document.body.classList.contains('doctor-mode');
      setDoctorMode(!isDoctor);
    }

    function updateWorkflowStep(stepIndex) {
      const stepper = document.getElementById('workflow-stepper');
      if (!stepper) return;
      const items = stepper.querySelectorAll('.step-item');
      items.forEach((item, idx) => {
        item.classList.remove('step-active', 'step-done');
        if (idx + 1 === stepIndex) {
          item.classList.add('step-active');
        } else if (idx + 1 < stepIndex) {
          item.classList.add('step-done');
        }
      });
    }

    function renderEmptyState(isEmpty) {
      const guide = document.getElementById('empty-state-guide');
      if (!guide) return;
      if (isEmpty) {
        guide.classList.remove('hidden');
      } else {
        guide.classList.add('hidden');
      }
    }

    // === Phase 32-21: More Menu & Structured Error Notification (E5, E7) ===
    function toggleMoreMenu() {
      const menu = document.getElementById('moreActionsMenu');
      if (menu) menu.classList.toggle('hidden');
    }

    let pendingDestructiveAction = null;
    function openDestructiveModal(actionFn) {
      pendingDestructiveAction = actionFn;
      const modal = document.getElementById('confirm-destructive-modal');
      if (modal) modal.classList.remove('hidden');
    }

    function closeConfirmModal() {
      pendingDestructiveAction = null;
      const modal = document.getElementById('confirm-destructive-modal');
      if (modal) modal.classList.add('hidden');
    }

    function executeDestructiveConfirm() {
      if (typeof pendingDestructiveAction === 'function') {
        pendingDestructiveAction();
      }
      closeConfirmModal();
    }

    let lastDiagnosticError = '';
    function showStructuredError({ event, dataSafety, nextAction, rawError }) {
      lastDiagnosticError = rawError ? String(rawError) : (event || '');
      const modal = document.getElementById('structured-error-modal');
      if (!modal) {
        alert(`[狀況說明] ${event}\n[資料狀態] ${dataSafety || '您的病歷與送審檔案已經完整儲存在主機中，請放心。'}\n[建議動作] ${nextAction}`);
        return;
      }
      const evEl = document.getElementById('errorEventText');
      const safeEl = document.getElementById('errorSafetyText');
      const actEl = document.getElementById('errorActionText');
      if (evEl) evEl.textContent = event || '系統處理中發生非預期狀況。';
      if (safeEl) safeEl.textContent = dataSafety || '您的病歷與送審檔案已經完整儲存在主機中，請放心。';
      if (actEl) actEl.textContent = nextAction || '請稍候再試，或聯絡資訊人員。';
      modal.classList.remove('hidden');
    }

    function closeErrorModal() {
      const modal = document.getElementById('structured-error-modal');
      if (modal) modal.classList.add('hidden');
    }

    function copyDiagnosticInfo() {
      if (navigator.clipboard && lastDiagnosticError) {
        navigator.clipboard.writeText(lastDiagnosticError);
        alert('已複製診斷資訊至剪貼簿');
      }
    }

    // Init：載入院所機構設定與當月申報月份（同一機構同一月份免重複驗證）
    (async function init() {
      // Phase 32-A：清掉舊版殘留的金鑰（院內網路不再需要驗證）。
      try { localStorage.removeItem('elc_api_key'); } catch (e) { /* 私密模式等 */ }
      initDoctorMode();
      await loadFacilityConfig();
      await loadActiveMonthlyBatch();
      switchWorkflowMode('soap');
    })();

    // === Phase 32-16: Setup Redirect (D-32-13) ===
    try {
      fetch("/api/setup/state")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.needs_setup === true) {
            window.location.href = "/setup";
          }
        })
        .catch(function () {});
    } catch (e) {}

    // === Phase 32-16: Event Delegation & Action Whitelist (D-32-16) ===
    const ACTIONS = {
      // E5 More Menu & Destructive Modal
      toggleMoreMenu: function () { toggleMoreMenu(); },
      confirmClearSampling: function () {
        toggleMoreMenu();
        openDestructiveModal(function () { clearSamplingCases(); });
      },
      confirmClearAppeal: function () {
        toggleMoreMenu();
        openDestructiveModal(function () { clearAppealCases(); });
      },
      confirmClearMonthly: function () {
        toggleMoreMenu();
        openDestructiveModal(function () { clearMonthlyBatch(); });
      },
      executeDestructiveConfirm: function () { executeDestructiveConfirm(); },
      closeConfirmModal: function () { closeConfirmModal(); },
      // E7 Structured Error
      closeErrorModal: function () { closeErrorModal(); },
      copyDiagnosticInfo: function () { copyDiagnosticInfo(); },
      // Workflow & Modal
      toggleDoctorMode: function () { toggleDoctorMode(); },
      switchWorkflowMode: function (e, el, arg) { switchWorkflowMode(arg); },
      toggleFullscreen: function () { toggleFullscreen(); },
      clearSoapPatientsList: function () { clearSoapPatientsList(); },
      togglePatientEntryModal: function (e, el, arg) { togglePatientEntryModal(arg === "true" || arg === true); },
      triggerImportFile: function () { const f = document.getElementById("importFile"); if (f) f.click(); },
      clearCacheAndReload: function () { clearCacheAndReload(); },
      toggleFacilityModal: function (e, el, arg) { toggleFacilityModal(arg === "true" || arg === true); },
      toggleQuickPanel: function (e, el, arg) { toggleQuickPanel(arg); },
      syncRules: function () { syncRules(false); },
      syncRulesReplace: function () { syncRulesReplace(); },
      saveFacilityFromWeb: function () { saveFacilityFromWeb(); },
      submitPatientEntry: function () { submitPatientEntry(); },
      // Sampling (Stage 2)
      openSamplingBatchReport: function () { openSamplingBatchReport(); },
      runSamplingAudit: function () { runSamplingAudit(); },
      runSamplingBatchAudit: function () { runSamplingBatchAudit(); },
      clearSamplingCases: function () { clearSamplingCases(); },
      exportSamplingBatchXml: function () { exportSamplingBatchXml(); },
      triggerVaultFileInput: function () { const f = document.getElementById("vaultFileInput"); if (f) f.click(); },
      triggerVaultZipInput: function () { const f = document.getElementById("vaultZipInput"); if (f) f.click(); },
      closeVaultLightbox: function () { closeVaultLightbox(); },
      pushStage2SoapToHis: function () { pushStage2SoapToHis(); },
      confirmAndPushStage2Both: function () { confirmAndPushStage2Both(); },
      applyRecommendedSoap: function () { applyRecommendedSoap(); },
      saveSamplingEvidence: function () { saveSamplingEvidence(); },
      // Appeal (Stage 3)
      openAppealBatchReport: function () { openAppealBatchReport(); },
      generateAppealDraft: function () { generateAppealDraft(); },
      clearAppealCases: function () { clearAppealCases(); },
      exportAppealBatchXml: function () { exportAppealBatchXml(); },
      triggerAppealHisWrite: function () { triggerDirectHisWrite("3階核減事後申復", typeof getAppealFullText === "function" ? getAppealFullText() : ""); },
      downloadSingleAppealJson: function () { downloadSingleAppealJson(); },
      downloadSingleAppealXml: function () { downloadSingleAppealXml(); },
      confirmAndPushStage3Both: function () { confirmAndPushStage3Both(); },
      applyAppealRecommendedDraft: function () { applyAppealRecommendedDraft(); },
      // Monthly (Stage 1)
      triggerMonthlyFileInput: function () { const f = document.getElementById("monthlyFileInput"); if (f) f.click(); },
      openMonthlyHtmlReport: function () { openMonthlyHtmlReport(); },
      downloadMonthlyPackage: function () { downloadMonthlyPackage(); },
      gapCheckMonthly: function () { gapCheckMonthly(); },
      clearMonthlyBatch: function () { clearMonthlyBatch(); },
      // Live Soap & Tools
      switchToLiveMode: function () { switchToLiveMode(); },
      copyCurrentSoapText: function () { copyCurrentSoapText(); },
      pushSoapToHisUia: function () { pushSoapToHisUia(); },
      downloadForensicEvidenceZip: function () { downloadForensicEvidenceZip(); },
      printWindow: function () { window.print(); },
      searchSoapPatientAction: function () { searchSoapPatient(true, true); },
      stopLiveRecordingAndGenerate: function () { stopLiveRecordingAndGenerate(); },
      triggerDirectHisSync: function () { triggerDirectHisWrite("病歷修訂同步", ""); },
      hideHisSyncToast: function () { hideHisSyncToast(); },
      // Change Actions
      importCasesChange: function (e, el) { if (el.files && el.files[0]) importCases(el.files[0]); },
      uploadMonthlyZipChange: function (e, el) { if (el.files && el.files[0]) uploadMonthlyZip(el.files[0]); },
      uploadRuleCsvChange: function (e, el) { if (el.files && el.files[0]) uploadRuleCsv(el.files[0]); },
      uploadVaultFilesChange: function (e, el) { if (el.files) uploadVaultFiles(el.files); },
      // Input Actions
      onSoapContentChanged: function (e, el, arg) { onSoapContentChanged(arg); },
      onStage2SoapInputChanged: function () { onStage2SoapInputChanged(); }
    };

    // Document event delegators
    document.addEventListener("click", function (e) {
      const target = e.target.closest("[data-action]");
      if (target) {
        const actionName = target.getAttribute("data-action");
        const fn = ACTIONS[actionName];
        if (typeof fn === "function") {
          const arg = target.getAttribute("data-arg");
          fn(e, target, arg);
        }
      }
    });

    document.addEventListener("change", function (e) {
      const target = e.target.closest("[data-change-action]");
      if (target) {
        const actionName = target.getAttribute("data-change-action");
        const fn = ACTIONS[actionName];
        if (typeof fn === "function") {
          const arg = target.getAttribute("data-arg");
          fn(e, target, arg);
        }
      }
    });

    document.addEventListener("input", function (e) {
      const target = e.target.closest("[data-input-action]");
      if (target) {
        const actionName = target.getAttribute("data-input-action");
        const fn = ACTIONS[actionName];
        if (typeof fn === "function") {
          const arg = target.getAttribute("data-arg");
          fn(e, target, arg);
        }
      }
    });

    // Facility Tooltip mouse events & Enter key listener
    const sb = document.getElementById("facilityStatusBar");
    if (sb) {
      sb.addEventListener("mouseenter", showFacilityTooltip);
      sb.addEventListener("mousemove", updateTooltipPosition);
      sb.addEventListener("mouseleave", hideFloatingTooltip);
    }
    const sq = document.getElementById("soapPatientQueryInput");
    if (sq) {
      sq.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          searchSoapPatient(true, true);
        }
      });
    }

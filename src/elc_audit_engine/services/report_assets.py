"""統一報告與當月申報報告共用的樣式與前端腳本（Phase 22-04，消除重複定義）。

- SHARED_CSS：SOAP 範例、複製按鈕、彈窗按鈕、佐證庫方塊。兩份報告共用同一定義。
- SHARED_SCRIPT：複製 SOAP、開啟範例病歷彈窗，以及彈窗按鈕的事件委派。
- soap_modal_button：產生彈窗按鈕。參數改以 data 屬性傳遞並經 HTML 轉義，
  不再把值嵌入 onclick 的 JavaScript 字串（修正 P1-18 onclick 注入）。
"""

from __future__ import annotations

from html import escape

SHARED_CSS = """
details.soap-example { margin-top: 8px; }
details.soap-example > summary { cursor: pointer; color: var(--accent); font-size: 13px; font-weight: 600; }
textarea.soap-text { width: 100%; min-height: 150px; font: 12px/1.6 monospace; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink, var(--fg)); resize: vertical; }
.soap-actions { display: flex; gap: 10px; align-items: center; margin-top: 4px; }
button.btn-copy { background: #10b981; color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
button.btn-soap-modal { background: var(--accent, #0284c7); color: #fff; border: none; border-radius: 4px; padding: 4px 10px; font-size: 12px; font-weight: 600; cursor: pointer; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; }
button.btn-soap-modal:hover { opacity: 0.9; }
.vault-box { margin: 8px 0; padding: 8px 12px; background: var(--card); border: 1px solid var(--line); border-radius: 6px; font-size: 13px; }
.vault-title { font-weight: 600; color: var(--accent); margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
.vault-files { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.vault-file-item { display: inline-flex; align-items: center; gap: 4px; background: var(--bg); padding: 2px 8px; border-radius: 4px; font-size: 12px; border: 1px solid var(--line); }
"""

SHARED_SCRIPT = """
function copySoap(btn){
  var scope=btn.closest('.soap-box')||btn.closest('.card')||btn.closest('.item');
  var t='';
  if(scope){
    var ta=scope.querySelector('textarea.soap-text');
    if(ta){
      ta.select();
      t=ta.value;
    } else {
      var grid=scope.querySelector('.soap-grid');
      if(grid){t=grid.innerText;}
    }
  }
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(function(){btn.textContent='已複製';},function(){btn.textContent='請手動複製';});
  } else {
    var ok=false;
    try{ok=document.execCommand('copy');}catch(e){ok=false;}
    btn.textContent=ok?'已複製':'請手動複製';
  }
}
function openSoapModal(orderCode, diagCode, caseId) {
  if (window.parent && window.parent.generateExampleRecord) {
    window.parent.generateExampleRecord(orderCode, diagCode, caseId);
  } else if (typeof generateExampleRecord === 'function') {
    generateExampleRecord(orderCode, diagCode, caseId);
  } else {
    window.parent.postMessage({ type: 'OPEN_EX_MODAL', order_code: orderCode, primary_diagnosis: diagCode, case_id: caseId }, '*');
  }
}
document.addEventListener('click', function (e) {
  var btn = e.target.closest ? e.target.closest('.btn-soap-modal[data-order]') : null;
  if (btn) {
    openSoapModal(btn.getAttribute('data-order') || '', btn.getAttribute('data-diag') || '', btn.getAttribute('data-case') || '');
  }
});
"""


def soap_modal_button(order_code: str | None, primary_diagnosis: str | None, case_id: str | None) -> str:
    """範例病歷彈窗按鈕：值只進 data 屬性（經 HTML 轉義），由事件委派讀取，不嵌入 JavaScript 字串。"""
    return (
        '<button type="button" class="btn-soap-modal" '
        f'data-order="{escape(order_code or "", quote=True)}" '
        f'data-diag="{escape(primary_diagnosis or "", quote=True)}" '
        f'data-case="{escape(case_id or "", quote=True)}">'
        "🧾 範例病歷彈窗"
        "</button>"
    )

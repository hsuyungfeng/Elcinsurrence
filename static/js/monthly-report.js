/* 月報複製 SOAP（事件委派；app 直接回傳時以外部檔載入） */

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

document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-copy-soap]');if(b){copySoap(b);}});

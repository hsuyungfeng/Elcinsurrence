/* 統一審查報告：複製 SOAP、範例彈窗、影像燈箱（事件委派；app 直接回傳時以外部檔載入） */

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

document.addEventListener('click',function(e){
  var lb=document.getElementById('lb');
  if(!lb){return;}
  var tile=e.target.closest?e.target.closest('.tile img'):null;
  if(tile){
    lb.querySelector('img').src=tile.src;
    lb.querySelector('.cap').textContent=tile.alt||'';
    lb.hidden=false;
    return;
  }
  if(e.target.closest&&e.target.closest('#lb')){lb.hidden=true;}
});
document.addEventListener('keydown',function(e){
  var lb=document.getElementById('lb');
  if(lb&&e.key==='Escape'){lb.hidden=true;}
});

document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-copy-soap]');if(b){copySoap(b);}});

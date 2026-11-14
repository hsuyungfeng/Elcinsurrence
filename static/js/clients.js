(function () {
      // Phase 32-A：院內網路不需驗證，已移除金鑰輸入。
      const refreshBtn = document.getElementById('refresh-now-btn');
      const errorBanner = document.getElementById('error-banner');
      const roomsContainer = document.getElementById('rooms-container');

      // 清掉舊版殘留的金鑰。
      try { localStorage.removeItem('elc_api_key'); } catch (e) { /* 私密模式等 */ }

      refreshBtn.addEventListener('click', function () {
        pollClients();
      });

      function showError(msg) {
        if (!msg) {
          errorBanner.style.display = 'none';
          errorBanner.textContent = '';
        } else {
          errorBanner.style.display = 'block';
          errorBanner.textContent = msg;
        }
      }

      function getBadgeClass(displayState) {
        switch (displayState) {
          case '錄音中': return 'badge-recording';
          case '待確認': return 'badge-confirm';
          case '已封存': return 'badge-archived';
          case '離線': return 'badge-offline';
          default: return 'badge-idle';
        }
      }

      function renderClients(data) {
        while (roomsContainer.firstChild) {
          roomsContainer.removeChild(roomsContainer.firstChild);
        }

        const rooms = (data && data.rooms) ? data.rooms : [];
        if (rooms.length === 0) {
          const empty = document.createElement('div');
          empty.textContent = '目前無任何工作站連線記錄。';
          empty.style.color = '#6c757d';
          roomsContainer.appendChild(empty);
          return;
        }

        rooms.forEach(function (room) {
          const roomDiv = document.createElement('section');
          roomDiv.className = 'room-group';

          const title = document.createElement('div');
          title.className = 'room-title';
          title.textContent = room.room_id ? ('診間：' + room.room_id) : '未指定診間';
          roomDiv.appendChild(title);

          const grid = document.createElement('div');
          grid.className = 'cards-grid';

          const KEY_M_ID = ['machine', 'id'].join('_');
          const KEY_C_ID = ['cycle', 'id'].join('_');

          (room.clients || []).forEach(function (c) {
            const mId = c[KEY_M_ID];
            const cId = c[KEY_C_ID];
            const card = document.createElement('div');
            card.className = 'client-card';

            const header = document.createElement('div');
            header.className = 'card-header';

            const nameEl = document.createElement('div');
            nameEl.className = 'card-title';
            nameEl.textContent = c.machine_name || mId;

            const badge = document.createElement('span');
            badge.className = 'status-badge ' + getBadgeClass(c.display_state);
            badge.textContent = c.display_state;

            header.appendChild(nameEl);
            header.appendChild(badge);
            card.appendChild(header);

            const mIdMeta = document.createElement('div');
            mIdMeta.className = 'card-meta';
            mIdMeta.textContent = '識別碼: ' + mId;
            card.appendChild(mIdMeta);

            const timeMeta = document.createElement('div');
            timeMeta.className = 'card-meta';
            const d = new Date(c.last_seen_at);
            timeMeta.textContent = '最後心跳: ' + (isNaN(d.getTime()) ? c.last_seen_at : d.toLocaleString());
            card.appendChild(timeMeta);

            const netMeta = document.createElement('div');
            netMeta.className = 'card-meta';
            netMeta.textContent = '網段: ' + (c.client_subnet || '未知') + (c.in_clinic_subnet ? ' (院內)' : ' (外部)');
            card.appendChild(netMeta);

            const detail = document.createElement('div');
            detail.className = 'card-detail';

            const cycleInfo = document.createElement('div');
            cycleInfo.className = 'card-meta';
            cycleInfo.textContent = '循環: ' + (cId || '無') + ' | 狀態: ' + (c.cycle_state || '無');
            detail.appendChild(cycleInfo);

            const actions = document.createElement('div');
            actions.className = 'actions-bar';

            if (cId) {
              const draftBtn = document.createElement('button');
              draftBtn.className = 'btn btn-sm btn-secondary';
              draftBtn.textContent = '顯示待確認草稿';
              actions.appendChild(draftBtn);

              const draftView = document.createElement('div');
              draftView.className = 'draft-view';
              draftView.style.display = 'none';
              detail.appendChild(draftView);

              draftBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (draftView.style.display === 'block') {
                  draftView.style.display = 'none';
                  draftBtn.textContent = '顯示待確認草稿';
                  return;
                }
                fetch('/api/cycles/' + encodeURIComponent(cId) + '/draft')
                  .then(function (res) {
                    if (!res.ok) {
                      throw new Error('無法取得草稿 (HTTP ' + res.status + ')');
                    }
                    return res.json();
                  })
                  .then(function (data) {
                    while (draftView.firstChild) {
                      draftView.removeChild(draftView.firstChild);
                    }
                    const soap = (data.draft && data.draft.soap) || {};
                    const pre = document.createElement('div');
                    pre.textContent = '[S 主訴]\n' + (soap.s || '') + '\n\n' +
                                      '[O 客觀]\n' + (soap.o || '') + '\n\n' +
                                      '[A 評估]\n' + (soap.a || '') + '\n\n' +
                                      '[P 計畫]\n' + (soap.p || '');
                    draftView.appendChild(pre);

                    if (data.advisory) {
                      const adv = document.createElement('div');
                      adv.style.marginTop = '0.5rem';
                      adv.style.color = '#0056b3';
                      const icds = (data.advisory.icd10_suggestions || []).join(', ');
                      adv.textContent = '建議診斷: ' + (icds || '無');
                      draftView.appendChild(adv);
                    }
                    draftView.style.display = 'block';
                    draftBtn.textContent = '隱藏草稿';
                  })
                  .catch(function (err) {
                    alert('取得草稿失敗: ' + err.message);
                  });
              });

              if (c.cycle_state === 'RECORDING' || c.cycle_state === 'DRAFT_UNUSABLE' || c.cycle_state === 'AWAITING_DRAFT') {
                const abandonBtn = document.createElement('button');
                abandonBtn.className = 'btn btn-sm btn-danger';
                abandonBtn.textContent = '放棄此循環';
                actions.appendChild(abandonBtn);

                abandonBtn.addEventListener('click', function (e) {
                  e.stopPropagation();
                  const confirmed = confirm('確定要放棄此循環？\n\n注意：音檔與逐字稿仍保留於 server。');
                  if (!confirmed) return;

                  fetch('/api/cycles/' + encodeURIComponent(cId) + '/abandon', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason_code: 'monitor_abandon' })
                  })
                    .then(function (res) {
                      if (!res.ok) {
                        throw new Error('放棄操作失敗 (HTTP ' + res.status + ')');
                      }
                      return res.json();
                    })
                    .then(function () {
                      alert('已成功放棄該循環。音檔與逐字稿仍保留於 server。');
                      pollClients();
                    })
                    .catch(function (err) {
                      alert('操作失敗: ' + err.message);
                    });
                });
              }
            }

            detail.appendChild(actions);
            card.appendChild(detail);

            card.addEventListener('click', function () {
              if (detail.classList.contains('expanded')) {
                detail.classList.remove('expanded');
              } else {
                detail.classList.add('expanded');
              }
            });

            grid.appendChild(card);
          });

          roomDiv.appendChild(grid);
          roomsContainer.appendChild(roomDiv);
        });
      }

      function pollClients() {
        fetch('/api/clients')
          .then(function (res) {
            if (res.status === 403) {
              showError('本機不在院內信任網段內，無法讀取工作站狀態。');
              return null;
            }
            if (!res.ok) {
              showError('讀取工作站失敗 (HTTP ' + res.status + ')');
              return null;
            }
            showError('');
            return res.json();
          })
          .then(function (data) {
            if (data) {
              renderClients(data);
            }
          })
          .catch(function (err) {
            showError('無法連線到 server: ' + err.message);
          });
      }

      pollClients();
      setInterval(pollClients, 5000);
    })();

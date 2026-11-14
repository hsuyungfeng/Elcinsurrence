// Phase 32 Plan 13: 初次設定頁面互動邏輯 (setup.js)

document.addEventListener("DOMContentLoaded", () => {
    const alertBox = document.getElementById("alert-box");
    const statusDesc = document.getElementById("status-desc");
    const form = document.getElementById("setup-form");
    const codeInput = document.getElementById("facility-code");
    const nameInput = document.getElementById("facility-name");
    const physicianInput = document.getElementById("physician-name");
    const roomsContainer = document.getElementById("rooms-container");
    const btnAddRoom = document.getElementById("btn-add-room");
    const btnSubmit = document.getElementById("btn-submit");
    const successActions = document.getElementById("success-actions");

    const errCode = document.getElementById("err-code");
    const errName = document.getElementById("err-name");
    const errPhysician = document.getElementById("err-physician");
    const errRooms = document.getElementById("err-rooms");

    function clearErrors() {
        errCode.style.display = "none";
        errCode.textContent = "";
        errName.style.display = "none";
        errName.textContent = "";
        errPhysician.style.display = "none";
        errPhysician.textContent = "";
        errRooms.style.display = "none";
        errRooms.textContent = "";
    }

    function showAlert(msg, type) {
        alertBox.className = "alert alert-" + type;
        alertBox.textContent = msg;
        alertBox.style.display = "block";
    }

    function createRoomRow(idVal = "", nameVal = "") {
        const row = document.createElement("div");
        row.className = "room-row";

        const idInp = document.createElement("input");
        idInp.type = "text";
        idInp.className = "room-id-input";
        idInp.placeholder = "代號 (例：room-1)";
        idInp.value = idVal;

        const nameInp = document.createElement("input");
        nameInp.type = "text";
        nameInp.className = "room-name-input";
        nameInp.placeholder = "顯示名稱 (例：第 1 診)";
        nameInp.value = nameVal;

        const btnDel = document.createElement("button");
        btnDel.type = "button";
        btnDel.className = "btn btn-danger";
        btnDel.textContent = "刪除";
        btnDel.addEventListener("click", () => {
            if (roomsContainer.querySelectorAll(".room-row").length > 1) {
                row.remove();
            } else {
                showAlert("至少需要保留一個診間", "warning");
            }
        });

        row.appendChild(idInp);
        row.appendChild(nameInp);
        row.appendChild(btnDel);
        return row;
    }

    btnAddRoom.addEventListener("click", () => {
        const count = roomsContainer.querySelectorAll(".room-row").length + 1;
        const newRow = createRoomRow(`room-${count}`, `第 ${count} 診`);
        roomsContainer.appendChild(newRow);
    });

    // 載入設定狀態
    fetch("/api/setup/state")
        .then(res => res.json())
        .then(data => {
            if (!data.write_allowed) {
                showAlert(data.write_hint || "此設定只能在伺服器本機修改。", "warning");
                codeInput.disabled = true;
                nameInput.disabled = true;
                physicianInput.disabled = true;
                btnAddRoom.disabled = true;
                btnSubmit.disabled = true;
            }

            if (!data.needs_setup) {
                statusDesc.textContent = "已完成設定，可隨時在此檢視或修改設定。";
            }

            if (data.facility) {
                codeInput.value = data.facility.code || "";
                nameInput.value = data.facility.name || "";
                physicianInput.value = data.facility.physician_name || "";
            }

            roomsContainer.innerHTML = "";
            if (data.rooms && data.rooms.length > 0) {
                data.rooms.forEach(r => {
                    roomsContainer.appendChild(createRoomRow(r.id, r.name));
                });
            } else {
                roomsContainer.appendChild(createRoomRow("room-1", "第 1 診"));
            }
        })
        .catch(err => {
            showAlert("無法載入設定狀態：" + err.message, "warning");
        });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        clearErrors();

        const rooms = [];
        const rows = roomsContainer.querySelectorAll(".room-row");
        rows.forEach(r => {
            const id = r.querySelector(".room-id-input").value.trim();
            const name = r.querySelector(".room-name-input").value.trim();
            if (id || name) {
                rooms.push({ id, name });
            }
        });

        const payload = {
            code: codeInput.value.trim(),
            name: nameInput.value.trim(),
            physician_name: physicianInput.value.trim(),
            rooms: rooms
        };

        btnSubmit.disabled = true;
        btnSubmit.textContent = "儲存中...";

        fetch("/api/setup", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            body: JSON.stringify(payload)
        })
        .then(async res => {
            btnSubmit.disabled = false;
            btnSubmit.textContent = "完成設定";

            const data = await res.json();
            if (res.status === 200) {
                showAlert("設定完成！資料已成功寫入，各診間電腦現在可以連線。", "success");
                form.style.display = "none";
                successActions.style.display = "block";
            } else if (res.status === 403) {
                showAlert(data.message || "權限不足：此設定只能在伺服器本機修改。", "warning");
            } else if (res.status === 422) {
                if (data.errors) {
                    if (data.errors.code) {
                        errCode.textContent = data.errors.code;
                        errCode.style.display = "block";
                    }
                    if (data.errors.name) {
                        errName.textContent = data.errors.name;
                        errName.style.display = "block";
                    }
                    if (data.errors.physician_name) {
                        errPhysician.textContent = data.errors.physician_name;
                        errPhysician.style.display = "block";
                    }
                    if (data.errors.rooms) {
                        errRooms.textContent = data.errors.rooms;
                        errRooms.style.display = "block";
                    }
                } else {
                    showAlert(data.message || "輸入資料格式不正確", "warning");
                }
            } else {
                showAlert("儲存失敗：" + (data.message || res.statusText), "warning");
            }
        })
        .catch(err => {
            btnSubmit.disabled = false;
            btnSubmit.textContent = "完成設定";
            showAlert("連線失敗：" + err.message, "warning");
        });
    });
});

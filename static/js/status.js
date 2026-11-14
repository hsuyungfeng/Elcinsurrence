"use strict";

function updateStatus() {
    fetch("/api/status")
        .then(function(res) {
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        })
        .then(function(data) {
            renderStatus(data);
        })
        .catch(function(err) {
            console.error("Failed to fetch /api/status:", err);
            var badge = document.getElementById("overallBadge");
            if (badge) {
                badge.className = "overall-badge bg-red";
                badge.textContent = "無法連線";
            }
            var lastUpdated = document.getElementById("lastUpdated");
            if (lastUpdated) {
                lastUpdated.textContent = "最後更新失敗：" + err.message;
            }
        });
}

function renderStatus(data) {
    var overall = data.overall || "unknown";
    var badge = document.getElementById("overallBadge");
    if (badge) {
        badge.className = "overall-badge bg-" + overall;
        if (overall === "green") {
            badge.textContent = "全部正常";
        } else if (overall === "yellow") {
            badge.textContent = "注意";
        } else if (overall === "red") {
            badge.textContent = "需處理";
        } else {
            badge.textContent = "未明";
        }
    }

    var lastUpdated = document.getElementById("lastUpdated");
    if (lastUpdated) {
        var now = new Date();
        lastUpdated.textContent = "最後更新時間：" + now.toLocaleTimeString();
    }

    var container = document.getElementById("checksContainer");
    if (!container) return;

    container.innerHTML = "";
    var checks = data.checks || [];
    checks.forEach(function(item) {
        var card = document.createElement("div");
        card.className = "status-card";

        var info = document.createElement("div");
        info.className = "status-info";

        var indicator = document.createElement("span");
        indicator.className = "indicator bg-" + (item.color || "unknown");

        var textDiv = document.createElement("div");
        var nameDiv = document.createElement("div");
        nameDiv.className = "name";
        nameDiv.textContent = item.name || item.key;

        var msgDiv = document.createElement("div");
        msgDiv.className = "message";
        msgDiv.textContent = item.message || "";

        textDiv.appendChild(nameDiv);
        textDiv.appendChild(msgDiv);

        info.appendChild(indicator);
        info.appendChild(textDiv);
        card.appendChild(info);

        container.appendChild(card);
    });
}

document.addEventListener("DOMContentLoaded", function() {
    updateStatus();
    setInterval(updateStatus, 30000);
});

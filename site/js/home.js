ATM.renderStatus(document.getElementById("status"));
ATM.renderFeed(document.getElementById("latest-ann"), "data/announcements.json", "announcements", { limit: 3 });

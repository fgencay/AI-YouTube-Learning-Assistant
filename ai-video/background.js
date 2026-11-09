chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message.type === "KAYIT") {
    fetch("http://127.0.0.1:8000/api/kayit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        ad: message.ad,
        email: message.email,
        sifre: message.sifre
      })
    })
      .then((response) => response.json())
      .then((data) => {
        sendResponse({
          success: data.durum === "basarili",
          data: data,
          error: data.mesaj
        });
      })
      .catch((error) => {
        sendResponse({
          success: false,
          error: error.toString()
        });
      });

    return true;
  }

  if (message.type === "GIRIS") {
    fetch("http://127.0.0.1:8000/api/giris", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: message.email,
        sifre: message.sifre
      })
    })
      .then((response) => response.json())
      .then((data) => {
        sendResponse({
          success: data.durum === "basarili",
          data: data,
          error: data.mesaj
        });
      })
      .catch((error) => {
        sendResponse({
          success: false,
          error: error.toString()
        });
      });

    return true;
  }

  if (message.type === "METIN_CEK") {
    const userQuery = message.kullaniciId
      ? `?kullanici_id=${encodeURIComponent(message.kullaniciId)}`
      : "";

    fetch(`http://127.0.0.1:8000/api/metin-cek/${message.videoId}${userQuery}`)
      .then((response) => response.json())
      .then((data) => {
        sendResponse({
          success: true,
          data: data
        });
      })
      .catch((error) => {
        sendResponse({
          success: false,
          error: error.toString()
        });
      });

    return true;
  }

  if (message.type === "HEATMAP_GONDER") {
    fetch(`http://127.0.0.1:8000/api/heatmap-kaydet/${message.videoId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        heatmap: message.heatmapData,
        heatmap_unavailable: Boolean(message.heatmapUnavailable)
      })
    })
      .then((response) => response.json())
      .then((data) => {
        sendResponse({
          success: true,
          data: data
        });
      })
      .catch((error) => {
        sendResponse({
          success: false,
          error: error.toString()
        });
      });

    return true;
  }

});

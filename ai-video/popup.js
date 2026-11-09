let registerMode = false;
let currentUser = null;
let loginCountdownInterval = null;

function getElement(id) {
  return document.getElementById(id);
}

function setStatus(message, color) {
  const statusDiv = getElement("status");
  if (statusDiv) {
    statusDiv.innerText = message;
    statusDiv.style.color = color || "#2f3846";
  }
}

function clearLoginCountdown() {
  if (loginCountdownInterval) {
    clearInterval(loginCountdownInterval);
    loginCountdownInterval = null;
  }
}

function startLoginCountdown(seconds, message) {
  clearLoginCountdown();

  const loginBtn = getElement("loginBtn");
  let remaining = Math.max(1, Number(seconds) || 1);
  const errorMessage = message || "E-mail veya şifre hatalı";

  function updateCountdown() {
    if (remaining <= 0) {
      clearLoginCountdown();
      setStatus(errorMessage, "#B42318");

      if (loginBtn && !registerMode && !currentUser) {
        loginBtn.disabled = false;
        loginBtn.innerText = "Giriş Yap";
      }
      return;
    }

    setStatus(`${errorMessage}\nTekrar denemek için ${remaining} sn`, "#B42318");

    if (loginBtn) {
      loginBtn.disabled = true;
      loginBtn.innerText = `${remaining} sn`;
    }

    remaining -= 1;
  }

  updateCountdown();
  loginCountdownInterval = setInterval(updateCountdown, 1000);
}

function setAnalysisStatus(statusInfo) {
  const statusDiv = getElement("status");
  const analyzeBtn = getElement("analyzeBtn");

  if (!statusDiv || !analyzeBtn || !statusInfo) return;

  statusDiv.innerText = statusInfo.message || "Hazır.";
  statusDiv.style.color = "#2f3846";

  if (!currentUser) {
    analyzeBtn.style.display = "none";
    return;
  }

  analyzeBtn.style.display = "block";

  if (statusInfo.status === "running") {
    analyzeBtn.disabled = true;
    analyzeBtn.innerText = "Analiz Devam Ediyor";
  } else {
    analyzeBtn.disabled = false;
    analyzeBtn.innerText = "Analizi Başlat";
  }
}

function updateAuthView() {
  const loggedOutBox = getElement("loggedOutBox");
  const loggedInBox = getElement("loggedInBox");
  const userInfo = getElement("userInfo");
  const analyzeBtn = getElement("analyzeBtn");
  const startBtn = getElement("startBtn");
  const stopBtn = getElement("stopBtn");

  if (!loggedOutBox || !loggedInBox || !userInfo) return;

  if (currentUser) {
    loggedOutBox.style.display = "none";
    loggedInBox.style.display = "block";
    userInfo.innerText = `${currentUser.ad || "Kullanıcı"} (${currentUser.email})`;

    if (analyzeBtn) {
      analyzeBtn.style.display = "block";
      analyzeBtn.disabled = false;
      analyzeBtn.innerText = "Analizi Başlat";
    }
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = false;
  } else {
    loggedOutBox.style.display = "block";
    loggedInBox.style.display = "none";

    if (analyzeBtn) {
      analyzeBtn.style.display = "none";
      analyzeBtn.disabled = true;
    }
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = true;
  }
}

function setRegisterMode(enabled) {
  registerMode = enabled;

  const nameInput = getElement("nameInput");
  const loginBtn = getElement("loginBtn");
  const registerBtn = getElement("registerBtn");
  const showLoginBtn = getElement("showLoginBtn");

  if (nameInput) nameInput.style.display = enabled ? "block" : "none";
  if (loginBtn) loginBtn.style.display = enabled ? "none" : "block";
  if (showLoginBtn) showLoginBtn.style.display = enabled ? "block" : "none";
  if (registerBtn) {
    registerBtn.innerText = enabled ? "Kaydı Tamamla" : "Kayıt Ol";
    registerBtn.className = enabled ? "" : "secondary-btn";
  }

  setStatus(enabled ? "Kayıt bilgilerini gir." : "Hazır.");
}

function saveUser(user) {
  clearLoginCountdown();

  currentUser = {
    kullanici_id: user.kullanici_id,
    ad: user.ad || "",
    email: user.email || ""
  };

  chrome.storage.local.set({ currentUser }, function () {
    updateAuthView();
    setRegisterMode(false);
    setStatus("Giriş yapıldı.");
  });
}

function sendAuthMessage(message, successMessage) {
  chrome.runtime.sendMessage(message, function (response) {
    if (chrome.runtime.lastError) {
      setStatus("Backend'e ulaşılamadı. Sunucuyu kontrol et.", "#B42318");
      return;
    }

    if (!response || !response.success) {
      const waitSeconds = Number(response?.data?.bekleme_suresi || 0);
      const errorMessage = response?.error || response?.data?.mesaj || "E-mail veya şifre hatalı";

      if (message.type === "GIRIS" && waitSeconds > 0) {
        startLoginCountdown(waitSeconds, errorMessage);
        return;
      }

      setStatus(errorMessage || "İşlem başarısız oldu.", "#B42318");
      return;
    }

    saveUser(response.data);
    setStatus(successMessage);
  });
}

function login() {
  const email = getElement("emailInput")?.value.trim();
  const sifre = getElement("passwordInput")?.value;

  if (!email || !sifre) {
    setStatus("E-mail ve şifre gerekli.", "#B42318");
    return;
  }

  setStatus("Giriş yapılıyor...");
  sendAuthMessage(
    {
      type: "GIRIS",
      email,
      sifre
    },
    "Giriş başarılı."
  );
}

function register() {
  if (!registerMode) {
    setRegisterMode(true);
    return;
  }

  const ad = getElement("nameInput")?.value.trim();
  const email = getElement("emailInput")?.value.trim();
  const sifre = getElement("passwordInput")?.value;

  if (!ad || !email || !sifre) {
    setStatus("Ad, e-mail ve şifre gerekli.", "#B42318");
    return;
  }

  setStatus("Kayıt oluşturuluyor...");
  sendAuthMessage(
    {
      type: "KAYIT",
      ad,
      email,
      sifre
    },
    "Kayıt başarılı."
  );
}

function logout() {
  chrome.storage.local.remove("currentUser", function () {
    currentUser = null;
    updateAuthView();
    setRegisterMode(false);
    setStatus("Çıkış yapıldı.");
  });
}

function sendToActiveTab(message, statusText) {
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    if (!tabs || tabs.length === 0) {
      setStatus("Aktif sekme bulunamadı.", "#B42318");
      return;
    }

    chrome.tabs.sendMessage(tabs[0].id, message, function (response) {
      if (chrome.runtime.lastError) {
        setStatus("YouTube video sayfasında değilsin veya sayfayı yenilemen gerekiyor.", "#B42318");
        return;
      }

      setStatus(response?.message || statusText);
    });
  });
}

function startAnalysis() {
  if (!currentUser) {
    setStatus("Analiz için önce giriş yapmalısın.", "#B42318");
    return;
  }

  setAnalysisStatus({
    status: "running",
    message: "Analiz devam ediyor. Popup açık kalmasa da sonuç buraya yazılacak."
  });

  sendToActiveTab(
    { type: "ANALIZ_YAP" },
    "Analiz başlatıldı."
  );
}

function formatTime(seconds) {
  const dakika = Math.floor(seconds / 60);
  const saniye = Math.floor(seconds % 60);
  return `${dakika}:${saniye.toString().padStart(2, "0")}`;
}

function loadLastAnalysisToPopup() {
  chrome.storage.local.get("lastAnalysis", function (result) {
    const resultsDiv = getElement("results");

    if (!resultsDiv) return;

    if (!result.lastAnalysis) {
      resultsDiv.innerHTML = "<p>Henüz analiz sonucu yok.</p>";
      return;
    }

    const analysis = result.lastAnalysis;
    const segments = analysis.segments || [];
    const segmentCount = analysis.segmentCount ?? segments.length;

    let html = `
      <p><b>${segmentCount}</b> atlanacak bölüm bulundu.</p>
    `;

    segments.forEach((segment, index) => {
      const chapter = segment.chapter || "Chapter bilgisi yok";
      const source = segment.source === "cache"
        ? "Cache kaydı"
        : (segment.source || "Analiz kaynağı yok");
      const reason = segment.reason || "Atlama nedeni yok";
      const heatmapScore = segment.heatmap_score || 0;
      const heatmapText = heatmapScore > 0
        ? `heatmap: ${heatmapScore}`
        : "Heatmap eşleşmesi yok";

      html += `
        <div class="segment-item">
          <div class="segment-time">
            ${index + 1}) ${formatTime(segment.start)} - ${formatTime(segment.end)}
          </div>
          <div class="segment-chapter">
            ${chapter} | ${reason} | ${source} | ${heatmapText}
          </div>
        </div>
      `;
    });

    resultsDiv.innerHTML = html;
  });
}

document.addEventListener("DOMContentLoaded", function () {
  getElement("loginBtn")?.addEventListener("click", login);
  getElement("registerBtn")?.addEventListener("click", register);
  getElement("showLoginBtn")?.addEventListener("click", function () {
    setRegisterMode(false);
  });
  getElement("logoutBtn")?.addEventListener("click", logout);
  getElement("analyzeBtn")?.addEventListener("click", startAnalysis);
  getElement("startBtn")?.addEventListener("click", function () {
    sendToActiveTab(
      { type: "SKIP_BASLAT" },
      "Otomatik atlatma başlatıldı."
    );
  });
  getElement("stopBtn")?.addEventListener("click", function () {
    sendToActiveTab(
      { type: "SKIP_DURDUR" },
      "Otomatik atlatma durduruldu."
    );
  });

  chrome.storage.local.get(["currentUser", "lastAnalysisStatus"], function (result) {
    currentUser = result.currentUser || null;
    updateAuthView();
    setRegisterMode(false);

    if (result.lastAnalysisStatus) {
      setAnalysisStatus(result.lastAnalysisStatus);
    }
  });

  loadLastAnalysisToPopup();
});

chrome.storage.onChanged.addListener(function (changes, areaName) {
  if (areaName !== "local") return;

  if (changes.currentUser) {
    currentUser = changes.currentUser.newValue || null;
    updateAuthView();
  }

  if (changes.lastAnalysisStatus) {
    setAnalysisStatus(changes.lastAnalysisStatus.newValue);
  }

  if (changes.lastAnalysis) {
    loadLastAnalysisToPopup();
  }
});

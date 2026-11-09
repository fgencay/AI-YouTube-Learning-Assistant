console.log("AI Video Extension aktif");

let skippableParts = [];
let autoSkipInterval = null;
let lastSkippedSegmentKey = null;
let analysisReady = false;
let analysisInProgress = false;
let analysisVideoId = null;
const SKIP_EXIT_PADDING_SECONDS = 0.25;

function getVideoId() {
  const params = new URLSearchParams(window.location.search);
  return params.get("v");
}

function getVideoElement() {
  return document.querySelector("video");
}

function getHeatmapDataFromPage() {
  const video = getVideoElement();

  if (!video || !video.duration) {
    console.log("Video suresi alinamadi.");
    return [];
  }

  const heatmapPaths = document.querySelectorAll("path");
  console.log("Toplam path sayisi:", heatmapPaths.length);

  const parsedSegments = [];

  heatmapPaths.forEach((path, index) => {
    const d = path.getAttribute("d");

    if (!d) return;
    if (!d.includes("C") && !d.includes("M")) return;

    const numbers = d.match(/-?\d+(\.\d+)?/g);
    if (!numbers || numbers.length < 10) return;

    const numericValues = numbers.map(Number);
    const yValues = numericValues.filter((_, i) => i % 2 === 1);
    if (yValues.length === 0) return;

    const avgHeight = yValues.reduce((a, b) => a + b, 0) / yValues.length;

    parsedSegments.push({
      index: index,
      raw_height: Math.abs(avgHeight)
    });
  });

  console.log("Parsed segment sayisi:", parsedSegments.length);

  if (parsedSegments.length === 0) {
    console.log("Heatmap parse edilemedi.");
    return [];
  }

  const maxHeight = Math.max(...parsedSegments.map((x) => x.raw_height));
  const videoDuration = video.duration;

  const normalized = parsedSegments.map((segment, index) => {
    const start = (index / parsedSegments.length) * videoDuration;
    const end = ((index + 1) / parsedSegments.length) * videoDuration;
    const heatScore = segment.raw_height / maxHeight;

    return {
      start: Math.round(start),
      end: Math.round(end),
      heat_score: Number(heatScore.toFixed(2))
    };
  });

  const highHeatmapSegments = normalized
    .filter((x) => x.heat_score >= 0.65)
    .slice(0, 20);

  console.log("Yuksek heatmap segmentleri:", highHeatmapSegments);
  return highHeatmapSegments;
}

function heatmapDataWithRetry(maxAttempts, delayMs, callback) {
  let attempt = 1;

  function tryParseHeatmap() {
    const heatmapData = getHeatmapDataFromPage();

    if (heatmapData.length > 0 || attempt >= maxAttempts) {
      callback({
        heatmapData: heatmapData,
        heatmapUnavailable: heatmapData.length === 0,
        attempts: attempt
      });
      return;
    }

    attempt++;
    setTimeout(tryParseHeatmap, delayMs);
  }

  tryParseHeatmap();
}

function normalizeSegments(segments) {
  return (segments || [])
    .map((segment) => ({
      ...segment,
      start: Number(segment.start),
      end: Number(segment.end)
    }))
    .filter((segment) => Number.isFinite(segment.start) && Number.isFinite(segment.end) && segment.end > segment.start);
}

function saveAnalysis(videoId, segments, serverMessage) {
  skippableParts = normalizeSegments(segments);
  lastSkippedSegmentKey = null;
  analysisReady = true;
  const doneMessage = serverMessage || (skippableParts.length === 0
    ? "Bu videoda guvenle atlanacak gereksiz bolum bulunmadi. Video normal oynayacak."
    : `${skippableParts.length} atlanacak bolum bulundu. Analiz tamamlandi.`);

  chrome.storage.local.set({
    lastAnalysisStatus: {
      videoId: videoId,
      status: "done",
      message: doneMessage
    },
    lastAnalysis: {
      videoId: videoId,
      segmentCount: skippableParts.length,
      segments: skippableParts,
      analysisType: "skippable"
    }
  });

  console.log("Atlanacak kisimlar:", skippableParts);
}

function requestAnalysis(videoId, kullaniciId) {
  chrome.runtime.sendMessage(
    {
      type: "METIN_CEK",
      videoId: videoId,
      kullaniciId: kullaniciId
    },
    function (response) {
      if (!response || !response.success) {
        console.error("Backend baglanti hatasi:", response?.error);
        chrome.storage.local.set({
          lastAnalysisStatus: {
            videoId: videoId,
            status: "error",
            message: "Backend baglanti hatasi. Sunucu calisiyor mu kontrol et."
          }
        });
        analysisInProgress = false;
        analysisVideoId = null;
        return;
      }

      if (response.data?.durum === "hata") {
        console.error("Backend analiz hatasi:", response.data);
        chrome.storage.local.set({
          lastAnalysisStatus: {
            videoId: videoId,
            status: "error",
            message: response.data.mesaj || "Analiz sirasinda hata olustu."
          }
        });
        analysisInProgress = false;
        analysisVideoId = null;
        return;
      }

      console.log("Backend cevabi:", response.data);
      saveAnalysis(
        videoId,
        response.data?.atlanacak_kisimlar || response.data?.onemli_kisimlar || [],
        response.data?.mesaj
      );
      analysisInProgress = false;
      analysisVideoId = null;
    }
  );
}

function loadAnalysis() {
  const videoId = getVideoId();

  console.log("Video ID:", videoId);

  if (!videoId) {
    console.log("Video ID bulunamadi.");
    return;
  }

  chrome.storage.local.get("currentUser", function (result) {
    const currentUser = result.currentUser;

    if (!currentUser || !currentUser.kullanici_id) {
      chrome.storage.local.set({
        lastAnalysisStatus: {
          videoId: videoId,
          status: "error",
          message: "Analiz icin once eklentiye giris yapmalisin."
        }
      });
      return;
    }

    startLoggedInAnalysis(videoId, currentUser.kullanici_id);
  });
}

function startLoggedInAnalysis(videoId, kullaniciId) {
  if (analysisInProgress && analysisVideoId === videoId) {
    console.log("Bu video icin analiz zaten devam ediyor.");
    chrome.storage.local.set({
      lastAnalysisStatus: {
        videoId: videoId,
        status: "running",
        message: "Analiz zaten devam ediyor. Bitmesini bekle."
      }
    });
    return;
  }

  analysisInProgress = true;
  analysisVideoId = videoId;
  analysisReady = false;

  chrome.storage.local.set({
    lastAnalysisStatus: {
      videoId: videoId,
      status: "running",
      message: "Heatmap kontrol ediliyor..."
    }
  });

  heatmapDataWithRetry(5, 800, function (result) {
    chrome.storage.local.set({
      lastAnalysisStatus: {
        videoId: videoId,
        status: "running",
        message: result.heatmapUnavailable
          ? "Heatmap bulunamadi. Heatmapsiz analiz devam ediyor..."
          : "Heatmap bulundu. LLM analizi devam ediyor..."
      }
    });

    chrome.storage.local.set({
      lastHeatmap: result.heatmapData
    });

    chrome.runtime.sendMessage(
      {
        type: "HEATMAP_GONDER",
        videoId: videoId,
        heatmapData: result.heatmapData,
        heatmapUnavailable: result.heatmapUnavailable
      },
      function (heatmapResponse) {
        if (!heatmapResponse || !heatmapResponse.success) {
          console.warn("Heatmap backend'e gonderilemedi, analiz devam ediyor:", heatmapResponse?.error);
        } else {
          console.log("Heatmap backend cevabi:", heatmapResponse);
        }

        requestAnalysis(videoId, kullaniciId);
      }
    );
  });
}

function restoreLastAnalysisForCurrentVideo() {
  const videoId = getVideoId();

  if (!videoId) return;

  chrome.storage.local.get("lastAnalysis", function (result) {
    const analysis = result.lastAnalysis;

    if (!analysis || analysis.videoId !== videoId || !Array.isArray(analysis.segments)) {
      return;
    }

    skippableParts = normalizeSegments(analysis.segments);
    analysisReady = true;
    console.log("Kayitli atlanacak kisimlar yuklendi:", skippableParts);
  });
}

function seekVideoTo(video, targetTime) {
  const safeTargetTime = Number(targetTime);

  if (!Number.isFinite(safeTargetTime)) {
    return "invalid";
  }

  if (typeof video.fastSeek === "function") {
    try {
      video.fastSeek(safeTargetTime);
      return "fastSeek";
    } catch (error) {
      console.warn("fastSeek basarisiz oldu, currentTime kullaniliyor:", error);
    }
  }

  video.currentTime = safeTargetTime;
  return "currentTime";
}

function startAutoSkip() {
  const video = getVideoElement();

  if (!video) {
    console.log("Video elementi bulunamadi.");
    return { success: false, message: "Video elementi bulunamadi." };
  }

  if (!skippableParts || skippableParts.length === 0) {
    if (analysisReady) {
      console.log("Bu analizde atlanacak bolum bulunmadi. Video normal oynayacak.");
      return { success: true, message: "Atlanacak bolum yok. Video normal oynayacak." };
    }

    console.log("Atlanacak kisimlar henuz yuklenmedi. Once analiz baslatilmali.");
    return { success: false, message: "Once analizi baslat ve tamamlanmasini bekle." };
  }

  if (autoSkipInterval) {
    console.log("Otomatik atlatma zaten calisiyor.");
    return { success: true, message: "Otomatik atlatma zaten calisiyor." };
  }

  skippableParts.sort((a, b) => a.start - b.start);
  lastSkippedSegmentKey = null;

  console.log("Skippable otomatik atlatma basladi:", skippableParts);

  video.play();

  autoSkipInterval = setInterval(() => {
    const currentTime = video.currentTime;
    const currentPart = skippableParts.find((part) => {
      const start = Number(part.start);
      const end = Number(part.end);

      return currentTime >= start && currentTime < end;
    });

    if (!currentPart) {
      lastSkippedSegmentKey = null;
      return;
    }

    const segmentKey = `${currentPart.start}-${currentPart.end}`;

    if (segmentKey === lastSkippedSegmentKey) {
      return;
    }

    lastSkippedSegmentKey = segmentKey;

    const targetTime = Math.min(
      video.duration || Number(currentPart.end),
      Number(currentPart.end) + SKIP_EXIT_PADDING_SECONDS
    );

    console.log(
      `${Number(currentPart.start).toFixed(2)}-${Number(currentPart.end).toFixed(2)} arasi atlanacak kisim geciliyor`
    );
    const seekMethod = seekVideoTo(video, targetTime);
    console.log(`Atlama yontemi: ${seekMethod}, hedef zaman: ${targetTime.toFixed(2)}`);
    video.play();
  }, 500);

  return { success: true, message: "Otomatik atlatma baslatildi." };
}

function stopAutoSkip() {
  if (autoSkipInterval) {
    clearInterval(autoSkipInterval);
    autoSkipInterval = null;
    lastSkippedSegmentKey = null;
    console.log("Otomatik atlatma durduruldu.");
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ANALIZ_YAP") {
    loadAnalysis();
    sendResponse({ success: true, message: "Analiz baslatildi." });
  }

  if (message.type === "SKIP_BASLAT") {
    sendResponse(startAutoSkip());
  }

  if (message.type === "SKIP_DURDUR") {
    stopAutoSkip();
    sendResponse({ success: true, message: "Otomatik atlatma durduruldu." });
  }

  return true;
});

restoreLastAnalysisForCurrentVideo();

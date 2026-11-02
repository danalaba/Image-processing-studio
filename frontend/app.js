"use strict";

const statusText = document.querySelector("#connection-status");
const instanceText = document.querySelector("#instance-id");
const checkButton = document.querySelector("#check-connection");

async function checkConnection() {
  checkButton.disabled = true;
  statusText.className = "";
  statusText.textContent = "Перевіряємо з’єднання…";
  instanceText.textContent = "—";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    // Відносний URL працюватиме і через майбутній Nginx.
    const response = await fetch("/api/health", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.status !== "ok" || typeof data.instance_id !== "string" || !data.instance_id) {
      throw new Error("Unexpected health response");
    }
    statusText.textContent = "API працює · з’єднання встановлено";
    statusText.className = "status-ok";
    instanceText.textContent = data.instance_id;
  } catch (error) {
    statusText.textContent = "Немає зв’язку. Перевірте, чи запущено FastAPI, і спробуйте ще раз.";
    statusText.className = "status-error";
    console.warn("API health check failed:", error);
  } finally {
    clearTimeout(timeout);
    checkButton.disabled = false;
  }
}

checkButton.addEventListener("click", checkConnection);
checkConnection();

const resizeForm = document.querySelector("#resize-form");
const fileInput = document.querySelector("#image-file");
const fileInfo = document.querySelector("#file-info");
const processButton = document.querySelector("#process-image");
const processingStatus = document.querySelector("#processing-status");
const resultPanel = document.querySelector("#result-panel");
const resultPreview = document.querySelector("#result-preview");
const resultInfo = document.querySelector("#result-info");
const downloadLink = document.querySelector("#download-result");
const maxFileBytes = 10 * 1024 * 1024;
let resultUrl = null;
let busy = false;

function clearResult() {
  resultPanel.hidden = true;
  resultPreview.removeAttribute("src");
  downloadLink.removeAttribute("href");
  if (resultUrl) URL.revokeObjectURL(resultUrl);
  resultUrl = null;
}

function showProcessingStatus(message, state = "") {
  processingStatus.textContent = message;
  processingStatus.className = `processing-status ${state}`;
}

fileInput.addEventListener("change", () => {
  clearResult();
  const file = fileInput.files[0];
  processButton.disabled = true;
  if (!file) {
    fileInfo.textContent = "Файл ще не обрано.";
    showProcessingStatus("Оберіть фото, щоб почати.");
    return;
  }
  fileInfo.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MiB`;
  if (file.size === 0 || file.size > maxFileBytes) {
    showProcessingStatus("Оберіть непорожній файл розміром до 10 MiB.", "status-error");
    fileInput.value = "";
    return;
  }
  // accept і ця перевірка допомагають користувачу. Остаточна перевірка — на сервері.
  if (!/\.(jpe?g|png|webp)$/i.test(file.name)) {
    showProcessingStatus("Підтримуються файли .jpg, .jpeg, .png і .webp.", "status-error");
    fileInput.value = "";
    return;
  }
  processButton.disabled = false;
  showProcessingStatus("Фото обрано. Задайте рамку й натисніть «Обробити зображення».");
});

resizeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !resizeForm.reportValidity()) return;
  const file = fileInput.files[0];
  if (!file) return;

  const data = new FormData(resizeForm);
  clearResult();
  busy = true;
  resizeForm.setAttribute("aria-busy", "true");
  resizeForm.querySelectorAll("input, button").forEach(control => { control.disabled = true; });
  showProcessingStatus("Надсилання й обробка зображення…");

  try {
    // Content-Type не встановлюємо вручну: браузер додасть multipart boundary.
    const response = await fetch("/api/images/resize", { method: "POST", body: data });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      let message = typeof errorData.detail === "string" ? errorData.detail : `Помилка сервера (${response.status}).`;
      if (response.status === 422 && Array.isArray(errorData.detail)) {
        message = "Перевірте файл і параметри: ширина та висота мають бути цілими числами від 1 до 4096.";
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    if (blob.type !== "image/png" || blob.size === 0) throw new Error("Сервер повернув некоректний результат.");
    resultUrl = URL.createObjectURL(blob);
    resultPreview.src = resultUrl;
    downloadLink.href = resultUrl;
    resultInfo.textContent = `${response.headers.get("X-Image-Width")} × ${response.headers.get("X-Image-Height")} px · PNG · ${(blob.size / 1024).toFixed(1)} KiB`;
    resultPanel.hidden = false;
    showProcessingStatus("Готово. Результат можна переглянути й завантажити.", "status-ok");
  } catch (error) {
    showProcessingStatus(error instanceof TypeError ? "Не вдалося зв’язатися із сервером. Перевірте FastAPI й спробуйте ще раз." : error.message, "status-error");
  } finally {
    busy = false;
    resizeForm.setAttribute("aria-busy", "false");
    resizeForm.querySelectorAll("input, button").forEach(control => { control.disabled = false; });
    processButton.disabled = !fileInput.files.length;
  }
});

window.addEventListener("beforeunload", () => {
  if (resultUrl) URL.revokeObjectURL(resultUrl);
});

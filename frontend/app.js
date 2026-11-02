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
let token = sessionStorage.getItem("studio-token");
let pollTimer = null;
let currentJobId = null;
let presentedJobId = null;
let historySignature = "";
const progressPanel = document.querySelector("#job-progress");
const progressBar = document.querySelector("#progress-bar");
const progressLabel = document.querySelector("#progress-label");
const cancelButton = document.querySelector("#cancel-job");
const activeStates = new Set(["QUEUED", "RUNNING", "CANCELLING"]);
const stageNames = { queued: "Очікує в черзі", validating: "Перевірка фото", decoding: "Читання фото", orienting: "Орієнтація", resizing: "Зміна розміру", encoding: "Створення PNG", saving: "Збереження", completed: "Готово", failed: "Помилка", cancelling: "Очікування скасування", cancelled: "Скасовано" };

async function api(path, options = {}) {
  const requestToken = token;
  const headers = new Headers(options.headers);
  if (requestToken) headers.set("Authorization", `Bearer ${requestToken}`);
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && token === requestToken) setAccount(null);
    throw new Error(typeof data.detail === "string" ? data.detail : "Перевірте введені дані та спробуйте ще раз.");
  }
  return response;
}

function setAccount(user) {
  document.querySelector("#auth-form").hidden = Boolean(user);
  document.querySelector("#signed-in").hidden = !user;
  document.querySelector("#protected-workspace").hidden = !user;
  document.querySelector("#current-user").textContent = user ? `Ви увійшли як ${user.username}` : "";
  document.querySelector("#auth-status").textContent = user ? "Вхід виконано. Історія доступна лише вам. Сесія діє 24 години." : "Увійдіть або створіть акаунт, щоб продовжити.";
  if (!user) {
    clearTimeout(pollTimer);
    pollTimer = null;
    currentJobId = null;
    presentedJobId = null;
    historySignature = "";
    progressPanel.hidden = true;
    token = null;
    sessionStorage.removeItem("studio-token");
    clearResult();
    fileInput.value = "";
    fileInfo.textContent = "Файл ще не обрано.";
    document.querySelector("#job-list").replaceChildren();
  }
}

const statusNames = { QUEUED: "У черзі", RUNNING: "Обробляється", CANCELLING: "Скасовується", COMPLETED: "Завершено", FAILED: "Помилка", CANCELLED: "Скасовано" };
async function loadHistory() {
  const requestToken = token;
  const data = await (await api("/api/jobs")).json();
  if (token !== requestToken) return;
  const list = document.querySelector("#job-list");
  await updateTrackedJob(data.jobs, requestToken);
  if (token !== requestToken) return;
  clearTimeout(pollTimer);
  pollTimer = null;
  if (token && data.jobs.some(job => activeStates.has(job.status))) {
    pollTimer = setTimeout(refreshHistory, 1500);
  }
  const signature = JSON.stringify(data.jobs);
  if (historySignature === signature) return;
  historySignature = signature;
  list.replaceChildren();
  document.querySelector("#history-status").textContent = `Збережено ${data.jobs.length} із ${data.limit} задач.`;
  for (const job of data.jobs) {
    const row = document.createElement("li");
    const text = document.createElement("p");
    text.textContent = `${new Date(job.created_at).toLocaleString("uk-UA")} · ${statusNames[job.status] || job.status} · рамка ${job.target_width}×${job.target_height}`;
    row.append(text);
    if (activeStates.has(job.status)) {
      const state = document.createElement("p");
      state.textContent = `${stageNames[job.stage] || job.stage} · ${job.progress}%`;
      const progress = document.createElement("progress");
      progress.max = 100;
      progress.value = job.progress;
      progress.setAttribute("aria-label", `Прогрес задачі: ${job.progress}%`);
      row.append(state, progress);
    }
    if (job.error) {
      const error = document.createElement("p");
      error.textContent = job.error;
      row.append(error);
    }
    const actions = document.createElement("div");
    actions.className = "job-actions";
    function action(label, handler) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await handler(); } catch (error) { document.querySelector("#history-status").textContent = error.message; }
        finally { button.disabled = false; }
      });
      actions.append(button);
    }
    if (job.status === "COMPLETED") action("Завантажити PNG", async () => {
      const blob = await (await api(`/api/jobs/${job.id}/result`)).blob();
      if (token !== requestToken) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "resized-image.png";
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    if (job.status === "QUEUED" || job.status === "RUNNING") action("Скасувати", async () => {
      await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      await loadHistory();
    });
    if (!activeStates.has(job.status)) action("Видалити", async () => {
      if (!window.confirm("Видалити цю задачу та її результат?")) return;
      await api(`/api/jobs/${job.id}`, { method: "DELETE" });
      clearResult();
      await loadHistory();
    });
    row.append(actions);
    list.append(row);
  }
}

async function refreshHistory() {
  try { await loadHistory(); }
  catch (error) {
    document.querySelector("#history-status").textContent = error.message + " Повторюємо перевірку…";
    if (token) { clearTimeout(pollTimer); pollTimer = setTimeout(refreshHistory, 5000); }
  }
}
document.querySelector("#refresh-history").addEventListener("click", refreshHistory);
document.querySelector("#auth-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const mode = event.submitter?.value || "login";
  form.querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    const response = await api(`/api/auth/${mode}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.username.value, password: form.password.value }),
    });
    token = (await response.json()).access_token;
    sessionStorage.setItem("studio-token", token);
    form.password.value = "";
    setAccount(await (await api("/api/auth/me")).json());
    await refreshHistory();
  } catch (error) { document.querySelector("#auth-status").textContent = error.message; }
  finally { form.querySelectorAll("button").forEach(button => { button.disabled = false; }); }
});
document.querySelector("#logout").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); setAccount(null); }
  catch (error) { document.querySelector("#auth-status").textContent = error.message; }
});
async function restoreAccount() {
  if (!token) return;
  try { setAccount(await (await api("/api/auth/me")).json()); await refreshHistory(); }
  catch (error) { document.querySelector("#auth-status").textContent = error.message; }
}
restoreAccount();

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

async function updateTrackedJob(jobs, requestToken) {
  const job = jobs.find(item => item.id === currentJobId);
  if (token !== requestToken) return;
  if (!job) { progressPanel.hidden = true; return; }
  progressPanel.hidden = false;
  progressBar.value = job.progress;
  progressLabel.textContent = `${statusNames[job.status]} · ${job.progress}% · ${stageNames[job.stage] || job.stage}`;
  cancelButton.hidden = !activeStates.has(job.status);
  cancelButton.disabled = job.status === "CANCELLING";
  cancelButton.textContent = job.status === "CANCELLING" ? "Скасовуємо…" : "Скасувати задачу";
  if (job.status === "COMPLETED" && presentedJobId !== job.id) {
    const response = await api(`/api/jobs/${job.id}/result`);
    const blob = await response.blob();
    if (token !== requestToken || currentJobId !== job.id) return;
    if (blob.type !== "image/png" || !blob.size) throw new Error("Некоректний результат.");
    clearResult();
    resultUrl = URL.createObjectURL(blob);
    resultPreview.src = resultUrl;
    downloadLink.href = resultUrl;
    resultInfo.textContent = `${job.width} × ${job.height} px · PNG · ${(blob.size / 1024).toFixed(1)} KiB`;
    resultPanel.hidden = false;
    presentedJobId = job.id;
    showProcessingStatus("Готово. Результат можна переглянути й завантажити.", "status-ok");
  } else if (job.status === "FAILED") {
    showProcessingStatus(job.error || "Обробка не вдалася.", "status-error");
  } else if (job.status === "CANCELLED") {
    showProcessingStatus("Задачу скасовано. Можна створити нову.");
  }
}

cancelButton.addEventListener("click", async () => {
  if (!currentJobId) return;
  cancelButton.disabled = true;
  try {
    await api(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
    await refreshHistory();
  } catch (error) {
    showProcessingStatus(error.message, "status-error");
    cancelButton.disabled = false;
  }
});

resizeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !resizeForm.reportValidity() || !fileInput.files[0]) return;
  const data = new FormData(resizeForm);
  const requestToken = token;
  clearResult();
  busy = true;
  document.querySelector("#logout").disabled = true;
  resizeForm.setAttribute("aria-busy", "true");
  resizeForm.querySelectorAll("input, button").forEach(control => { control.disabled = true; });
  showProcessingStatus("Надсилання зображення…");
  try {
    const response = await api("/api/jobs", { method: "POST", body: data });
    const job = await response.json();
    if (token !== requestToken) return;
    currentJobId = job.id;
    presentedJobId = null;
    progressPanel.hidden = false;
    progressBar.value = 0;
    progressLabel.textContent = "У черзі · 0%";
    showProcessingStatus("Задачу прийнято. Статус оновлюється автоматично; можна обрати інше фото.");
  } catch (error) {
    showProcessingStatus(error instanceof TypeError ? "Не вдалося зв’язатися із сервером." : error.message, "status-error");
  } finally {
    busy = false;
    document.querySelector("#logout").disabled = false;
    resizeForm.setAttribute("aria-busy", "false");
    resizeForm.querySelectorAll("input, button").forEach(control => { control.disabled = false; });
    processButton.disabled = !fileInput.files.length;
    if (token) await refreshHistory();
  }
});

window.addEventListener("beforeunload", () => {
  clearTimeout(pollTimer);
  if (resultUrl) URL.revokeObjectURL(resultUrl);
});

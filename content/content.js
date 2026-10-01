let overlay;
let originalEl;
let translatedEl;
let statusEl;
let hideTimer;

function clampSize(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 100;
  return Math.min(180, Math.max(70, Math.round(n / 10) * 10));
}

function applyTranslationSize(percent) {
  ensureOverlay();
  overlay.style.setProperty('--lt-translation-scale', String(clampSize(percent) / 100));
}

async function loadDisplaySettings() {
  const stored = await chrome.storage.local.get({ translationSize: 100 });
  applyTranslationSize(stored.translationSize);
}

function ensureOverlay() {
  if (overlay?.isConnected) return;
  overlay = document.createElement('div');
  overlay.id = 'live-translator-overlay';

  originalEl = document.createElement('div');
  originalEl.className = 'lt-original';

  translatedEl = document.createElement('div');
  translatedEl.className = 'lt-translated';

  statusEl = document.createElement('div');
  statusEl.className = 'lt-status';

  overlay.append(originalEl, translatedEl, statusEl);
  document.documentElement.appendChild(overlay);
}

function show() {
  ensureOverlay();
  overlay.classList.add('lt-visible');
}

function scheduleHide(ms = 6000) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    if (statusEl?.textContent && statusEl.textContent !== 'ライブ翻訳中') return;
    overlay?.classList.remove('lt-visible');
  }, ms);
}

chrome.runtime.onMessage.addListener((message) => {
  ensureOverlay();

  if (message.type === 'LT_SET_TRANSLATION_SIZE') {
    applyTranslationSize(message.percent);
  }

  if (message.type === 'LT_STATUS') {
    statusEl.textContent = message.message || '';
    if (message.state === 'stopped') {
      originalEl.textContent = '';
      translatedEl.textContent = '';
      scheduleHide(1200);
    } else {
      show();
    }
  }

  if (message.type === 'LT_TRANSCRIPT') {
    originalEl.textContent = message.text || '';
    show();
  }

  if (message.type === 'LT_TRANSLATION') {
    originalEl.textContent = message.original || '';
    translatedEl.textContent = message.translated || '';
    statusEl.textContent = '';
    show();
    if (message.final) scheduleHide(7000);
  }
});

ensureOverlay();
loadDisplaySettings();

let overlay;
let speakerEl;
let originalEl;
let translatedEl;
let statusEl;
let hideTimer;
let currentSpeaker = null;

function clampSize(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 100;
  return Math.min(180, Math.max(70, Math.round(n / 10) * 10));
}

function speakerName(index) {
  if (!Number.isInteger(index) || index < 0) return '';
  const letter = String.fromCharCode(65 + (index % 26));
  return `話者 ${letter}`;
}

function applySpeaker(index) {
  currentSpeaker = Number.isInteger(index) ? index : null;
  ensureOverlay();
  if (currentSpeaker === null) {
    speakerEl.textContent = '';
    speakerEl.style.display = 'none';
    return;
  }
  speakerEl.textContent = speakerName(currentSpeaker);
  speakerEl.style.setProperty('--lt-speaker-hue', String((currentSpeaker * 71) % 360));
  speakerEl.style.display = 'table';
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

  speakerEl = document.createElement('div');
  speakerEl.className = 'lt-speaker';
  speakerEl.style.display = 'none';

  originalEl = document.createElement('div');
  originalEl.className = 'lt-original';

  translatedEl = document.createElement('div');
  translatedEl.className = 'lt-translated';

  statusEl = document.createElement('div');
  statusEl.className = 'lt-status';

  overlay.append(speakerEl, originalEl, translatedEl, statusEl);
  document.documentElement.appendChild(overlay);
}

function show() {
  ensureOverlay();
  overlay.classList.add('lt-visible');
}

function scheduleHide(ms = 6000) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    if (statusEl?.textContent && !statusEl.textContent.startsWith('ライブ翻訳中')) return;
    overlay?.classList.remove('lt-visible');
  }, ms);
}

chrome.runtime.onMessage.addListener((message) => {
  ensureOverlay();

  if (message.type === 'LT_SET_TRANSLATION_SIZE') {
    applyTranslationSize(message.percent);
  }

  if (message.type === 'LT_SPEAKER') {
    applySpeaker(message.speaker);
    show();
  }

  if (message.type === 'LT_STATUS') {
    statusEl.textContent = message.message || '';
    if (message.state === 'stopped') {
      originalEl.textContent = '';
      translatedEl.textContent = '';
      applySpeaker(null);
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
    if (Number.isInteger(message.speaker)) applySpeaker(message.speaker);
    originalEl.textContent = message.original || '';
    translatedEl.textContent = message.translated || '';
    statusEl.textContent = '';
    show();
    if (message.final) scheduleHide(7000);
  }
});

ensureOverlay();
loadDisplaySettings();

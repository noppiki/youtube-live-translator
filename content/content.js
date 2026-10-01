let overlay;
let utteranceList;
let statusEl;
let hideTimer;

const utteranceNodes = new Map();
const speakerProfiles = new Map();

function clampSize(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 100;
  return Math.min(180, Math.max(70, Math.round(n / 10) * 10));
}

function baseSpeakerName(index) {
  if (!Number.isInteger(index) || index < 0) return '話者 ?';
  const letter = String.fromCharCode(65 + (index % 26));
  return `話者 ${letter}`;
}

function localizedRole(role) {
  const value = String(role || '').trim();
  const map = {
    host: 'ホスト',
    guest: 'ゲスト',
    interviewer: 'インタビュアー',
    interviewee: 'ゲスト',
    presenter: '登壇者',
    speaker: '登壇者',
    commentator: '解説者',
    moderator: '司会',
    panelist: 'パネリスト'
  };
  return map[value.toLowerCase()] || value;
}

function speakerName(index) {
  if (!Number.isInteger(index) || index < 0) return '話者 ?';
  const profile = speakerProfiles.get(index);
  if (!profile) return baseSpeakerName(index);

  const name = String(profile.name || '').trim();
  const role = localizedRole(profile.role);
  const confidence = Number(profile.confidence || 0);

  if (name) {
    return confidence >= 0.9 ? name : confidence >= 0.65 ? `${name}?` : (role || baseSpeakerName(index));
  }
  return role || baseSpeakerName(index);
}

function speakerHue(index) {
  return Number.isInteger(index) && index >= 0 ? (index * 71) % 360 : 0;
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

  utteranceList = document.createElement('div');
  utteranceList.className = 'lt-utterance-list';

  statusEl = document.createElement('div');
  statusEl.className = 'lt-status';

  overlay.append(utteranceList, statusEl);
  document.documentElement.appendChild(overlay);
}

function show() {
  ensureOverlay();
  clearTimeout(hideTimer);
  hideTimer = null;
  overlay.classList.add('lt-visible');
}

function scheduleHide(ms = 7000) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    if (statusEl?.textContent && !statusEl.textContent.startsWith('ライブ翻訳中')) return;
    overlay?.classList.remove('lt-visible');
  }, ms);
}

function createUtteranceNode(utteranceId) {
  const root = document.createElement('div');
  root.className = 'lt-utterance';
  root.dataset.utteranceId = String(utteranceId);

  const speaker = document.createElement('div');
  speaker.className = 'lt-utterance-speaker';

  const body = document.createElement('div');
  body.className = 'lt-utterance-body';

  const original = document.createElement('div');
  original.className = 'lt-original';

  const translated = document.createElement('div');
  translated.className = 'lt-translated';

  body.append(original, translated);
  root.append(speaker, body);
  utteranceList.appendChild(root);

  const node = {
    root,
    speaker,
    original,
    translated,
    speakerIndex: null,
    final: false,
    order: performance.now()
  };
  utteranceNodes.set(utteranceId, node);
  paintSpeaker(node);
  trimUtterances();
  return node;
}

function paintSpeaker(node) {
  node.speaker.textContent = speakerName(node.speakerIndex);
  node.speaker.style.setProperty('--lt-speaker-hue', String(speakerHue(node.speakerIndex)));
  node.speaker.classList.toggle('lt-speaker-pending', !Number.isInteger(node.speakerIndex));
}

function moveToLatest(node) {
  if (node.root.parentElement === utteranceList) {
    utteranceList.appendChild(node.root);
  }
  node.order = performance.now();
}

function trimUtterances() {
  const nodes = [...utteranceNodes.entries()]
    .sort((a, b) => a[1].order - b[1].order);

  while (nodes.length > 3) {
    const [id, node] = nodes.shift();
    node.root.remove();
    utteranceNodes.delete(id);
  }
}

function updateSpeaker(utteranceId, speakerIndex) {
  const node = utteranceNodes.get(utteranceId);
  if (!node || !Number.isInteger(speakerIndex)) return;

  node.speakerIndex = speakerIndex;
  paintSpeaker(node);
}

function upsertUtterance(message) {
  ensureOverlay();

  const utteranceId = Number(message.utteranceId);
  if (!Number.isInteger(utteranceId)) return;

  const node = utteranceNodes.get(utteranceId) || createUtteranceNode(utteranceId);
  const firstContent = !node.original.textContent && !node.translated.textContent;

  if (typeof message.original === 'string' && message.original) {
    node.original.textContent = message.original;
  }

  if (typeof message.translated === 'string' && message.translated) {
    node.translated.textContent = message.translated;
  }

  if (Number.isInteger(message.speaker)) {
    node.speakerIndex = message.speaker;
    paintSpeaker(node);
  }

  node.root.classList.toggle('lt-translating', Boolean(message.translationPending));
  node.final = Boolean(message.final);
  node.root.classList.toggle('lt-final', node.final);
  node.root.classList.toggle('lt-partial', !node.final);

  // New utterances become the newest card. Updates to the same utterance stay
  // in place so partial ASR doesn't constantly reorder the stack.
  if (firstContent) moveToLatest(node);

  statusEl.textContent = '';
  show();
  trimUtterances();

  if (node.final) scheduleHide(9000);
}

function removeUtterance(utteranceId) {
  const node = utteranceNodes.get(utteranceId);
  if (!node) return;
  node.root.remove();
  utteranceNodes.delete(utteranceId);
}

function applySpeakerProfile(message) {
  if (!Number.isInteger(message.speaker)) return;

  speakerProfiles.set(message.speaker, {
    name: message.name || '',
    role: message.role || '',
    confidence: Number(message.confidence || 0),
    source: message.source || ''
  });

  for (const node of utteranceNodes.values()) {
    if (node.speakerIndex === message.speaker) paintSpeaker(node);
  }
}

function getPageContext() {
  const title =
    document.querySelector('meta[name="title"]')?.content ||
    document.querySelector('h1 yt-formatted-string')?.textContent ||
    document.title.replace(/\s*-\s*YouTube\s*$/, '');

  const channel =
    document.querySelector('#owner #channel-name a')?.textContent ||
    document.querySelector('ytd-channel-name a')?.textContent ||
    '';

  const description =
    document.querySelector('meta[name="description"]')?.content ||
    document.querySelector('meta[property="og:description"]')?.content ||
    '';

  return {
    title: String(title || '').trim().slice(0, 300),
    channel: String(channel || '').trim().slice(0, 200),
    description: String(description || '').trim().slice(0, 1200),
    url: location.href
  };
}

function clearUtterances() {
  for (const node of utteranceNodes.values()) node.root.remove();
  utteranceNodes.clear();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'LT_GET_PAGE_CONTEXT') {
    sendResponse(getPageContext());
    return;
  }

  ensureOverlay();

  if (message.type === 'LT_SET_TRANSLATION_SIZE') {
    applyTranslationSize(message.percent);
    return;
  }

  if (message.type === 'LT_UTTERANCE') {
    upsertUtterance(message);
    return;
  }

  if (message.type === 'LT_UTTERANCE_REMOVE') {
    removeUtterance(Number(message.utteranceId));
    return;
  }

  if (message.type === 'LT_UTTERANCE_SPEAKER') {
    updateSpeaker(Number(message.utteranceId), message.speaker);
    show();
    return;
  }

  if (message.type === 'LT_SPEAKER_PROFILE') {
    applySpeakerProfile(message);
    show();
    return;
  }

  if (message.type === 'LT_STATUS') {
    statusEl.textContent = message.message || '';

    if (message.state === 'stopped') {
      clearUtterances();
      scheduleHide(1200);
    } else {
      show();
    }
  }
});

ensureOverlay();
loadDisplaySettings();

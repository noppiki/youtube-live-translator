const OFFSCREEN_URL = 'offscreen/offscreen.html';
let creatingOffscreen = null;

async function hasOffscreenDocument() {
  if ('getContexts' in chrome.runtime) {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'],
      documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)]
    });
    return contexts.length > 0;
  }
  const matchedClients = await self.clients.matchAll();
  return matchedClients.some((client) => client.url === chrome.runtime.getURL(OFFSCREEN_URL));
}

async function ensureOffscreenDocument() {
  if (await hasOffscreenDocument()) return;
  if (creatingOffscreen) return creatingOffscreen;

  creatingOffscreen = chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ['USER_MEDIA', 'AUDIO_PLAYBACK'],
    justification: 'Capture and process tab audio while preserving playback for live subtitles.'
  }).finally(() => {
    creatingOffscreen = null;
  });

  return creatingOffscreen;
}

async function getActiveYoutubeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error('アクティブなタブを取得できませんでした。');
  if (!tab.url?.startsWith('https://www.youtube.com/')) {
    throw new Error('YouTube のタブで実行してください。');
  }
  return tab;
}

async function startCapture(settings) {
  const tab = await getActiveYoutubeTab();
  await ensureOffscreenDocument();

  const pageContext = await chrome.tabs.sendMessage(tab.id, { type: 'LT_GET_PAGE_CONTEXT' })
    .catch(() => ({}));

  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  const response = await chrome.runtime.sendMessage({
    target: 'offscreen',
    type: 'START_CAPTURE',
    streamId,
    tabId: tab.id,
    settings: { ...settings, pageContext }
  });

  if (!response?.ok) throw new Error(response?.error || '翻訳を開始できませんでした。');
  return { ok: true, tabId: tab.id };
}

async function stopCapture() {
  await ensureOffscreenDocument();
  const response = await chrome.runtime.sendMessage({ target: 'offscreen', type: 'STOP_CAPTURE' });
  if (!response?.ok) throw new Error(response?.error || '停止できませんでした。');
  return { ok: true };
}


async function translateComment(text, author = '') {
  const stored = await chrome.storage.local.get({ domainTerms: '' });
  const glossary = String(stored.domainTerms || '')
    .split(/\n|,/)
    .map((value) => value.trim())
    .filter(Boolean);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('http://127.0.0.1:8765/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        sourceLanguage: 'en',
        targetLanguage: 'ja',
        context: author ? [`YouTube commenter: ${author}`] : [],
        glossary
      }),
      signal: controller.signal
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    return { ok: true, translated: data?.translated || '' };
  } finally {
    clearTimeout(timer);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== 'background') return;

  (async () => {
    try {
      switch (message.type) {
        case 'START':
          sendResponse(await startCapture(message.settings));
          break;
        case 'STOP':
          sendResponse(await stopCapture());
          break;
        case 'GET_STATUS': {
          await ensureOffscreenDocument();
          const status = await chrome.runtime.sendMessage({ target: 'offscreen', type: 'GET_STATUS' });
          sendResponse(status || { ok: true, running: false });
          break;
        }
        case 'TRANSLATE_COMMENT':
          sendResponse(await translateComment(
            String(message.text || '').trim(),
            String(message.author || '').trim()
          ));
          break;
        default:
          sendResponse({ ok: false, error: 'Unknown background message' });
      }
    } catch (error) {
      sendResponse({ ok: false, error: error?.message || String(error) });
    }
  })();

  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== 'content-relay') return;
  chrome.tabs.sendMessage(message.tabId, message.message)
    .then(() => sendResponse({ ok: true }))
    .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
  return true;
});

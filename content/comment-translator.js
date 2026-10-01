const translatedNodes = new WeakSet();
const pending = [];
let working = false;
let enabled = true;

function hasJapanese(text) {
  const value = String(text || '');
  const jp = (value.match(/[\u3040-\u30ff\u3400-\u9fff]/g) || []).length;
  const letters = (value.match(/[A-Za-z\u3040-\u30ff\u3400-\u9fff]/g) || []).length;
  return letters > 0 && jp / letters >= 0.35;
}

function usefulText(text) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (value.length < 2 || value.length > 500) return '';
  if (!/[A-Za-z]/.test(value)) return '';
  if (hasJapanese(value)) return '';
  return value;
}

function translationTarget(messageEl) {
  const root = messageEl.closest(
    'ytd-comment-thread-renderer, yt-live-chat-text-message-renderer, yt-live-chat-paid-message-renderer, yt-live-chat-membership-item-renderer'
  );
  if (!root) return null;

  const author =
    root.querySelector('#author-text')?.textContent ||
    root.querySelector('#author-name')?.textContent ||
    '';

  return { root, author: author.trim() };
}

function ensureTranslationEl(messageEl) {
  let el = messageEl.parentElement?.querySelector(':scope > .lt-comment-translation');
  if (!el) {
    el = document.createElement('div');
    el.className = 'lt-comment-translation';
    messageEl.insertAdjacentElement('afterend', el);
  }
  return el;
}

async function translateOne(item) {
  const { messageEl, text, author } = item;
  if (!messageEl.isConnected || !enabled) return;

  const out = ensureTranslationEl(messageEl);
  out.textContent = '翻訳中…';
  out.classList.add('lt-comment-translating');

  try {
    const response = await chrome.runtime.sendMessage({
      target: 'background',
      type: 'TRANSLATE_COMMENT',
      text,
      author
    });
    if (!messageEl.isConnected) return;
    if (!response?.ok || !response.translated) {
      out.remove();
      return;
    }
    out.textContent = response.translated;
    out.classList.remove('lt-comment-translating');
  } catch {
    out.remove();
  }
}

async function drainQueue() {
  if (working) return;
  working = true;
  try {
    while (pending.length && enabled) {
      const item = pending.shift();
      await translateOne(item);
    }
  } finally {
    working = false;
  }
}

function queueMessage(messageEl) {
  if (!enabled || translatedNodes.has(messageEl)) return;
  const text = usefulText(messageEl.textContent);
  if (!text) {
    translatedNodes.add(messageEl);
    return;
  }

  const target = translationTarget(messageEl);
  if (!target) return;

  translatedNodes.add(messageEl);
  pending.push({
    messageEl,
    text,
    author: target.author
  });
  drainQueue();
}

const io = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    io.unobserve(entry.target);
    queueMessage(entry.target);
  }
}, { rootMargin: '250px 0px' });

function scan(root = document) {
  const selectors = [
    'ytd-comment-thread-renderer #content-text',
    'yt-live-chat-text-message-renderer #message',
    'yt-live-chat-paid-message-renderer #message',
    'yt-live-chat-membership-item-renderer #header-subtext'
  ];
  for (const el of root.querySelectorAll(selectors.join(','))) {
    if (!translatedNodes.has(el)) io.observe(el);
  }
}

async function loadSetting() {
  const stored = await chrome.storage.local.get({ translateComments: true });
  enabled = Boolean(stored.translateComments);
  if (enabled) scan();
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !changes.translateComments) return;
  enabled = Boolean(changes.translateComments.newValue);
  if (!enabled) {
    pending.length = 0;
    for (const el of document.querySelectorAll('.lt-comment-translation')) el.remove();
  } else {
    scan();
  }
});

const observer = new MutationObserver((mutations) => {
  if (!enabled) return;
  for (const mutation of mutations) {
    for (const node of mutation.addedNodes) {
      if (!(node instanceof Element)) continue;
      if (node.matches?.('#content-text, #message, #header-subtext')) io.observe(node);
      scan(node);
    }
  }
});

observer.observe(document.documentElement, { childList: true, subtree: true });
loadSetting();

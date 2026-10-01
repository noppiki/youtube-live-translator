const apiKey = document.querySelector('#apiKey');
const sourceLanguage = document.querySelector('#sourceLanguage');
const targetLanguage = document.querySelector('#targetLanguage');
const endpointingMs = document.querySelector('#endpointingMs');
const startButton = document.querySelector('#start');
const stopButton = document.querySelector('#stop');
const status = document.querySelector('#status');

const DEFAULTS = {
  deepgramApiKey: '',
  sourceLanguage: 'en',
  targetLanguage: 'ja',
  endpointingMs: 350
};

async function load() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  apiKey.value = stored.deepgramApiKey || '';
  sourceLanguage.value = stored.sourceLanguage || 'en';
  targetLanguage.value = stored.targetLanguage || 'ja';
  endpointingMs.value = String(stored.endpointingMs || 350);
  await refreshStatus();
}

function readSettings() {
  return {
    deepgramApiKey: apiKey.value.trim(),
    sourceLanguage: sourceLanguage.value,
    targetLanguage: targetLanguage.value,
    endpointingMs: Number(endpointingMs.value)
  };
}

async function saveSettings() {
  await chrome.storage.local.set(readSettings());
}

async function refreshStatus() {
  const response = await chrome.runtime.sendMessage({ target: 'background', type: 'GET_STATUS' }).catch(() => null);
  const isRunning = Boolean(response?.running);
  status.textContent = isRunning ? '● ライブ翻訳中' : '停止中';
  startButton.disabled = isRunning;
  stopButton.disabled = !isRunning;
}

startButton.addEventListener('click', async () => {
  const settings = readSettings();
  if (!settings.deepgramApiKey) {
    status.textContent = 'Deepgram APIキーを入力してください。';
    apiKey.focus();
    return;
  }

  await saveSettings();
  startButton.disabled = true;
  status.textContent = '開始しています…';

  const response = await chrome.runtime.sendMessage({
    target: 'background',
    type: 'START',
    settings
  });

  if (!response?.ok) {
    status.textContent = `エラー: ${response?.error || '開始できませんでした'}`;
    startButton.disabled = false;
    return;
  }

  status.textContent = '● ライブ翻訳中';
  stopButton.disabled = false;
});

stopButton.addEventListener('click', async () => {
  stopButton.disabled = true;
  status.textContent = '停止しています…';
  const response = await chrome.runtime.sendMessage({ target: 'background', type: 'STOP' });
  status.textContent = response?.ok ? '停止中' : `エラー: ${response?.error || '停止できませんでした'}`;
  startButton.disabled = false;
});

for (const control of [apiKey, sourceLanguage, targetLanguage, endpointingMs]) {
  control.addEventListener('change', saveSettings);
}

load();

const $ = (s) => document.querySelector(s);
const engineMode = $('#engineMode');
const localModel = $('#localModel');
const localBadge = $('#localBadge');
const testLocal = $('#testLocal');
const installModel = $('#installModel');
const installCommand = $('#installCommand');
const copyInstall = $('#copyInstall');
const apiKey = $('#apiKey');
const apiKeyLabel = $('#apiKeyLabel');
const sourceLanguage = $('#sourceLanguage');
const targetLanguage = $('#targetLanguage');
const domainTerms = $('#domainTerms');
const endpointingMs = $('#endpointingMs');
const endpointingLabel = $('#endpointingLabel');
const startButton = $('#start');
const stopButton = $('#stop');
const status = $('#status');

const DEFAULTS = {
  engineMode: 'auto',
  localModel: 'moona3k/mlx-qwen3-asr-0.6b-4bit',
  deepgramApiKey: '',
  sourceLanguage: 'en',
  targetLanguage: 'ja',
  domainTerms: 'OpenAI\nAnthropic\nClaude\nGemini\nCursor\nCodex\nMCP\nNVIDIA',
  endpointingMs: 350
};

async function checkLocal(showStatus = false) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    const response = await fetch('http://127.0.0.1:8765/health', { signal: controller.signal });
    clearTimeout(timer);
    const data = await response.json();
    if (!data?.ok) throw new Error('not ready');
    localBadge.textContent = '接続済み';
    localBadge.className = 'badge online';
    if (showStatus) status.textContent = 'ローカルエンジンに接続できました。';
    return true;
  } catch {
    localBadge.textContent = '未接続';
    localBadge.className = 'badge offline';
    if (showStatus) status.textContent = 'ローカルエンジンが見つかりません。初回インストールを実行してください。';
    return false;
  }
}

function updateVisibility() {
  const mode = engineMode.value;
  apiKeyLabel.style.display = mode === 'local' ? 'none' : 'grid';
  endpointingLabel.style.display = mode === 'local' ? 'none' : 'grid';
}

async function load() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  engineMode.value = stored.engineMode;
  localModel.value = stored.localModel;
  apiKey.value = stored.deepgramApiKey || '';
  sourceLanguage.value = stored.sourceLanguage;
  targetLanguage.value = stored.targetLanguage;
  domainTerms.value = stored.domainTerms || '';
  endpointingMs.value = String(stored.endpointingMs || 350);
  updateVisibility();
  checkLocal(false);
  await refreshStatus();
}

function readSettings() {
  return {
    engineMode: engineMode.value,
    localModel: localModel.value,
    deepgramApiKey: apiKey.value.trim(),
    sourceLanguage: sourceLanguage.value,
    targetLanguage: targetLanguage.value,
    domainTerms: domainTerms.value,
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

testLocal.addEventListener('click', () => checkLocal(true));

installModel.addEventListener('click', async () => {
  status.textContent = 'モデルを準備しています…初回はダウンロードに時間がかかります。';
  try {
    const response = await fetch('http://127.0.0.1:8765/models/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: localModel.value })
    });
    const data = await response.json();
    if (!data?.ok) throw new Error('モデル準備に失敗しました');
    status.textContent = 'モデルの準備が完了しました。';
    await checkLocal(false);
  } catch (error) {
    status.textContent = `エラー: ${error?.message || 'ローカルエンジンへ接続できません'}`;
  }
});

copyInstall.addEventListener('click', async () => {
  await navigator.clipboard.writeText(installCommand.value);
  status.textContent = 'インストールコマンドをコピーしました。';
});

startButton.addEventListener('click', async () => {
  const settings = readSettings();
  if (settings.engineMode === 'deepgram' && !settings.deepgramApiKey) {
    status.textContent = 'Deepgram APIキーを入力してください。';
    apiKey.focus();
    return;
  }
  if (settings.engineMode === 'local' && !(await checkLocal(false))) {
    status.textContent = 'ローカルエンジンが未接続です。初回インストールを実行してください。';
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

for (const control of [engineMode, localModel, apiKey, sourceLanguage, targetLanguage, domainTerms, endpointingMs]) {
  control.addEventListener('change', async () => {
    updateVisibility();
    await saveSettings();
  });
}
domainTerms.addEventListener('input', saveSettings);

load();

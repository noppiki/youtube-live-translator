const $ = (s) => document.querySelector(s);
const NATIVE_HOST = 'com.noppiki.youtube_live_translator';

const engineMode = $('#engineMode');
const localModel = $('#localModel');
const localBadge = $('#localBadge');
const startLocal = $('#startLocal');
const testLocal = $('#testLocal');
const installModel = $('#installModel');
const installCommand = $('#installCommand');
const copyInstall = $('#copyInstall');
const apiKey = $('#apiKey');
const apiKeyLabel = $('#apiKeyLabel');
const sourceLanguage = $('#sourceLanguage');
const targetLanguage = $('#targetLanguage');
const translationSize = $('#translationSize');
const translationSizeValue = $('#translationSizeValue');
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
  translationSize: 100,
  domainTerms: 'OpenAI\nAnthropic\nClaude\nGemini\nCursor\nCodex\nMCP\nNVIDIA',
  endpointingMs: 350
};

function sendNative(action) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NATIVE_HOST, { action }, (response) => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve(response || {});
    });
  });
}

async function nativeStatus() {
  try {
    return await sendNative('status');
  } catch (error) {
    return { ok: false, helperMissing: true, installed: false, running: false, error: error.message };
  }
}

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
    startLocal.disabled = true;
    startLocal.textContent = '起動済み';
    if (showStatus) status.textContent = 'ローカルエンジンに接続できました。';
    return true;
  } catch {
    const native = await nativeStatus();
    startLocal.disabled = false;
    startLocal.textContent = 'ローカル起動';

    if (native.helperMissing) {
      localBadge.textContent = 'ヘルパー未設定';
      localBadge.className = 'badge offline';
      if (showStatus) status.textContent = '起動ヘルパーが未設定です。「初回インストール / 起動ヘルパー更新」を一度実行してください。';
    } else if (native.installed) {
      localBadge.textContent = '停止中';
      localBadge.className = 'badge idle';
      if (showStatus) status.textContent = 'Qwen3はインストール済みですが、ローカルサービスが停止しています。';
    } else {
      localBadge.textContent = '未インストール';
      localBadge.className = 'badge offline';
      if (showStatus) status.textContent = 'ローカルエンジンが未インストールです。初回インストールを実行してください。';
    }
    return false;
  }
}

function updateVisibility() {
  const mode = engineMode.value;
  apiKeyLabel.style.display = mode === 'local' ? 'none' : 'grid';
  endpointingLabel.style.display = mode === 'local' ? 'none' : 'grid';
}

function updateInstallCommand() {
  installCommand.value =
    `curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash -s -- ${chrome.runtime.id}`;
}

async function load() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  engineMode.value = stored.engineMode;
  localModel.value = stored.localModel;
  apiKey.value = stored.deepgramApiKey || '';
  sourceLanguage.value = stored.sourceLanguage;
  targetLanguage.value = stored.targetLanguage;
  translationSize.value = String(stored.translationSize || 100);
  translationSizeValue.value = `${translationSize.value}%`;
  domainTerms.value = stored.domainTerms || '';
  endpointingMs.value = String(stored.endpointingMs || 350);

  updateInstallCommand();
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
    translationSize: Number(translationSize.value),
    domainTerms: domainTerms.value,
    endpointingMs: Number(endpointingMs.value)
  };
}

async function saveSettings() {
  await chrome.storage.local.set(readSettings());
}

async function sendSizeToActiveTab() {
  const percent = Number(translationSize.value);
  translationSizeValue.value = `${percent}%`;
  await chrome.storage.local.set({ translationSize: percent });

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) {
    chrome.tabs.sendMessage(tab.id, {
      type: 'LT_SET_TRANSLATION_SIZE',
      percent
    }).catch(() => {});
  }
}

async function refreshStatus() {
  const response = await chrome.runtime.sendMessage({ target: 'background', type: 'GET_STATUS' }).catch(() => null);
  const isRunning = Boolean(response?.running);
  status.textContent = isRunning ? '● ライブ翻訳中' : '停止中';
  startButton.disabled = isRunning;
  stopButton.disabled = !isRunning;
}

testLocal.addEventListener('click', () => checkLocal(true));

startLocal.addEventListener('click', async () => {
  startLocal.disabled = true;
  startLocal.textContent = '起動中…';
  status.textContent = 'ローカルQwen3を起動しています…';

  try {
    const response = await sendNative('start');
    if (!response?.ok) {
      throw new Error(response?.error || '起動に失敗しました');
    }

    const ready = await checkLocal(false);
    if (!ready) throw new Error('サービスを起動しましたが接続確認に失敗しました。');
    status.textContent = 'ローカルQwen3を起動しました。';
  } catch (error) {
    startLocal.disabled = false;
    startLocal.textContent = 'ローカル起動';
    const message = String(error?.message || error);
    if (/native messaging host|not found|forbidden/i.test(message)) {
      status.textContent = '起動ヘルパーが未設定です。初回インストール / 起動ヘルパー更新を一度実行してください。';
    } else {
      status.textContent = `起動エラー: ${message}`;
    }
    await checkLocal(false);
  }
});

installModel.addEventListener('click', async () => {
  status.textContent = 'モデルを準備しています…初回はダウンロードに時間がかかります。';
  try {
    if (!(await checkLocal(false))) {
      status.textContent = '先に「ローカル起動」でQwen3サービスを起動してください。';
      return;
    }
    const response = await fetch('http://127.0.0.1:8765/models/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: localModel.value })
    });
    const data = await response.json();
    if (!data?.ok) throw new Error('モデル準備に失敗しました');
    status.textContent = 'モデルの準備が完了しました。';
  } catch (error) {
    status.textContent = `エラー: ${error?.message || 'ローカルエンジンへ接続できません'}`;
  }
});

copyInstall.addEventListener('click', async () => {
  await navigator.clipboard.writeText(installCommand.value);
  status.textContent = 'インストールコマンドをコピーしました。';
});

translationSize.addEventListener('input', sendSizeToActiveTab);

startButton.addEventListener('click', async () => {
  const settings = readSettings();
  if (settings.engineMode === 'deepgram' && !settings.deepgramApiKey) {
    status.textContent = 'Deepgram APIキーを入力してください。';
    apiKey.focus();
    return;
  }

  if (settings.engineMode === 'local' && !(await checkLocal(false))) {
    status.textContent = 'ローカルエンジンが停止しています。「ローカル起動」を押してください。';
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

const $ = (s) => document.querySelector(s);
const NATIVE_HOST = 'com.noppiki.youtube_live_translator';

const engineMode = $('#engineMode');
const localBackend = $('#localBackend');
const localModel = $('#localModel');
const qwenModelLabel = $('#qwenModelLabel');
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
const diarization = $('#diarization');
const diarizationLabel = $('#diarizationLabel');
const diarizationHint = $('#diarizationHint');
const speakerNameInference = $('#speakerNameInference');
const speakerNameInferenceLabel = $('#speakerNameInferenceLabel');
const speakerNameInferenceHint = $('#speakerNameInferenceHint');
const prepareSpeakerAI = $('#prepareSpeakerAI');
const domainTerms = $('#domainTerms');
const domainTermsLabel = $('#domainTermsLabel');
const domainTermsHint = $('#domainTermsHint');
const endpointingMs = $('#endpointingMs');
const endpointingLabel = $('#endpointingLabel');
const startButton = $('#start');
const stopButton = $('#stop');
const status = $('#status');

const DEFAULTS = {
  engineMode: 'auto',
  localBackend: 'auto',
  localModel: 'moona3k/mlx-qwen3-asr-0.6b-4bit',
  deepgramApiKey: '',
  sourceLanguage: 'en',
  targetLanguage: 'ja',
  translationSize: 100,
  diarization: false,
  speakerNameInference: true,
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

function effectiveLocalBackend() {
  if (localBackend.value === 'fluid') return 'fluid';
  if (localBackend.value === 'qwen') return 'qwen';
  return sourceLanguage.value === 'en' ? 'fluid' : 'qwen';
}

async function checkLocal(showStatus = false) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    const response = await fetch('http://127.0.0.1:8765/health', { signal: controller.signal });
    clearTimeout(timer);
    const data = await response.json();
    if (!data?.ok) throw new Error('not ready');

    const fluidReady = Boolean(data.fluidAudio?.available);
    localBadge.textContent = fluidReady
      ? '接続済み · FluidAudio + Gemma 4 E4B'
      : '接続済み · Qwen3-ASR + Gemma 4 E4B';
    localBadge.className = 'badge online';
    startLocal.disabled = true;
    startLocal.textContent = '起動済み';
    if (showStatus) {
      status.textContent = fluidReady
        ? '接続済み。音声認識: FluidAudio / Qwen3-ASR、英→日翻訳: Gemma 4 E4B。'
        : '接続済み。音声認識: Qwen3-ASR、英→日翻訳: Gemma 4 E4B。';
    }
    return data;
  } catch {
    const native = await nativeStatus();
    startLocal.disabled = false;
    startLocal.textContent = 'ローカルAI起動';

    if (native.helperMissing) {
      localBadge.textContent = 'ヘルパー未設定';
      localBadge.className = 'badge offline';
      if (showStatus) status.textContent = '起動ヘルパーが未設定です。「初回インストール / ローカルAI更新」を実行してください。';
    } else if (native.installed) {
      localBadge.textContent = '停止中';
      localBadge.className = 'badge idle';
      if (showStatus) status.textContent = 'ローカルAIはインストール済みですが停止しています。';
    } else {
      localBadge.textContent = '未インストール';
      localBadge.className = 'badge offline';
      if (showStatus) status.textContent = 'ローカルAIが未インストールです。初回インストールを実行してください。';
    }
    return null;
  }
}

function updateVisibility() {
  const mode = engineMode.value;
  const backend = effectiveLocalBackend();
  const fluid = backend === 'fluid';
  const english = sourceLanguage.value === 'en';

  apiKeyLabel.style.display = mode === 'local' ? 'none' : 'grid';
  endpointingLabel.style.display = mode === 'local' ? 'none' : 'grid';

  qwenModelLabel.style.display = fluid ? 'none' : 'grid';
  domainTermsLabel.style.display = 'grid';
  domainTermsHint.style.display = 'block';

  diarization.disabled = !fluid || !english;
  if (!fluid || !english) {
    diarizationHint.textContent = english
      ? '話者分離を使うにはローカルバックエンドをFluidAudioまたは自動にしてください。'
      : '現在のライブ話者分離は英語＋FluidAudio時のみ利用できます。';
  } else {
    diarizationHint.textContent = 'Sortformerで話者A/B…を推定します。判定は字幕より少し遅れて追従します。';
  }

  const canInferNames = fluid && english && diarization.checked;
  speakerNameInference.disabled = !canInferNames;
  prepareSpeakerAI.disabled = !canInferNames || !speakerNameInference.checked;
  speakerNameInferenceHint.textContent = canInferNames
    ? '会話・配信タイトル・チャンネル名・概要欄から推定します。確信度が低い場合は「名前?」または役割名で表示します。'
    : '話者名推定は、英語＋FluidAudio＋話者分離ONのとき利用できます。';

  installModel.textContent = fluid
    ? (diarization.checked ? '音声認識＋話者モデル準備' : '音声認識モデル準備')
    : 'Qwen3-ASRモデル準備';
}

function updateInstallCommand() {
  installCommand.value =
    `curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash -s -- ${chrome.runtime.id}`;
}

async function load() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  engineMode.value = stored.engineMode;
  localBackend.value = stored.localBackend;
  localModel.value = stored.localModel;
  apiKey.value = stored.deepgramApiKey || '';
  sourceLanguage.value = stored.sourceLanguage;
  targetLanguage.value = stored.targetLanguage;
  translationSize.value = String(stored.translationSize || 100);
  translationSizeValue.value = `${translationSize.value}%`;
  diarization.checked = Boolean(stored.diarization);
  speakerNameInference.checked = Boolean(stored.speakerNameInference);
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
    localBackend: localBackend.value,
    localModel: localModel.value,
    deepgramApiKey: apiKey.value.trim(),
    sourceLanguage: sourceLanguage.value,
    targetLanguage: targetLanguage.value,
    translationSize: Number(translationSize.value),
    diarization: Boolean(diarization.checked),
    speakerNameInference: Boolean(speakerNameInference.checked),
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
  const provider = response?.provider ? ` · ${response.provider}` : '';
  status.textContent = isRunning ? `● ライブ翻訳中${provider}` : '停止中';
  startButton.disabled = isRunning;
  stopButton.disabled = !isRunning;
}

testLocal.addEventListener('click', () => checkLocal(true));

startLocal.addEventListener('click', async () => {
  startLocal.disabled = true;
  startLocal.textContent = '起動中…';
  status.textContent = 'ローカルAIサービスを起動しています…';

  try {
    const response = await sendNative('start');
    if (!response?.ok) throw new Error(response?.error || '起動に失敗しました');

    const ready = await checkLocal(false);
    if (!ready) throw new Error('サービスを起動しましたが接続確認に失敗しました。');
    status.textContent = 'ローカルAIサービスを起動しました。';
  } catch (error) {
    startLocal.disabled = false;
    startLocal.textContent = 'ローカルAI起動';
    const message = String(error?.message || error);
    if (/native messaging host|not found|forbidden/i.test(message)) {
      status.textContent = '起動ヘルパーが未設定です。初回インストール / ローカルAI更新を実行してください。';
    } else {
      status.textContent = `起動エラー: ${message}`;
    }
    await checkLocal(false);
  }
});

installModel.addEventListener('click', async () => {
  const health = await checkLocal(false);
  if (!health) {
    status.textContent = '先に「ローカルAI起動」でサービスを起動してください。';
    return;
  }

  const backend = effectiveLocalBackend();
  status.textContent = backend === 'fluid'
    ? 'FluidAudioモデルを準備しています…初回は数百MBのダウンロードがあります。'
    : 'Qwen3モデルを準備しています…';

  try {
    const body = backend === 'fluid'
      ? { engine: 'fluid', diarization: Boolean(diarization.checked) }
      : { engine: 'qwen', model: localModel.value };

    const response = await fetch('http://127.0.0.1:8765/models/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    if (!data?.ok) throw new Error('モデル準備に失敗しました');

    status.textContent = backend === 'fluid'
      ? 'FluidAudioモデルの準備が完了しました。'
      : 'Qwen3モデルの準備が完了しました。';
  } catch (error) {
    status.textContent = `モデル準備エラー: ${error?.message || error}`;
  }
});

copyInstall.addEventListener('click', async () => {
  await navigator.clipboard.writeText(installCommand.value);
  status.textContent = 'インストールコマンドをコピーしました。';
});

translationSize.addEventListener('input', sendSizeToActiveTab);

async function prepareSpeakerNameAI({ silent = false } = {}) {
  if (!speakerNameInference.checked) return true;

  if (!('LanguageModel' in globalThis)) {
    if (!silent) status.textContent = 'Chrome内蔵の名前推定AIはこの環境では利用できません。明示的な自己紹介のみ推定します。';
    return false;
  }

  const options = {
    expectedInputs: [{ type: 'text', languages: ['en', 'ja'] }],
    expectedOutputs: [{ type: 'text', languages: ['en'] }]
  };

  try {
    const availability = await LanguageModel.availability(options);
    if (availability === 'unavailable') {
      if (!silent) status.textContent = '名前推定AIはこの端末では利用できません。明示的な自己紹介のみ推定します。';
      return false;
    }

    if (!silent) {
      status.textContent = availability === 'available'
        ? '名前推定AIを確認しています…'
        : '名前推定AIをダウンロードしています…';
    }

    const session = await LanguageModel.create({
      ...options,
      monitor(monitor) {
        monitor.addEventListener('downloadprogress', (event) => {
          if (!silent) status.textContent = `名前推定AIを準備中… ${Math.round((event.loaded || 0) * 100)}%`;
        });
      }
    });
    session.destroy?.();

    if (!silent) status.textContent = '名前推定AIの準備が完了しました。';
    return true;
  } catch (error) {
    if (!silent) status.textContent = `名前推定AI: ${error?.message || error}`;
    return false;
  }
}

prepareSpeakerAI.addEventListener('click', () => prepareSpeakerNameAI({ silent: false }));

startButton.addEventListener('click', async () => {
  const settings = readSettings();

  if (settings.engineMode === 'deepgram' && !settings.deepgramApiKey) {
    status.textContent = 'Deepgram APIキーを入力してください。';
    apiKey.focus();
    return;
  }

  if (settings.engineMode === 'local' && !(await checkLocal(false))) {
    status.textContent = 'ローカルAIが停止しています。「ローカルAI起動」を押してください。';
    return;
  }

  const backend = effectiveLocalBackend();
  if (settings.diarization && (backend !== 'fluid' || settings.sourceLanguage !== 'en')) {
    status.textContent = '話者分離は英語＋FluidAudio時のみ利用できます。';
    return;
  }

  if (settings.speakerNameInference && settings.diarization) {
    await prepareSpeakerNameAI({ silent: true });
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

for (const control of [
  engineMode, localBackend, localModel, apiKey, sourceLanguage,
  targetLanguage, diarization, speakerNameInference, domainTerms, endpointingMs
]) {
  control.addEventListener('change', async () => {
    updateVisibility();
    await saveSettings();
  });
}

domainTerms.addEventListener('input', saveSettings);
load();

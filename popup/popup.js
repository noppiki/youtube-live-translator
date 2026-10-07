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
const installHint = $('#installHint');
const copyInstall = $('#copyInstall');
const performanceWarning = $('#performanceWarning');
const apiKey = $('#apiKey');
const apiKeyLabel = $('#apiKeyLabel');
const sourceLanguage = $('#sourceLanguage');
const targetLanguage = $('#targetLanguage');
const translationSize = $('#translationSize');
const translateComments = $('#translateComments');
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

const MACOS_MODELS = [
  { id: 'moona3k/mlx-qwen3-asr-0.6b-4bit', label: 'Qwen3-ASR 0.6B 4-bit（推奨・約517MB）' },
  { id: 'moona3k/mlx-qwen3-asr-1.7b-4bit', label: 'Qwen3-ASR 1.7B 4-bit（高精度・約1.2GB）' }
];
const WINDOWS_MODELS = [
  { id: 'Qwen/Qwen3-ASR-0.6B-hf', label: 'Qwen3-ASR 0.6B（推奨）' },
  { id: 'Qwen/Qwen3-ASR-1.7B-hf', label: 'Qwen3-ASR 1.7B（高精度）' }
];
const MODEL_ALIASES = {
  'moona3k/mlx-qwen3-asr-0.6b-4bit': 'Qwen/Qwen3-ASR-0.6B-hf',
  'moona3k/mlx-qwen3-asr-1.7b-4bit': 'Qwen/Qwen3-ASR-1.7B-hf',
  'Qwen/Qwen3-ASR-0.6B-hf': 'moona3k/mlx-qwen3-asr-0.6b-4bit',
  'Qwen/Qwen3-ASR-1.7B-hf': 'moona3k/mlx-qwen3-asr-1.7b-4bit'
};

const DEFAULTS = {
  engineMode: 'auto',
  localBackend: 'auto',
  localModel: 'moona3k/mlx-qwen3-asr-0.6b-4bit',
  deepgramApiKey: '',
  sourceLanguage: 'en',
  targetLanguage: 'ja',
  translationSize: 100,
  translateComments: true,
  diarization: false,
  speakerNameInference: true,
  domainTerms: 'OpenAI\nAnthropic\nClaude\nGemini\nCursor\nCodex\nMCP\nNVIDIA',
  endpointingMs: 350
};

let detectedOs = 'macos';

async function detectOs() {
  try {
    const info = await chrome.runtime.getPlatformInfo();
    if (info?.os === 'win') return 'windows';
    if (info?.os === 'mac') return 'macos';
  } catch {
  }
  return /Windows/i.test(navigator.userAgent) ? 'windows' : 'macos';
}

function defaultModelForOs(os) {
  return os === 'windows' ? WINDOWS_MODELS[0].id : MACOS_MODELS[0].id;
}

function populateModels(os, selected) {
  const models = os === 'windows' ? WINDOWS_MODELS : MACOS_MODELS;
  const wanted = models.some((item) => item.id === selected)
    ? selected
    : (MODEL_ALIASES[selected] && models.some((item) => item.id === MODEL_ALIASES[selected])
      ? MODEL_ALIASES[selected]
      : models[0].id);
  localModel.innerHTML = models.map((item) => (
    `<option value="${item.id}">${item.label}</option>`
  )).join('');
  localModel.value = wanted;
  return wanted;
}

function applyPlatformUi(os, health) {
  const windows = os === 'windows' || health?.os === 'windows';
  const fluidOption = localBackend.querySelector('option[value="fluid"]');
  if (fluidOption) fluidOption.hidden = windows;
  if (windows && localBackend.value === 'fluid') localBackend.value = 'auto';
  if (windows) {
    const autoOption = localBackend.querySelector('option[value="auto"]');
    if (autoOption) autoOption.textContent = '自動（Qwen3-ASR）';
  }
  diarization.disabled = windows;
  if (windows) {
    diarization.checked = false;
    diarizationHint.textContent = 'Windows初版では話者分離は準備中です。';
    speakerNameInference.disabled = true;
    prepareSpeakerAI.disabled = true;
    speakerNameInferenceHint.textContent = '話者名推定はmacOSのFluidAudio話者分離時のみ利用できます。';
    installHint.textContent = 'Windows 10/11 x64用。Qwen3-ASRとGemma 4 E4Bを準備します。PowerShellで実行してください。';
  }
  const warning = health?.performanceWarning;
  if (warning) {
    performanceWarning.hidden = false;
    performanceWarning.textContent = warning;
  } else if (windows && health?.accelerator === 'cpu') {
    performanceWarning.hidden = false;
    performanceWarning.textContent = 'CPUのみで動作しています。ライブ字幕が遅れる場合があります。';
  } else {
    performanceWarning.hidden = true;
    performanceWarning.textContent = '';
  }
}

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
  if (detectedOs === 'windows') return 'qwen';
  if (localBackend.value === 'fluid') return 'fluid';
  if (localBackend.value === 'qwen') return 'qwen';
  return sourceLanguage.value === 'en' && diarization.checked ? 'fluid' : 'qwen';
}

async function checkLocal(showStatus = false) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    const response = await fetch('http://127.0.0.1:8765/health', { signal: controller.signal });
    clearTimeout(timer);
    const data = await response.json();
    if (!data?.ok) throw new Error('not ready');

    if (data.os === 'windows' || data.os === 'macos') detectedOs = data.os;
    applyPlatformUi(detectedOs, data);
    const fluidReady = Boolean(data.fluidAudio?.available) && detectedOs !== 'windows';
    const asrLabel = data.asrBackend === 'torch' ? 'Qwen3-ASR (torch)' : 'Qwen3-ASR';
    localBadge.textContent = fluidReady
      ? '接続済み · FluidAudio + Gemma 4 E4B'
      : `接続済み · ${asrLabel} + Gemma 4 E4B`;
    localBadge.className = 'badge online';
    startLocal.disabled = true;
    startLocal.textContent = '起動済み';
    if (showStatus) {
      status.textContent = fluidReady
        ? '接続済み。自動音声認識: Qwen3-ASR優先（話者分離ON時のみFluidAudio）、翻訳: Gemma 4 E4B。'
        : `接続済み。音声認識: ${asrLabel}、翻訳: Gemma 4 E4B。`;
    }
    return data;
  } catch {
    const native = await nativeStatus();
    startLocal.disabled = false;
    startLocal.textContent = 'ローカルAI起動';

    if (native.helperMissing) {
      localBadge.textContent = 'ヘルパー未設定 / ID不一致';
      localBadge.className = 'badge offline';
      if (showStatus) status.textContent = `起動ヘルパーが未設定、または拡張IDが一致していません（現在: ${chrome.runtime.id}）。下のインストールコマンドを再実行してください。`;
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
  const windows = detectedOs === 'windows';
  const canUseFluidDiarization =
    !windows && english && (localBackend.value === 'fluid' || localBackend.value === 'auto');

  apiKeyLabel.style.display = mode === 'local' ? 'none' : 'grid';
  endpointingLabel.style.display = mode === 'local' ? 'none' : 'grid';

  qwenModelLabel.style.display = fluid ? 'none' : 'grid';
  domainTermsLabel.style.display = 'grid';
  domainTermsHint.style.display = 'block';

  diarization.disabled = windows || !canUseFluidDiarization;
  if (windows) {
    diarization.checked = false;
    diarizationHint.textContent = 'Windows初版では話者分離は準備中です。';
  } else if (!canUseFluidDiarization) {
    diarizationHint.textContent = english
      ? '話者分離を使うにはローカルバックエンドをFluidAudioまたは自動にしてください。'
      : '現在のライブ話者分離は英語＋FluidAudio時のみ利用できます。';
  } else if (localBackend.value === 'auto') {
    diarizationHint.textContent = diarization.checked
      ? '話者分離ONのためFluidAudio＋Sortformerを使用します。'
      : '自動ではQwen3-ASRを優先します。話者分離をONにするとFluidAudio＋Sortformerへ切り替わります。';
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
  const id = chrome.runtime.id;
  if (detectedOs === 'windows') {
    installCommand.value =
      `irm https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-windows.ps1 -OutFile "$env:TEMP\\ytlt-install.ps1"; & "$env:TEMP\\ytlt-install.ps1" -ExtensionId '${id}'`;
    return;
  }
  installCommand.value =
    `curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash -s -- ${id}`;
}

async function load() {
  detectedOs = await detectOs();
  const stored = await chrome.storage.local.get(DEFAULTS);
  engineMode.value = stored.engineMode;
  localBackend.value = stored.localBackend;
  const selectedModel = populateModels(detectedOs, stored.localModel || defaultModelForOs(detectedOs));
  if (selectedModel !== stored.localModel) {
    await chrome.storage.local.set({ localModel: selectedModel });
  }
  applyPlatformUi(detectedOs);
  apiKey.value = stored.deepgramApiKey || '';
  sourceLanguage.value = stored.sourceLanguage;
  targetLanguage.value = stored.targetLanguage;
  translationSize.value = String(stored.translationSize || 100);
  translateComments.checked = Boolean(stored.translateComments);
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
    translateComments: Boolean(translateComments.checked),
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
      status.textContent = `起動ヘルパーが未設定、または拡張IDが不一致です（現在: ${chrome.runtime.id}）。初回インストール / ローカルAI更新を再実行してください。`;
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
  if (detectedOs === 'windows' && settings.diarization) {
    status.textContent = 'Windows初版では話者分離は利用できません。';
    return;
  }

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
  targetLanguage, translateComments, diarization, speakerNameInference, domainTerms, endpointingMs
]) {
  control.addEventListener('change', async () => {
    updateVisibility();
    await saveSettings();
  });
}

domainTerms.addEventListener('input', saveSettings);
load();

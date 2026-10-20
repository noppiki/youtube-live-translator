const $ = (s) => document.querySelector(s);
const NATIVE_HOST = 'com.noppiki.youtube_live_translator';
let PLATFORM_OS = 'unknown';
let IS_WINDOWS = false;

async function detectPlatform() {
  try {
    const info = await chrome.runtime.getPlatformInfo();
    PLATFORM_OS = String(info?.os || 'unknown').toLowerCase();
    IS_WINDOWS = PLATFORM_OS === 'win';
    return;
  } catch {
    // Fallback for older Chromium builds or unusual extension environments.
  }

  const fallback = String(
    globalThis.navigator?.userAgentData?.platform || globalThis.navigator?.platform || ''
  ).toLowerCase();
  PLATFORM_OS = fallback;
  IS_WINDOWS = fallback.includes('win');
}
const WINDOWS_MODELS = [
  { value: 'Qwen/Qwen3-ASR-0.6B-hf', label: 'Qwen3-ASR 0.6B（Windows Transformers・推奨）' },
  { value: 'Qwen/Qwen3-ASR-1.7B-hf', label: 'Qwen3-ASR 1.7B（Windows Transformers・高精度）' }
];

const engineMode = $('#engineMode');
const localBackend = $('#localBackend');
const localModel = $('#localModel');
const qwenModelLabel = $('#qwenModelLabel');
const translationModel = $('#translationModel');
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
const translateComments = $('#translateComments');
const translationSizeValue = $('#translationSizeValue');
const diarization = $('#diarization');
const diarizationLabel = $('#diarizationLabel');
const diarizationHint = $('#diarizationHint');
const speakerNameInference = $('#speakerNameInference');
const speakerNameInferenceLabel = $('#speakerNameInferenceLabel');
const speakerNameInferenceHint = $('#speakerNameInferenceHint');
const prepareSpeakerAI = $('#prepareSpeakerAI');
const speakerEnrollDetails = $('#speakerEnrollDetails');
const speakerEnrollHint = $('#speakerEnrollHint');
const enrolledList = $('#enrolledList');
const speakerNameInput = $('#speakerNameInput');
const liveSpeakerSelect = $('#liveSpeakerSelect');
const speakerAudioFile = $('#speakerAudioFile');
const enrollLiveSpeaker = $('#enrollLiveSpeaker');
const enrollAudioFile = $('#enrollAudioFile');
const refreshSpeakers = $('#refreshSpeakers');
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
  translateComments: true,
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
  if (IS_WINDOWS) return 'qwen';
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

    const fluidReady = Boolean(data.fluidAudio?.available);
    if (IS_WINDOWS || data.os === 'windows') {
      const accelerator = data.accelerator ? ` · ${data.accelerator}` : '';
      localBadge.textContent = `接続済み · Qwen3-ASR Transformers + llama.cpp${accelerator}`;
    } else {
      localBadge.textContent = fluidReady
        ? '接続済み · FluidAudio + Gemma 4 E4B'
        : '接続済み · Qwen3-ASR + Gemma 4 E4B';
    }
    localBadge.className = 'badge online';
    startLocal.disabled = true;
    startLocal.textContent = '起動済み';
    if (showStatus) {
      status.textContent = IS_WINDOWS || data.os === 'windows'
        ? `接続済み。音声認識: Qwen3-ASR Transformers、翻訳: llama.cpp / Gemma 4 E4B${data.accelerator ? `（${data.accelerator}）` : ''}。`
        : fluidReady
          ? '接続済み。自動音声認識: Qwen3-ASR優先（話者分離ON時のみFluidAudio）、翻訳: Gemma 4 E4B。'
          : '接続済み。音声認識: Qwen3-ASR、翻訳: Gemma 4 E4B。';
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
  const fluid = !IS_WINDOWS && backend === 'fluid';
  const english = sourceLanguage.value === 'en';
  const canUseFluidDiarization = !IS_WINDOWS &&
    english && (localBackend.value === 'fluid' || localBackend.value === 'auto');

  apiKeyLabel.style.display = mode === 'local' ? 'none' : 'grid';
  endpointingLabel.style.display = mode === 'local' ? 'none' : 'grid';

  qwenModelLabel.style.display = fluid ? 'none' : 'grid';
  domainTermsLabel.style.display = 'grid';
  domainTermsHint.style.display = 'block';

  diarization.disabled = !canUseFluidDiarization;
  if (IS_WINDOWS) {
    diarization.checked = false;
    diarization.disabled = true;
    diarizationHint.textContent = 'Windows初版では話者分離（FluidAudio / Sortformer）は準備中です。';
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

  const canInferNames = !IS_WINDOWS && fluid && english && diarization.checked;
  speakerNameInference.disabled = !canInferNames;
  prepareSpeakerAI.disabled = !canInferNames || !speakerNameInference.checked;
  speakerNameInferenceHint.textContent = canInferNames
    ? '会話・配信タイトル・チャンネル名・概要欄から推定します。確信度が低い場合は「名前?」または役割名で表示します。'
    : '話者名推定は、英語＋FluidAudio＋話者分離ONのとき利用できます。';

  installModel.textContent = IS_WINDOWS
    ? 'Qwen3-ASRモデル準備'
    : fluid
    ? (diarization.checked ? '音声認識＋話者モデル準備' : '音声認識モデル準備')
    : 'Qwen3-ASRモデル準備';
}

function updateInstallCommand() {
  installCommand.value = IS_WINDOWS
    ? `& ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-windows.ps1'))) -ExtensionId '${chrome.runtime.id}'`
    : `curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash -s -- ${chrome.runtime.id}`;
}

function configurePlatformUI() {
  speakerEnrollDetails.style.display = IS_WINDOWS ? 'none' : '';
  if (!IS_WINDOWS) return;

  const fluidOption = localBackend.querySelector('option[value="fluid"]');
  if (fluidOption) {
    fluidOption.hidden = true;
    fluidOption.disabled = true;
  }
  if (localBackend.value === 'fluid') localBackend.value = 'qwen';

  localModel.replaceChildren(...WINDOWS_MODELS.map(({ value, label }) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    return option;
  }));
  if (!WINDOWS_MODELS.some(({ value }) => value === localModel.value)) {
    localModel.value = WINDOWS_MODELS[0].value;
  }
  translationModel.replaceChildren(Object.assign(document.createElement('option'), {
    value: 'google/gemma-4-E4B-it-qat-q4_0-gguf',
    textContent: 'Gemma 4 E4B Q4_0（llama.cpp・固定）'
  }));
  translationModel.value = 'google/gemma-4-E4B-it-qat-q4_0-gguf';
  $('#translationModelHint').textContent = '英・韓・中・西・仏・独 → 日本語。Windowsではllama.cpp経由でGemma 4 E4Bを使用します。';
  $('#installHint').textContent = 'Windows 10/11 x64用（PowerShell）。Qwen3-ASR Transformers、llama.cpp、Gemma 4 E4B、Native Messaging、ログイン時起動を準備します。初回はモデルとランタイムのダウンロードがあります。';
}

async function load() {
  await detectPlatform();
  const stored = await chrome.storage.local.get(DEFAULTS);
  engineMode.value = stored.engineMode;
  localBackend.value = stored.localBackend;
  localModel.value = stored.localModel;
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

  configurePlatformUI();
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
      ? {
          engine: 'fluid',
          diarization: Boolean(diarization.checked),
          voiceprint: Boolean(diarization.checked)
        }
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

// ---- Voice enrollment (speaker identification) ----

let speakersPoll = null;
let fluidAvailable = false;

function speakerLetter(index) {
  return String.fromCharCode(65 + (index % 26));
}

let speakerTokenCache = null;

async function speakerApiHeaders() {
  if (speakerTokenCache === null) {
    try {
      const response = await sendNative('speakerToken');
      speakerTokenCache = response?.ok ? String(response.token || '') : '';
    } catch {
      speakerTokenCache = '';
    }
  }
  return speakerTokenCache ? { 'X-YTLT-Token': speakerTokenCache } : {};
}

async function speakerFetch(path, options = {}) {
  const doFetch = async () => fetch(`http://127.0.0.1:8765${path}`, {
    ...options,
    headers: { ...(await speakerApiHeaders()), ...(options.headers || {}) }
  });
  let response = await doFetch();
  if (response.status === 403) {
    // The token rotates with each server start; refresh once and retry.
    speakerTokenCache = null;
    response = await doFetch();
  }
  return response;
}

async function fetchSpeakers() {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const response = await speakerFetch('/speakers', { signal: controller.signal });
    clearTimeout(timer);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function renderSpeakers(data) {
  const speakers = data?.speakers || [];
  const live = data?.live || {};

  enrolledList.replaceChildren();
  if (!speakers.length) {
    const empty = document.createElement('div');
    empty.className = 'enrolledEmpty';
    empty.textContent = '登録済みの話者はいません。';
    enrolledList.append(empty);
  }
  for (const speaker of speakers) {
    const row = document.createElement('div');
    row.className = 'enrolledRow';
    const name = document.createElement('span');
    name.className = 'enrolledName';
    name.textContent = speaker.name || '(無名)';
    const remove = document.createElement('button');
    remove.textContent = '削除';
    remove.addEventListener('click', async () => {
      try {
        const response = await speakerFetch(`/speakers/${speaker.id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(await response.text());
        status.textContent = `「${speaker.name}」の登録を解除しました。`;
      } catch (error) {
        status.textContent = `削除エラー: ${error?.message || error}`;
      }
      refreshSpeakerPanel();
    });
    row.append(name, remove);
    enrolledList.append(row);
  }

  const previousSelection = liveSpeakerSelect.value;
  liveSpeakerSelect.replaceChildren();
  const entries = Object.entries(live);
  if (!entries.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '検出中の話者なし（翻訳中に話し始めると出ます）';
    liveSpeakerSelect.append(option);
    liveSpeakerSelect.disabled = true;
    enrollLiveSpeaker.disabled = true;
  } else {
    for (const [index, info] of entries) {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `話者 ${speakerLetter(Number(index))}（約${info.seconds}秒${info.identified ? '・登録済' : ''}）`;
      liveSpeakerSelect.append(option);
    }
    if (previousSelection !== '' && entries.some(([index]) => index === previousSelection)) {
      liveSpeakerSelect.value = previousSelection;
    }
    liveSpeakerSelect.disabled = !fluidAvailable;
    enrollLiveSpeaker.disabled = !fluidAvailable;
  }
  enrollAudioFile.disabled = !fluidAvailable;
}

let enrollInFlight = false;

async function refreshSpeakerPanel() {
  if (enrollInFlight) return;
  const data = await fetchSpeakers();
  fluidAvailable = Boolean(data?.matching?.available);
  if (!data) {
    speakerEnrollHint.textContent = 'ローカルAIに接続できません。先に「ローカルAI起動」を実行してください。';
    return;
  }
  speakerEnrollHint.textContent = fluidAvailable
    ? '登録した声が検出されると字幕の「話者A」等が登録名で表示されます。'
    : '声紋登録は macOS の FluidAudio 環境でのみ利用できます。';
  renderSpeakers(data);
}

async function postEnroll(body) {
  const response = await speakerFetch('/speakers/enroll', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.ok) {
    throw new Error(data?.detail || data?.error || '登録に失敗しました');
  }
  return data;
}

enrollLiveSpeaker.addEventListener('click', async () => {
  const name = speakerNameInput.value.trim();
  const index = liveSpeakerSelect.value;
  if (!name) {
    status.textContent = '登録する名前を入力してください。';
    speakerNameInput.focus();
    return;
  }
  if (index === '') {
    status.textContent = '検出中の話者がありません。翻訳中に話し始めると選択できます。';
    return;
  }

  enrollLiveSpeaker.disabled = true;
  enrollInFlight = true;
  status.textContent = `話者 ${speakerLetter(Number(index))} の声を学習しています…`;
  try {
    await postEnroll({ name, speakerIndex: Number(index) });
    status.textContent = `「${name}」を登録しました。字幕の話者名が更新されます。`;
    speakerNameInput.value = '';
  } catch (error) {
    status.textContent = `登録エラー: ${error?.message || error}`;
  } finally {
    enrollInFlight = false;
  }
  refreshSpeakerPanel();
});

async function fileToPcm16Base64(file) {
  const arrayBuffer = await file.arrayBuffer();
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(arrayBuffer);
  const length = Math.min(decoded.length, Math.round(60 * decoded.sampleRate));
  const offline = new OfflineAudioContext(1, Math.ceil((length / decoded.sampleRate) * 16000), 16000);
  const trimmed = ctx.createBuffer(1, length, decoded.sampleRate);
  trimmed.copyToChannel(decoded.getChannelData(0).subarray(0, length), 0);
  const source = offline.createBufferSource();
  source.buffer = trimmed;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();

  const floats = rendered.getChannelData(0);
  const pcm = new Int16Array(floats.length);
  for (let i = 0; i < floats.length; i += 1) {
    const s = Math.max(-1, Math.min(1, floats[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

enrollAudioFile.addEventListener('click', async () => {
  const name = speakerNameInput.value.trim();
  const file = speakerAudioFile.files?.[0];
  if (!name) {
    status.textContent = '登録する名前を入力してください。';
    speakerNameInput.focus();
    return;
  }
  if (!file) {
    status.textContent = '音声ファイルを選択してください。';
    return;
  }

  enrollAudioFile.disabled = true;
  enrollInFlight = true;
  status.textContent = '音声ファイルから声を学習しています…';
  try {
    const audioBase64 = await fileToPcm16Base64(file);
    await postEnroll({ name, audioBase64 });
    status.textContent = `「${name}」を登録しました。`;
    speakerNameInput.value = '';
    speakerAudioFile.value = '';
  } catch (error) {
    status.textContent = `登録エラー: ${error?.message || error}`;
  } finally {
    enrollInFlight = false;
  }
  refreshSpeakerPanel();
});

refreshSpeakers.addEventListener('click', refreshSpeakerPanel);

speakerEnrollDetails.addEventListener('toggle', () => {
  if (speakerEnrollDetails.open) {
    refreshSpeakerPanel();
    if (!speakersPoll) speakersPoll = setInterval(refreshSpeakerPanel, 4000);
  } else if (speakersPoll) {
    clearInterval(speakersPoll);
    speakersPoll = null;
  }
});

window.addEventListener('unload', () => {
  if (speakersPoll) clearInterval(speakersPoll);
});

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
  targetLanguage, translateComments, diarization, speakerNameInference, domainTerms, endpointingMs
]) {
  control.addEventListener('change', async () => {
    updateVisibility();
    await saveSettings();
  });
}

domainTerms.addEventListener('input', saveSettings);
load();

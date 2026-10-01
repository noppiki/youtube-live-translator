let mediaStream = null;
let audioContext = null;
let sourceNode = null;
let workletNode = null;
let muteGain = null;
let deepgramSocket = null;
let keepAliveTimer = null;
let currentTabId = null;
let running = false;
let settings = null;
let finalizedPieces = [];
let translatorCache = new Map();
let translateSequence = 0;

function postToTab(type, payload = {}) {
  if (!currentTabId) return;
  chrome.tabs?.sendMessage?.(currentTabId, { type, ...payload }).catch?.(() => {});
}

// Offscreen documents only expose chrome.runtime. Route through the service worker.
async function relayToTab(message) {
  await chrome.runtime.sendMessage({
    target: 'background-relay',
    ...message,
    tabId: currentTabId
  }).catch(() => {});
}

function sendOverlay(type, payload = {}) {
  chrome.runtime.sendMessage({
    target: 'content-relay',
    tabId: currentTabId,
    message: { type, ...payload }
  }).catch(() => {});
}

function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function downsampleBuffer(buffer, inputRate, outputRate) {
  if (outputRate === inputRate) return buffer;
  if (outputRate > inputRate) throw new Error('Output rate must be <= input rate');

  const ratio = inputRate / outputRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i += 1) {
      accum += buffer[i];
      count += 1;
    }
    result[offsetResult] = count ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function buildDeepgramUrl() {
  const params = new URLSearchParams({
    model: 'nova-3',
    encoding: 'linear16',
    sample_rate: '16000',
    channels: '1',
    interim_results: 'true',
    endpointing: String(settings.endpointingMs || 350),
    punctuate: 'true',
    smart_format: 'true'
  });

  if (settings.sourceLanguage === 'auto') {
    params.set('detect_language', 'true');
  } else if (settings.sourceLanguage === 'multi') {
    params.set('language', 'multi');
  } else {
    params.set('language', settings.sourceLanguage || 'en');
  }

  return `wss://api.deepgram.com/v1/listen?${params.toString()}`;
}

function normalizeSourceLanguage(language) {
  if (!language) return settings.sourceLanguage === 'auto' ? 'en' : settings.sourceLanguage;
  return language.split('-')[0].toLowerCase();
}

async function getTranslator(sourceLanguage, targetLanguage) {
  const source = normalizeSourceLanguage(sourceLanguage);
  const target = (targetLanguage || 'ja').split('-')[0].toLowerCase();
  if (source === target) return null;
  if (!('Translator' in self)) throw new Error('Chrome Translator API が利用できません。Chrome 138+ のデスクトップ版を使用してください。');

  const key = `${source}->${target}`;
  if (translatorCache.has(key)) return translatorCache.get(key);

  const availability = await Translator.availability({ sourceLanguage: source, targetLanguage: target });
  if (availability === 'unavailable') {
    throw new Error(`Chrome Translator API が ${source} → ${target} に対応していません。`);
  }

  const translator = await Translator.create({
    sourceLanguage: source,
    targetLanguage: target,
    monitor(monitor) {
      monitor.addEventListener('downloadprogress', (event) => {
        sendOverlay('LT_STATUS', {
          state: 'downloading',
          message: `翻訳モデルを準備中… ${Math.round((event.loaded || 0) * 100)}%`
        });
      });
    }
  });
  translatorCache.set(key, translator);
  return translator;
}

async function translateText(text, sourceLanguage) {
  if (!text?.trim()) return '';
  const source = normalizeSourceLanguage(sourceLanguage);
  const target = settings.targetLanguage || 'ja';
  if (source === target) return text;
  const translator = await getTranslator(source, target);
  return translator ? translator.translate(text) : text;
}

async function emitSubtitle(text, sourceLanguage, final) {
  const sequence = ++translateSequence;
  sendOverlay('LT_TRANSCRIPT', { text, final });

  try {
    const translated = await translateText(text, sourceLanguage);
    if (!running || sequence < translateSequence - 8) return;
    sendOverlay('LT_TRANSLATION', {
      original: text,
      translated,
      final,
      sourceLanguage: normalizeSourceLanguage(sourceLanguage)
    });
  } catch (error) {
    sendOverlay('LT_STATUS', { state: 'error', message: error?.message || String(error) });
  }
}

function handleDeepgramMessage(event) {
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }

  if (data.type === 'Results') {
    const transcript = data.channel?.alternatives?.[0]?.transcript?.trim();
    if (!transcript) return;

    const detected = data.channel?.detected_language || data.channel?.alternatives?.[0]?.languages?.[0];

    if (data.is_final) {
      finalizedPieces.push(transcript);
      if (data.speech_final) {
        const complete = finalizedPieces.join(' ').replace(/\s+/g, ' ').trim();
        finalizedPieces = [];
        emitSubtitle(complete, detected, true);
      } else {
        emitSubtitle(finalizedPieces.join(' '), detected, false);
      }
    } else {
      const prefix = finalizedPieces.length ? `${finalizedPieces.join(' ')} ` : '';
      emitSubtitle(`${prefix}${transcript}`.trim(), detected, false);
    }
  }

  if (data.type === 'Metadata') {
    sendOverlay('LT_STATUS', { state: 'running', message: 'ライブ翻訳中' });
  }
}

function openDeepgramSocket() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(buildDeepgramUrl(), ['token', settings.deepgramApiKey]);
    socket.binaryType = 'arraybuffer';

    const timeout = setTimeout(() => reject(new Error('Deepgram 接続がタイムアウトしました。')), 10000);

    socket.onopen = () => {
      clearTimeout(timeout);
      deepgramSocket = socket;
      keepAliveTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'KeepAlive' }));
        }
      }, 8000);
      resolve();
    };

    socket.onmessage = handleDeepgramMessage;
    socket.onerror = () => {
      clearTimeout(timeout);
      reject(new Error('Deepgram に接続できませんでした。APIキーを確認してください。'));
    };
    socket.onclose = (event) => {
      clearInterval(keepAliveTimer);
      keepAliveTimer = null;
      if (running) {
        sendOverlay('LT_STATUS', {
          state: 'error',
          message: `Deepgram 接続が終了しました (${event.code})`
        });
      }
    };
  });
}

async function setupAudio(streamId) {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: 'tab',
        chromeMediaSourceId: streamId
      }
    },
    video: false
  });

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule(chrome.runtime.getURL('offscreen/pcm-worklet.js'));

  sourceNode = audioContext.createMediaStreamSource(mediaStream);

  // Preserve original tab audio for the viewer.
  sourceNode.connect(audioContext.destination);

  workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');
  muteGain = audioContext.createGain();
  muteGain.gain.value = 0;
  workletNode.connect(muteGain).connect(audioContext.destination);
  sourceNode.connect(workletNode);

  workletNode.port.onmessage = (event) => {
    if (!running || !deepgramSocket || deepgramSocket.readyState !== WebSocket.OPEN) return;
    const input = event.data instanceof Float32Array ? event.data : new Float32Array(event.data);
    const downsampled = downsampleBuffer(input, audioContext.sampleRate, 16000);
    const pcm16 = floatTo16BitPCM(downsampled);
    deepgramSocket.send(pcm16.buffer);
  };
}

async function stopAll() {
  running = false;
  finalizedPieces = [];
  translateSequence += 1000;

  if (deepgramSocket) {
    try {
      if (deepgramSocket.readyState === WebSocket.OPEN) {
        deepgramSocket.send(JSON.stringify({ type: 'Finalize' }));
        deepgramSocket.send(JSON.stringify({ type: 'CloseStream' }));
      }
      deepgramSocket.close();
    } catch {}
    deepgramSocket = null;
  }

  if (keepAliveTimer) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }

  workletNode?.disconnect();
  sourceNode?.disconnect();
  muteGain?.disconnect();
  workletNode = null;
  sourceNode = null;
  muteGain = null;

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  if (audioContext) {
    await audioContext.close().catch(() => {});
    audioContext = null;
  }

  sendOverlay('LT_STATUS', { state: 'stopped', message: '停止しました' });
  currentTabId = null;
}

async function startAll(message) {
  await stopAll();
  currentTabId = message.tabId;
  settings = message.settings;

  if (!settings?.deepgramApiKey) throw new Error('Deepgram APIキーを設定してください。');

  sendOverlay('LT_STATUS', { state: 'starting', message: '音声を取得しています…' });
  await openDeepgramSocket();
  running = true;
  await setupAudio(message.streamId);
  sendOverlay('LT_STATUS', { state: 'running', message: 'ライブ翻訳中' });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== 'offscreen') return;

  (async () => {
    try {
      if (message.type === 'START_CAPTURE') {
        await startAll(message);
        sendResponse({ ok: true });
      } else if (message.type === 'STOP_CAPTURE') {
        await stopAll();
        sendResponse({ ok: true });
      } else if (message.type === 'GET_STATUS') {
        sendResponse({ ok: true, running, tabId: currentTabId });
      } else {
        sendResponse({ ok: false, error: 'Unknown offscreen message' });
      }
    } catch (error) {
      await stopAll().catch(() => {});
      sendResponse({ ok: false, error: error?.message || String(error) });
    }
  })();

  return true;
});

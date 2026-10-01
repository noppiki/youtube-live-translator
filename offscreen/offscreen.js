let mediaStream = null;
let audioContext = null;
let sourceNode = null;
let workletNode = null;
let muteGain = null;
let activeSocket = null;
let activeProvider = null;
let keepAliveTimer = null;
let currentTabId = null;
let running = false;
let settings = null;
let finalizedPieces = [];
let translatorCache = new Map();
let translateSequence = 0;
let nextGenericUtteranceId = 1;
let speakerTimeline = [];
let recentUtterances = new Map();
let utteranceTranslationSeq = new Map();
let finalTranslationCache = new Map();
let lockedUtteranceSpeakers = new Map();
let speakerProfiles = new Map();
let speakerInferenceSession = null;
let speakerInferenceBusy = false;
let speakerInferenceTimer = null;
let finalizedConversation = [];

const LANGUAGE_CODES = {
  English: 'en', Japanese: 'ja', Korean: 'ko', Chinese: 'zh',
  Spanish: 'es', French: 'fr', German: 'de', Italian: 'it',
  Portuguese: 'pt', Russian: 'ru', Arabic: 'ar', Hindi: 'hi',
  Dutch: 'nl', Turkish: 'tr', Thai: 'th', Vietnamese: 'vi',
  Indonesian: 'id', Malay: 'ms'
};

const QWEN_LANGUAGES = {
  en: 'English', ja: 'Japanese', ko: 'Korean', zh: 'Chinese',
  es: 'Spanish', fr: 'French', de: 'German', it: 'Italian',
  pt: 'Portuguese', ru: 'Russian', ar: 'Arabic', hi: 'Hindi',
  nl: 'Dutch', tr: 'Turkish', th: 'Thai', vi: 'Vietnamese',
  id: 'Indonesian', ms: 'Malay'
};

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

function normalizeSourceLanguage(language) {
  if (LANGUAGE_CODES[language]) return LANGUAGE_CODES[language];
  if (!language || language === 'auto' || language === 'multi') {
    return settings.sourceLanguage === 'auto' || settings.sourceLanguage === 'multi'
      ? 'en'
      : settings.sourceLanguage;
  }
  const lower = String(language).toLowerCase();
  if (LANGUAGE_CODES[language]) return LANGUAGE_CODES[language];
  if (/^[a-z]{2}(-[A-Z]{2})?$/.test(String(language))) return lower.slice(0, 2);
  return lower;
}

function recentTranscript(text) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  if (clean.length <= 260) return clean;
  const tail = clean.slice(-260);
  const cut = tail.search(/[.!?。！？]\s+/);
  return cut >= 0 ? tail.slice(cut + 1).trim() : tail;
}

async function getTranslator(sourceLanguage, targetLanguage) {
  const source = normalizeSourceLanguage(sourceLanguage);
  const target = (targetLanguage || 'ja').split('-')[0].toLowerCase();
  if (source === target) return null;
  if (!('Translator' in self)) {
    throw new Error('Chrome Translator API が利用できません。Chrome 138+ のデスクトップ版を使用してください。');
  }

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

function cleanTokenText(tokens) {
  return String((tokens || []).join(''))
    .replace(/▁/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function speakerAtTime(ms) {
  if (!Number.isFinite(ms)) return null;
  let speaker = null;
  for (const point of speakerTimeline) {
    if (point.changeAtMs <= ms) speaker = point.speaker;
    else break;
  }
  return speaker;
}

function splitFinalBySpeaker(data) {
  const tokens = Array.isArray(data.tokenStrings) ? data.tokenStrings : [];
  const times = Array.isArray(data.tokenTimestampsMs) ? data.tokenTimestampsMs : [];
  if (!tokens.length || tokens.length !== times.length || !speakerTimeline.length) return null;

  const groups = [];
  let current = null;

  for (let i = 0; i < tokens.length; i += 1) {
    const speaker = speakerAtTime(times[i]);
    if (!current || current.speaker !== speaker) {
      current = { speaker, tokens: [], times: [] };
      groups.push(current);
    }
    current.tokens.push(tokens[i]);
    current.times.push(times[i]);
  }

  const useful = groups
    .map((group) => ({
      speaker: group.speaker,
      text: cleanTokenText(group.tokens),
      startMs: group.times[0],
      endMs: group.times[group.times.length - 1]
    }))
    .filter((group) => group.text);

  return useful.length > 1 ? useful : null;
}

async function emitFinalSpeakerSegments(data) {
  const groups = splitFinalBySpeaker(data);
  if (!groups) return false;

  for (let i = 0; i < groups.length; i += 1) {
    const group = groups[i];
    const segmentId = Number(data.utteranceId) * 100 + i + 1;
    lockedUtteranceSpeakers.set(segmentId, group.speaker);
    await emitUtterance({
      utteranceId: segmentId,
      text: group.text,
      sourceLanguage: data.language || settings.sourceLanguage,
      final: true,
      startMs: group.startMs,
      endMs: group.endMs,
      forcedSpeaker: group.speaker
    });
  }
  return true;
}

async function emitUtterance({
  utteranceId,
  text,
  sourceLanguage,
  final,
  startMs = null,
  endMs = null,
  forcedSpeaker = null
}) {
  const displayText = recentTranscript(text);
  if (!displayText) return;

  const id = Number.isInteger(utteranceId) ? utteranceId : nextGenericUtteranceId;
  if (!Number.isInteger(utteranceId) && final) nextGenericUtteranceId += 1;

  if (Number.isFinite(startMs) || Number.isFinite(endMs)) {
    recentUtterances.set(id, {
      startMs: Number.isFinite(startMs) ? startMs : null,
      endMs: Number.isFinite(endMs) ? endMs : null,
      text: displayText,
      final: Boolean(final)
    });
    if (recentUtterances.size > 12) {
      const oldest = [...recentUtterances.keys()].sort((a, b) => a - b)[0];
      recentUtterances.delete(oldest);
    }
  }

  const speaker = Number.isInteger(forcedSpeaker)
    ? forcedSpeaker
    : (final ? (lockedUtteranceSpeakers.get(id) ?? speakerForUtterance(id)) : null);

  // Partial ASR updates are intentionally NOT translated.
  // This keeps the original transcript live while preventing the translated
  // sentence from being rewritten on every recognition update.
  if (!final) {
    sendOverlay('LT_UTTERANCE', {
      utteranceId: id,
      original: displayText,
      final: false,
      speaker,
      translationPending: false,
      startMs,
      endMs
    });
    return;
  }

  const cached = finalTranslationCache.get(id);
  if (cached?.source === displayText) {
    sendOverlay('LT_UTTERANCE', {
      utteranceId: id,
      original: displayText,
      translated: cached.translated,
      final: true,
      speaker,
      translationPending: false,
      sourceLanguage: normalizeSourceLanguage(sourceLanguage),
      startMs,
      endMs
    });
    return;
  }

  const sequence = ++translateSequence;
  utteranceTranslationSeq.set(id, sequence);

  sendOverlay('LT_UTTERANCE', {
    utteranceId: id,
    original: displayText,
    final: true,
    speaker,
    translationPending: true,
    startMs,
    endMs
  });

  try {
    const translated = await translateText(displayText, sourceLanguage);
    if (!running || utteranceTranslationSeq.get(id) !== sequence) return;

    finalTranslationCache.set(id, {
      source: displayText,
      translated
    });
    if (finalTranslationCache.size > 20) {
      const oldest = [...finalTranslationCache.keys()].sort((a, b) => a - b)[0];
      finalTranslationCache.delete(oldest);
    }

    const resolvedSpeaker = Number.isInteger(forcedSpeaker)
      ? forcedSpeaker
      : (lockedUtteranceSpeakers.get(id) ?? speakerForUtterance(id));
    if (Number.isInteger(resolvedSpeaker)) lockedUtteranceSpeakers.set(id, resolvedSpeaker);
    sendOverlay('LT_UTTERANCE', {
      utteranceId: id,
      original: displayText,
      translated,
      final: true,
      speaker: resolvedSpeaker,
      translationPending: false,
      sourceLanguage: normalizeSourceLanguage(sourceLanguage),
      startMs,
      endMs
    });

    rememberFinalUtterance({
      utteranceId: id,
      text: displayText,
      speaker: resolvedSpeaker,
      startMs,
      endMs
    });
  } catch (error) {
    sendOverlay('LT_UTTERANCE', {
      utteranceId: id,
      original: displayText,
      final: true,
      speaker: speakerForUtterance(id),
      translationPending: false,
      startMs,
      endMs
    });
    sendOverlay('LT_STATUS', { state: 'error', message: error?.message || String(error) });
  }
}

function speakerForUtterance(utteranceId) {
  const interval = recentUtterances.get(utteranceId);
  if (!interval) return null;

  const start = Number.isFinite(interval.startMs) ? interval.startMs : 0;
  const end = Number.isFinite(interval.endMs) ? interval.endMs : start;
  const midpoint = start + Math.max(0, end - start) / 2;

  let speaker = null;
  for (const point of speakerTimeline) {
    if (point.changeAtMs <= midpoint) speaker = point.speaker;
    else break;
  }
  return speaker;
}

function addSpeakerPoint(speaker, changeAtMs) {
  if (!Number.isInteger(speaker) || !Number.isFinite(changeAtMs)) return;

  const existing = speakerTimeline.find(
    (point) => point.speaker === speaker && Math.abs(point.changeAtMs - changeAtMs) < 120
  );
  if (!existing) {
    speakerTimeline.push({ speaker, changeAtMs });
    speakerTimeline.sort((a, b) => a.changeAtMs - b.changeAtMs);
    if (speakerTimeline.length > 32) speakerTimeline = speakerTimeline.slice(-32);
  }

  for (const utteranceId of recentUtterances.keys()) {
    const stored = recentUtterances.get(utteranceId);
    if (!stored?.final || lockedUtteranceSpeakers.has(utteranceId)) continue;
    const resolved = speakerForUtterance(utteranceId);
    if (Number.isInteger(resolved)) {
      lockedUtteranceSpeakers.set(utteranceId, resolved);
      sendOverlay('LT_UTTERANCE_SPEAKER', {
        utteranceId,
        speaker: resolved
      });

      if (stored?.text) {
        rememberFinalUtterance({
          utteranceId,
          text: stored.text,
          speaker: resolved,
          startMs: stored.startMs,
          endMs: stored.endMs
        });
      }
    }
  }
}

function profileLabelForOverlay(speaker, profile) {
  sendOverlay('LT_SPEAKER_PROFILE', {
    speaker,
    name: profile?.name || '',
    role: profile?.role || '',
    confidence: Number(profile?.confidence || 0),
    source: profile?.source || ''
  });
}

function rememberFinalUtterance({ utteranceId, text, speaker, startMs, endMs }) {
  if (!text?.trim()) return;
  const idx = finalizedConversation.findIndex((u) => u.utteranceId === utteranceId);
  const item = {
    utteranceId,
    text: text.trim(),
    speaker: Number.isInteger(speaker) ? speaker : null,
    startMs: Number.isFinite(startMs) ? startMs : null,
    endMs: Number.isFinite(endMs) ? endMs : null
  };
  if (idx >= 0) finalizedConversation[idx] = item;
  else finalizedConversation.push(item);

  finalizedConversation = finalizedConversation.slice(-18);
  scheduleSpeakerInference();
}

function inferExplicitNames() {
  const bySpeaker = new Map();
  const knownSpeakers = [...new Set(
    finalizedConversation.map((u) => u.speaker).filter(Number.isInteger)
  )];

  for (const item of finalizedConversation) {
    if (!Number.isInteger(item.speaker)) continue;
    const text = item.text;

    const selfIntro = text.match(/\b(?:i(?:'m| am)|my name is)\s+([A-Z][A-Za-z.'-]{1,30}(?:\s+[A-Z][A-Za-z.'-]{1,30})?)/i);
    if (selfIntro) {
      bySpeaker.set(item.speaker, {
        name: selfIntro[1].trim(),
        role: '',
        confidence: 0.96,
        source: 'self-introduction'
      });
      continue;
    }

    if (knownSpeakers.length === 2) {
      const addressed = text.match(/\b(?:thanks|thank you|welcome|good to have you|over to you)[,\s]+([A-Z][A-Za-z.'-]{1,30})(?:\b|[,.!?])/i);
      if (addressed) {
        const other = knownSpeakers.find((speaker) => speaker !== item.speaker);
        if (Number.isInteger(other) && !bySpeaker.has(other)) {
          bySpeaker.set(other, {
            name: addressed[1].trim(),
            role: '',
            confidence: 0.82,
            source: 'direct-address'
          });
        }
      }
    }
  }

  for (const [speaker, profile] of bySpeaker) {
    const previous = speakerProfiles.get(speaker);
    if (!previous || profile.confidence > Number(previous.confidence || 0)) {
      speakerProfiles.set(speaker, profile);
      profileLabelForOverlay(speaker, profile);
    }
  }
}

function scheduleSpeakerInference() {
  if (!settings?.speakerNameInference) return;
  inferExplicitNames();
  clearTimeout(speakerInferenceTimer);
  speakerInferenceTimer = setTimeout(() => runSpeakerInference().catch(() => {}), 1200);
}

async function getSpeakerInferenceSession() {
  if (speakerInferenceSession) return speakerInferenceSession;
  if (!('LanguageModel' in self)) return null;

  const options = {
    expectedInputs: [{ type: 'text', languages: ['en', 'ja'] }],
    expectedOutputs: [{ type: 'text', languages: ['en'] }]
  };
  const availability = await LanguageModel.availability(options);
  if (availability !== 'available') return null;

  speakerInferenceSession = await LanguageModel.create(options);
  return speakerInferenceSession;
}

async function runSpeakerInference() {
  if (speakerInferenceBusy || !settings?.speakerNameInference) return;
  const speakers = [...new Set(finalizedConversation.map((u) => u.speaker).filter(Number.isInteger))];
  if (!speakers.length || finalizedConversation.length < 2) return;

  const session = await getSpeakerInferenceSession();
  if (!session) return;

  speakerInferenceBusy = true;
  try {
    const page = settings.pageContext || {};
    const transcript = finalizedConversation.map((u) => {
      const label = Number.isInteger(u.speaker) ? `SPEAKER_${u.speaker}` : 'UNKNOWN';
      return `${label}: ${u.text}`;
    }).join('\n');

    const schema = {
      type: 'object',
      properties: {
        speakers: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              speaker: { type: 'integer' },
              name: { type: 'string' },
              role: { type: 'string' },
              confidence: { type: 'number', minimum: 0, maximum: 1 }
            },
            required: ['speaker', 'name', 'role', 'confidence'],
            additionalProperties: false
          }
        }
      },
      required: ['speakers'],
      additionalProperties: false
    };

    const prompt = `Infer speaker names and roles from a live-stream transcript.
Rules:
- Never identify a person from voice characteristics.
- Use only the supplied text and page metadata.
- A name should be non-empty only when supported by explicit or strong textual evidence.
- If uncertain about a name, return an empty name and infer a role such as Host, Guest, Interviewer, Presenter, Commentator.
- Confidence is about the proposed name/role mapping, from 0 to 1.
- Speaker numbers must match the supplied SPEAKER_N IDs.

Page title: ${page.title || ''}
Channel: ${page.channel || ''}
Description: ${page.description || ''}

Transcript:
${transcript}`;

    const raw = await session.prompt(prompt, { responseConstraint: schema });
    const result = JSON.parse(raw);

    for (const candidate of result.speakers || []) {
      if (!Number.isInteger(candidate.speaker) || !speakers.includes(candidate.speaker)) continue;

      const profile = {
        name: String(candidate.name || '').trim().slice(0, 80),
        role: String(candidate.role || '').trim().slice(0, 60),
        confidence: Math.max(0, Math.min(1, Number(candidate.confidence || 0))),
        source: 'chrome-prompt-api'
      };

      const previous = speakerProfiles.get(candidate.speaker);
      if (!previous || profile.confidence >= Number(previous.confidence || 0) + 0.05 ||
          (!previous.name && profile.name && profile.confidence >= 0.7)) {
        speakerProfiles.set(candidate.speaker, profile);
        profileLabelForOverlay(candidate.speaker, profile);
      }
    }
  } finally {
    speakerInferenceBusy = false;
  }
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

  if (settings.sourceLanguage === 'auto') params.set('detect_language', 'true');
  else if (settings.sourceLanguage === 'multi') params.set('language', 'multi');
  else params.set('language', settings.sourceLanguage || 'en');

  return `wss://api.deepgram.com/v1/listen?${params.toString()}`;
}

function handleDeepgramMessage(event) {
  let data;
  try { data = JSON.parse(event.data); } catch { return; }

  if (data.type === 'Results') {
    const transcript = data.channel?.alternatives?.[0]?.transcript?.trim();
    if (!transcript) return;
    const detected = data.channel?.detected_language || data.channel?.alternatives?.[0]?.languages?.[0];

    if (data.is_final) {
      finalizedPieces.push(transcript);
      if (data.speech_final) {
        const complete = finalizedPieces.join(' ').replace(/\s+/g, ' ').trim();
        finalizedPieces = [];
        emitUtterance({
          text: complete,
          sourceLanguage: detected,
          final: true
        });
      } else {
        emitUtterance({
          text: finalizedPieces.join(' '),
          sourceLanguage: detected,
          final: false
        });
      }
    } else {
      const prefix = finalizedPieces.length ? `${finalizedPieces.join(' ')} ` : '';
      emitUtterance({
        text: `${prefix}${transcript}`.trim(),
        sourceLanguage: detected,
        final: false
      });
    }
  }
}

function openDeepgramSocket() {
  return new Promise((resolve, reject) => {
    if (!settings.deepgramApiKey) {
      reject(new Error('Deepgram APIキーが未設定です。'));
      return;
    }

    const socket = new WebSocket(buildDeepgramUrl(), ['token', settings.deepgramApiKey]);
    socket.binaryType = 'arraybuffer';
    const timeout = setTimeout(() => reject(new Error('Deepgram 接続がタイムアウトしました。')), 10000);

    socket.onopen = () => {
      clearTimeout(timeout);
      activeSocket = socket;
      activeProvider = 'deepgram';
      keepAliveTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'KeepAlive' }));
      }, 8000);
      resolve();
    };
    socket.onmessage = handleDeepgramMessage;
    socket.onerror = () => {
      clearTimeout(timeout);
      reject(new Error('Deepgram に接続できませんでした。'));
    };
    socket.onclose = (event) => {
      clearInterval(keepAliveTimer);
      keepAliveTimer = null;
      if (running && activeProvider === 'deepgram') {
        sendOverlay('LT_STATUS', { state: 'error', message: `Deepgram 接続終了 (${event.code})` });
      }
    };
  });
}

function openLocalSocket() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket('ws://127.0.0.1:8765/stream');
    socket.binaryType = 'arraybuffer';
    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        socket.close();
        reject(new Error('ローカルAIの準備が10分以内に完了しませんでした。モデル準備またはログを確認してください。'));
      }
    }, 600000);

    socket.onopen = () => {
      const language = QWEN_LANGUAGES[settings.sourceLanguage] || null;
      const context = String(settings.domainTerms || '')
        .split(/\n|,/)
        .map((v) => v.trim())
        .filter(Boolean)
        .join(' ');
      socket.send(JSON.stringify({
        type: 'config',
        model: settings.localModel || 'moona3k/mlx-qwen3-asr-0.6b-4bit',
        language,
        context,
        chunkSizeSec: 1.0,
        maxContextSec: 30.0,
        localBackend: settings.localBackend || 'auto',
        diarization: Boolean(settings.diarization)
      }));
    };

    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }

      if (data.type === 'preparing') {
        sendOverlay('LT_STATUS', {
          state: 'preparing',
          message: data.message || 'ローカルAIモデルを準備しています…'
        });
        return;
      }

      if (data.type === 'ready') {
        clearTimeout(timeout);
        if (!settled) {
          settled = true;
          activeSocket = socket;
          activeProvider = data.backend || 'local';
          if (data.warning) {
            sendOverlay('LT_STATUS', { state: 'warning', message: data.warning });
          }
          resolve();
        }
        return;
      }
      if (data.type === 'utterance') {
        if (data.final && Array.isArray(data.tokenStrings) && Array.isArray(data.tokenTimestampsMs)) {
          const split = await emitFinalSpeakerSegments(data);
          if (!split) {
            emitUtterance({
              utteranceId: data.utteranceId,
              text: data.text || '',
              sourceLanguage: data.language || settings.sourceLanguage,
              final: true,
              startMs: data.startMs,
              endMs: data.endMs
            });
          }
        } else {
          emitUtterance({
            utteranceId: data.utteranceId,
            text: data.text || '',
            sourceLanguage: data.language || settings.sourceLanguage,
            final: Boolean(data.final),
            startMs: data.startMs,
            endMs: data.endMs
          });
        }
      } else if (data.type === 'partial' || data.type === 'final') {
        emitUtterance({
          text: data.text || data.stableText || '',
          sourceLanguage: data.language || settings.sourceLanguage,
          final: data.type === 'final'
        });
      } else if (data.type === 'speaker') {
        addSpeakerPoint(data.speaker, data.changeAtMs);
      } else if (data.type === 'warning') {
        sendOverlay('LT_STATUS', { state: 'warning', message: data.message || 'ローカルAI警告' });
      } else if (data.type === 'error') {
        const message = `ローカルSTT: ${data.message || '不明なエラー'}`;
        sendOverlay('LT_STATUS', { state: 'error', message });
        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          socket.close();
          reject(new Error(message));
        }
      }
    };

    socket.onerror = () => {
      clearTimeout(timeout);
      if (!settled) {
        settled = true;
        reject(new Error('ローカルエンジンが見つかりません。'));
      }
    };
    socket.onclose = () => {
      if (running && activeProvider !== 'deepgram') {
        sendOverlay('LT_STATUS', { state: 'error', message: 'ローカルSTTとの接続が終了しました。' });
      }
    };
  });
}

async function openProvider() {
  const mode = settings.engineMode || 'auto';

  if (mode === 'local') {
    await openLocalSocket();
    return;
  }
  if (mode === 'deepgram') {
    await openDeepgramSocket();
    return;
  }

  try {
    await openLocalSocket();
  } catch (localError) {
    if (!settings.deepgramApiKey) {
      throw new Error(`${localError.message} Deepgram APIキーも未設定です。`);
    }
    sendOverlay('LT_STATUS', { state: 'starting', message: 'ローカル未接続。Deepgramへ切り替えます…' });
    await openDeepgramSocket();
  }
}

async function setupAudio(streamId) {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } },
    video: false
  });

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule(chrome.runtime.getURL('offscreen/pcm-worklet.js'));

  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  sourceNode.connect(audioContext.destination);

  workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');
  muteGain = audioContext.createGain();
  muteGain.gain.value = 0;
  workletNode.connect(muteGain).connect(audioContext.destination);
  sourceNode.connect(workletNode);

  workletNode.port.onmessage = (event) => {
    if (!running || !activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    const input = event.data instanceof Float32Array ? event.data : new Float32Array(event.data);
    const downsampled = downsampleBuffer(input, audioContext.sampleRate, 16000);
    const pcm16 = floatTo16BitPCM(downsampled);
    activeSocket.send(pcm16.buffer);
  };
}

async function stopAll({ announce = true } = {}) {
  running = false;
  finalizedPieces = [];
  translateSequence += 1000;

  if (activeSocket) {
    try {
      if (activeSocket.readyState === WebSocket.OPEN) {
        if (activeProvider !== 'deepgram') activeSocket.send(JSON.stringify({ type: 'finalize' }));
        else {
          activeSocket.send(JSON.stringify({ type: 'Finalize' }));
          activeSocket.send(JSON.stringify({ type: 'CloseStream' }));
        }
      }
      activeSocket.close();
    } catch {}
    activeSocket = null;
  }
  activeProvider = null;
  nextGenericUtteranceId = 1;
  speakerTimeline = [];
  recentUtterances = new Map();
  utteranceTranslationSeq = new Map();
  finalTranslationCache = new Map();
  lockedUtteranceSpeakers = new Map();
  speakerProfiles = new Map();
  finalizedConversation = [];
  clearTimeout(speakerInferenceTimer);
  speakerInferenceTimer = null;
  speakerInferenceBusy = false;
  if (speakerInferenceSession) {
    try { speakerInferenceSession.destroy?.(); } catch {}
    speakerInferenceSession = null;
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

  if (announce && currentTabId) {
    sendOverlay('LT_STATUS', { state: 'stopped', message: '停止しました' });
  }
  currentTabId = null;
}

async function startAll(message) {
  await stopAll();
  currentTabId = message.tabId;
  settings = message.settings;

  sendOverlay('LT_STATUS', { state: 'starting', message: '音声認識エンジンへ接続しています…' });
  await openProvider();
  await setupAudio(message.streamId);
  running = true;

  const label =
    activeProvider === 'fluid' ? 'FluidAudio · Parakeet' :
    activeProvider === 'qwen' ? 'Qwen3-ASR' :
    activeProvider === 'local' ? 'ローカルAI' :
    'Deepgram';
  sendOverlay('LT_STATUS', { state: 'running', message: `ライブ翻訳中 · ${label}` });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== 'offscreen') return;

  (async () => {
    try {
      if (message.type === 'START_CAPTURE') {
        await startAll(message);
        sendResponse({ ok: true, provider: activeProvider });
      } else if (message.type === 'STOP_CAPTURE') {
        await stopAll();
        sendResponse({ ok: true });
      } else if (message.type === 'GET_STATUS') {
        sendResponse({ ok: true, running, tabId: currentTabId, provider: activeProvider });
      } else {
        sendResponse({ ok: false, error: 'Unknown offscreen message' });
      }
    } catch (error) {
      const message = error?.message || String(error);
      sendOverlay('LT_STATUS', { state: 'error', message });
      await stopAll({ announce: false }).catch(() => {});
      sendResponse({ ok: false, error: message });
    }
  })();

  return true;
});

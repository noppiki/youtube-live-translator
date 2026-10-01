# Live Translator for YouTube

YouTube Live のタブ音声をリアルタイム文字起こしし、Chrome の組み込み Translator API で翻訳字幕を動画上へ表示する Manifest V3 拡張です。

## v0.3

- 翻訳字幕サイズを **70〜180%** で変更可能
- 設定変更を開いているYouTubeへ即時反映
- Qwen3-ASRがインストール済み・停止中なら **「ローカル起動」** からワンクリック起動
- Chrome Native Messagingの小さな起動ヘルパーを追加
- ローカルQwen3サービスを常駐必須から **オンデマンド起動** に変更

## 音声認識

デフォルトは **ローカル優先** です。

1. Apple Silicon Mac 上の Qwen3-ASR MLX を探す
2. 接続できればローカルSTTを使用（API料金なし）
3. 接続できず Deepgram APIキーが設定されていれば Nova-3 へ自動フォールバック
4. 翻訳は Chrome Translator API を使用

### 推奨モデル

- バランス: `moona3k/mlx-qwen3-asr-0.6b-4bit`（約517MB）
- 高精度: `moona3k/mlx-qwen3-asr-1.7b-4bit`（約1.2GB）

## 構成

- 音声取得: `chrome.tabCapture`
- 長時間音声処理: `chrome.offscreen`
- ローカルSTT: Qwen3-ASR / MLX
- クラウドSTT: Deepgram Nova-3（任意・フォールバック）
- 翻訳: Chrome Translator API
- 字幕描画: YouTubeページ上のcontent script
- 音声: PCM16 / mono / 16kHz
- ローカルSTT: `ws://127.0.0.1:8765/stream`
- ローカル起動: Chrome Native Messaging → macOS LaunchAgent

## Chrome拡張の導入

1. このリポジトリをcloneまたはZIPで取得
2. Chromeで `chrome://extensions` を開く
3. 「デベロッパー モード」をON
4. 「パッケージ化されていない拡張機能を読み込む」
5. このリポジトリのフォルダを選択

manifestを更新した場合は、`chrome://extensions` で拡張を再読み込みしてください。

## ローカルエンジンの導入（Apple Silicon Mac）

### 推奨

拡張を開き、

**ローカルエンジン → 初回インストール / 起動ヘルパー更新**

に表示されるコマンドをコピーしてターミナルへ貼り付けます。

そのコマンドには現在のChrome拡張IDが自動で含まれます。Native Messagingの `allowed_origins` はワイルドカードを使えないため、ワンクリック起動にはこのID登録が必要です。

既にQwen3-ASRを導入済みの場合でも、v0.3の「ローカル起動」ボタンを使うには最新版インストーラを一度だけ再実行してください。

### ローカルSTTだけを導入する場合

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash
```

この形式では拡張IDが渡らないため、STT本体は入りますが「ローカル起動」ボタン用Native Messagingホストは登録されません。

### インストーラが行うこと

- `uv` の確認/導入
- Python 3.12隔離環境
- `mlx-qwen3-asr` / aiohttp / numpy
- 推奨0.6Bモデル
- `127.0.0.1:8765` のローカルサーバー
- macOS LaunchAgent
- Chrome Native Messaging起動ヘルパー

ファイルは主に以下へ置きます。

```
~/Library/Application Support/YouTubeLiveTranslator/
```

Native Messaging manifest:

```
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.noppiki.youtube_live_translator.json
```

システムPythonは変更しません。

### ローカル起動

拡張の状態表示は以下です。

- **接続済み**: Qwen3サービス稼働中
- **停止中**: インストール済み。**ローカル起動**で開始可能
- **ヘルパー未設定**: v0.3インストーラを再実行
- **未インストール**: ローカルエンジンを導入

サービスはv0.3から常時KeepAliveではなく、必要時に起動する構成です。

### アンインストール

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/uninstall-macos.sh | bash
```

## 翻訳字幕サイズ

ポップアップの **翻訳字幕サイズ** で70〜180%を10%刻みで変更できます。

- デフォルト: 100%
- 設定は `chrome.storage.local` に保存
- YouTubeを再読み込みしても維持
- スライダー操作中に現在のYouTubeタブへ即時反映

## ローカルモデル

設定画面から次のモデルを選び、「モデル準備」を押すとダウンロード/ロードできます。

- Qwen3-ASR 0.6B 4-bit
- Qwen3-ASR 1.7B 4-bit

## 固有名詞・専門用語

改行区切りで入力した語句をQwen3-ASRの `context` に渡します。

例:

```
OpenAI
Anthropic
Claude
Gemini
Cursor
Codex
MCP
NVIDIA
```

## ローカルAPI

### ヘルスチェック

```bash
curl http://127.0.0.1:8765/health
```

### モデル一覧

```bash
curl http://127.0.0.1:8765/models
```

### Streaming WebSocket

```
ws://127.0.0.1:8765/stream
```

## セキュリティ

ローカルSTTサーバーは `127.0.0.1` のみにbindします。

ワンクリック起動にはChromeのNative Messagingを使います。Native Messagingホストはインストール時に渡された**現在の拡張IDだけ**を `allowed_origins` に登録します。ChromeではNative Messagingホストの許可originにワイルドカードを利用できません。

Native Messagingホスト自身が行える操作は、このプロジェクトのmacOS LaunchAgentの状態確認と起動だけです。

Deepgram APIキーは `chrome.storage.local` へ保存します。共有APIキーを拡張へ埋め込まないでください。

## 今後

- YouTube公式ライブ字幕が存在する場合はSTTを省略
- 字幕の文脈バッファ/自然化
- 原文字幕ON/OFF、位置、背景透明度
- ローカルサービス停止ボタン
- Twitch / X Live対応
- SRT / VTTログ保存
- Windows向けローカルエンジン

## License

MIT License. See [`LICENSE`](LICENSE).

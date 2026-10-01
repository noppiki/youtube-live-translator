# Live Translator for YouTube

YouTube Live のタブ音声をリアルタイム文字起こしし、Chrome の組み込み Translator API で翻訳字幕を動画上へ表示する Manifest V3 拡張です。

## v0.2: ローカルAI対応

デフォルトは **ローカル優先** です。

1. Apple Silicon Mac 上の Qwen3-ASR MLX を探す
2. 接続できればローカルSTTを使用（API料金なし）
3. 接続できず Deepgram APIキーが設定されていれば Nova-3 へ自動フォールバック
4. 翻訳は Chrome Translator API を使用

### 推奨モデル

- バランス: `moona3k/mlx-qwen3-asr-0.6b-4bit`（約517MB）
- 高精度: `moona3k/mlx-qwen3-asr-1.7b-4bit`（約1.2GB）

0.6B 4-bit はデコーダ4-bit + 音声エンコーダ8-bitの量子化を使い、軽量化しながら音声認識精度の低下を抑えたモデルです。

## 構成

- 音声取得: `chrome.tabCapture`
- 長時間音声処理: `chrome.offscreen`
- ローカルSTT: Qwen3-ASR / MLX
- クラウドSTT: Deepgram Nova-3（任意・フォールバック）
- 翻訳: Chrome Translator API
- 字幕描画: YouTubeページ上のcontent script
- 音声: PCM16 / mono / 16kHz
- ローカル通信: `ws://127.0.0.1:8765/stream`

## Chrome拡張の導入

1. このリポジトリをcloneまたはZIPで取得
2. Chromeで `chrome://extensions` を開く
3. 「デベロッパー モード」をON
4. 「パッケージ化されていない拡張機能を読み込む」
5. このリポジトリのフォルダを選択

## ローカルエンジンの導入（Apple Silicon Mac）

拡張の「初回インストール」に表示されるコマンド、または以下をターミナルへ1回貼り付けます。

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash
```

インストーラは以下を行います。

- `uv` の確認/導入
- Python 3.12の隔離環境作成
- `mlx-qwen3-asr` とローカルサーバー依存関係の導入
- 推奨0.6Bモデルのダウンロード
- `127.0.0.1:8765` のローカルサーバー設置
- macOS LaunchAgent登録
- Macログイン時の自動起動

ファイルは原則ここへまとめます。

```
~/Library/Application Support/YouTubeLiveTranslator/
```

システムPythonは変更しません。

### アンインストール

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/uninstall-macos.sh | bash
```

## 拡張からできること

### 音声認識モード

- **自動（推奨）**: ローカル → Deepgram
- **ローカルのみ**: 完全無料
- **Deepgramのみ**: クラウドSTT固定

### ローカルモデル

設定画面から次のモデルを選び、「モデル準備」を押すとダウンロード/ロードできます。

- Qwen3-ASR 0.6B 4-bit
- Qwen3-ASR 1.7B 4-bit

### 固有名詞・専門用語

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

技術系ライブなどで固有名詞の認識改善に使えます。

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

PCM16 / mono / 16kHz をbinary frameとして送信します。最初にJSON設定を送ります。

```json
{
  "type": "config",
  "model": "moona3k/mlx-qwen3-asr-0.6b-4bit",
  "language": "English",
  "context": "OpenAI Anthropic Claude Cursor",
  "chunkSizeSec": 1.0,
  "maxContextSec": 30.0
}
```

## Deepgram

ローカルエンジンを使わない場合、または自動モードのフォールバックとしてDeepgram Nova-3を利用できます。

Deepgram APIキーは `chrome.storage.local` へ保存します。公開配布向けに共有APIキーを拡張へ埋め込まないでください。

## セキュリティ

ローカルサーバーは `127.0.0.1` のみにbindします。WebSocket/モデル操作はChrome拡張Originからの利用を想定しています。

インストールスクリプトを `curl | bash` で実行したくない場合は、内容を確認してからローカルで実行してください。

## 今後

- YouTube公式ライブ字幕が存在する場合はSTTを省略
- 字幕の文脈バッファ/自然化
- 原文字幕ON/OFF、位置、サイズ、背景調整
- Twitch / X Live対応
- SRT / VTTログ保存
- Windows向けローカルエンジン

## License

MIT License. See [`LICENSE`](LICENSE).

# Security

## API keys

This MVP stores the user's Deepgram API key in `chrome.storage.local` and sends it only to Deepgram for streaming speech-to-text.

Do not hard-code API keys in this repository or commit exported browser storage.

For a production Chrome Web Store release, use short-lived credentials issued by a backend rather than shipping a shared provider key in the extension.

## Reporting a vulnerability

Please open a GitHub issue that does not contain secrets. For vulnerabilities that would expose credentials, avoid posting real API keys or tokens.

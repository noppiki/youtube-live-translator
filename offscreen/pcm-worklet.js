class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.buffered = 0;
    this.targetFrames = 2048;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input?.[0]) return true;

    const channel = input[0];
    this.buffer.push(new Float32Array(channel));
    this.buffered += channel.length;

    if (this.buffered >= this.targetFrames) {
      const merged = new Float32Array(this.buffered);
      let offset = 0;
      for (const chunk of this.buffer) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      this.port.postMessage(merged, [merged.buffer]);
      this.buffer = [];
      this.buffered = 0;
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);

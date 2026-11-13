# Listening audio provenance

`study-group.wav` contains an original VerbaTrail script, synthesized locally offline. It contains no IELTS test recording or third-party script.

## Voice and license

- Synthesis engine: Piper 1.8.0, used as a local generator only. The Piper engine is GPL-3.0; the project does not bundle the engine or voice model.
- Voice: `en_US-joe-medium`, downloaded from [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices/tree/2f358b6a560e3a913ebf509b2f3344f20b367f94/en/en_US/joe/medium) at repository revision `2f358b6a560e3a913ebf509b2f3344f20b367f94`.
- The pinned [voice model card](https://huggingface.co/rhasspy/piper-voices/blob/2f358b6a560e3a913ebf509b2f3344f20b367f94/en/en_US/joe/medium/MODEL_CARD) states that Joe's recordings are CC0 and the model is fine-tuned from Piper's CC0 `rdh` base.
- Piper's [`COMMERCIAL_USE.md`](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/COMMERCIAL_USE.md) lists `en_US-joe-medium` in its CC0 training-data chain table and explains that each voice's data chain determines its use conditions. The exact model-card revision is pinned above because Piper warns that voice files with the same name can have different training ancestry.
- [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) permits copying, modifying, and redistributing the underlying recordings without attribution. This project retains this notice and model provenance for transparency. The voice model and synthesis binaries are not redistributed.

Piper's project notes that a voice-model dataset chain is its reuse guidance and that legal treatment of trained models and output can depend on jurisdiction. We therefore record the exact voice revision and continue to identify the asset as synthetic speech.

## Audio artifact

- Format: PCM WAV, mono, 22,050 Hz, 16-bit.
- Measured duration: 63.7159 seconds.
- WAV SHA-256: `F70BDDE86057BEAB65CE4BDFE510DEBB734C6DB4073F54F23E0AC52B04BCB57C`.
- Pinned ONNX voice model SHA-256 (generation input; kept outside this repository): `ABF4B998E34045CBD00EAF050DE2DE620F81DED6EB8B85A24B022A1C2B3F08D2`.
- Each quiz anchor is aligned to a separately synthesized sentence and the sentence's exact frame offsets in this file.

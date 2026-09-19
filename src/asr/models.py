"""English speech-to-text model helpers."""

import os
import tempfile
import threading
import wave

import torch
from loguru import logger


os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ.setdefault("OMP_NUM_THREADS", "2")
torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "2")))
torch.set_num_interop_threads(1)

_audio_model_en = None
_en_model_lock = threading.Lock()


def get_audio_model_en():
    global _audio_model_en
    if _audio_model_en is not None:
        return _audio_model_en

    import nemo.collections.asr as nemo_asr

    logger.info("Loading English ASR model (nvidia/parakeet-tdt-0.6b-v2)...")
    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
    try:
        from omegaconf import OmegaConf
        decoding_cfg = OmegaConf.structured(model.cfg.decoding)
        OmegaConf.update(decoding_cfg, "strategy", "greedy_batch")
        model.change_decoding_strategy(decoding_cfg, verbose=False)
    except Exception as exc:
        logger.warning(f"English ASR decoding setup failed; using defaults: {exc}")
    _audio_model_en = model
    return model


def transcribe_en_batch(audio_paths: list[str]) -> list[str]:
    model = get_audio_model_en()
    with _en_model_lock, torch.no_grad():
        transcriptions = model.transcribe(audio_paths)
        if isinstance(transcriptions, tuple):
            transcriptions = transcriptions[0]
        return [
            (item.text if hasattr(item, "text") else str(item)).strip().rstrip(".")
            for item in transcriptions
        ]


def warmup_parakeet() -> None:
    if _audio_model_en is None:
        return
    warmup_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
            warmup_path = file.name
        with wave.open(warmup_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * 16000)
        with _en_model_lock, torch.no_grad():
            _audio_model_en.transcribe([warmup_path])
    except Exception as exc:
        logger.warning(f"English ASR warmup failed: {exc}")
    finally:
        if warmup_path:
            try:
                os.unlink(warmup_path)
            except OSError:
                pass

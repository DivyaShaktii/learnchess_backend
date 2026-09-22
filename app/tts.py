"""Real-time Kokoro speech synthesis with bounded in-memory caching.

The implementation is adapted from the supplied Colab notebook. Unlike the
notebook helper, it concatenates every chunk emitted by KPipeline so longer
coach messages are never truncated.
"""

from array import array
from collections import OrderedDict
from io import BytesIO
import hashlib
import os
import threading
import wave


ALLOWED_VOICES = {
    "af_heart", "af_bella", "af_nicole", "af_sarah", "am_adam", "am_michael"
}


class KokoroSpeechService:
    sample_rate = 24_000

    def __init__(self, pipeline_factory=None, cache_size: int = 128):
        self._pipeline_factory = pipeline_factory
        self._pipeline = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self.default_voice = os.getenv("KOKORO_VOICE", "af_bella")
        self.enabled = os.getenv("KOKORO_ENABLED", "true").lower() in {"1", "true", "yes"}

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def _get_pipeline(self):
        if self._pipeline is None:
            if not self.enabled:
                raise RuntimeError("Kokoro speech is disabled")
            if self._pipeline_factory is None:
                from kokoro import KPipeline
                self._pipeline_factory = lambda: KPipeline(lang_code="a")
            self._pipeline = self._pipeline_factory()
        return self._pipeline

    @staticmethod
    def _normalise_text(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _samples_from_chunk(chunk) -> list[float]:
        value = chunk
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        if hasattr(value, "reshape"):
            value = value.reshape(-1)
        if hasattr(value, "tolist"):
            value = value.tolist()
        return [float(sample) for sample in value]

    @classmethod
    def _encode_wav(cls, samples: list[float]) -> bytes:
        pcm = array("h", (
            max(-32768, min(32767, round(sample * 32767))) for sample in samples
        ))
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(cls.sample_rate)
            wav.writeframes(pcm.tobytes())
        return output.getvalue()

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> tuple[bytes, bool]:
        clean_text = self._normalise_text(text)
        if not clean_text:
            raise ValueError("Speech text cannot be empty")
        if len(clean_text) > 500:
            raise ValueError("Speech text must be 500 characters or fewer")

        selected_voice = voice or self.default_voice
        if selected_voice not in ALLOWED_VOICES:
            raise ValueError("Unsupported Kokoro voice")
        if not 0.75 <= speed <= 1.25:
            raise ValueError("Speech speed must be between 0.75 and 1.25")

        key = hashlib.sha256(
            f"{selected_voice}|{speed:.2f}|{clean_text}".encode("utf-8")
        ).hexdigest()

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached, True

            pipeline = self._get_pipeline()
            samples: list[float] = []
            for _, _, chunk in pipeline(clean_text, voice=selected_voice, speed=speed):
                samples.extend(self._samples_from_chunk(chunk))
            if not samples:
                raise RuntimeError("Kokoro returned no audio")

            audio = self._encode_wav(samples)
            self._cache[key] = audio
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return audio, False

    def warm(self) -> None:
        self.synthesize("Coach ready.", voice=self.default_voice)


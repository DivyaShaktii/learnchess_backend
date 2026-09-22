import unittest
import wave
from io import BytesIO

from app.tts import KokoroSpeechService


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def __call__(self, text, voice, speed):
        self.calls += 1
        yield "one", "one", [0.0, 0.25]
        yield "two", "two", [-0.25, 0.5]


class KokoroSpeechServiceTests(unittest.TestCase):
    def test_concatenates_every_generated_chunk_and_caches_result(self):
        pipeline = FakePipeline()
        service = KokoroSpeechService(lambda: pipeline)

        first, first_cache_hit = service.synthesize("A longer live position message.")
        second, second_cache_hit = service.synthesize("A longer live position message.")

        self.assertFalse(first_cache_hit)
        self.assertTrue(second_cache_hit)
        self.assertEqual(first, second)
        self.assertEqual(pipeline.calls, 1)
        with wave.open(BytesIO(first), "rb") as wav:
            self.assertEqual(wav.getframerate(), 24_000)
            self.assertEqual(wav.getnframes(), 4)

    def test_rejects_unbounded_or_unknown_inputs(self):
        service = KokoroSpeechService(lambda: FakePipeline())
        with self.assertRaises(ValueError):
            service.synthesize("x" * 501)
        with self.assertRaises(ValueError):
            service.synthesize("hello", voice="unknown")


if __name__ == "__main__":
    unittest.main()

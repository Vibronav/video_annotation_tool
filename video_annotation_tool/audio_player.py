import threading
import numpy as np
import sounddevice as sd


class AudioPlayer:
    """Handles real-time audio playback synchronized with video frames."""

    def __init__(self, audio_data, audio_sr, audio_channel):
        self._stream = None
        self._sr = audio_sr
        self._pos = 0
        self._playing = False
        self._lock = threading.Lock()

        if audio_data is None or audio_sr is None:
            return

        self._channel_data = audio_data[audio_channel].astype(np.float32)

        def callback(outdata, frames, time_info, status):
            with self._lock:
                if not self._playing:
                    outdata.fill(0)
                    return
                pos = self._pos
                end = pos + frames
                if pos >= len(self._channel_data):
                    outdata.fill(0)
                    return
                if end > len(self._channel_data):
                    valid = len(self._channel_data) - pos
                    outdata[:valid, 0] = self._channel_data[pos:pos + valid]
                    outdata[valid:, 0] = 0
                    self._pos = len(self._channel_data)
                else:
                    outdata[:, 0] = self._channel_data[pos:end]
                    self._pos = end

        try:
            self._stream = sd.OutputStream(
                samplerate=audio_sr,
                channels=1,
                dtype='float32',
                callback=callback,
                blocksize=1024
            )
            self._stream.start()
        except Exception as e:
            print(f"Audio playback error: {e}")
            self._stream = None

    def play(self, time_in_seconds):
        """Start playback from the given time position."""
        if self._stream is None:
            return
        with self._lock:
            self._pos = int(time_in_seconds * self._sr)
            self._playing = True

    def pause(self):
        """Pause playback."""
        if self._stream is None:
            return
        with self._lock:
            self._playing = False

    def seek(self, time_in_seconds):
        """Seek to a time position without changing play/pause state."""
        if self._stream is None:
            return
        with self._lock:
            self._pos = int(time_in_seconds * self._sr)

    def stop(self):
        """Stop and close the audio stream."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

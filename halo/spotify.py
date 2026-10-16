import asyncio
import logging
import queue
import time
from datetime import datetime, timezone
from PySide6.QtCore import QThread, Signal
from .models import Track, TimelineClock
from .artwork import valid_artwork

log = logging.getLogger(__name__)


async def read_thumbnail(thumbnail):
    from winrt.windows.storage.streams import Buffer, InputStreamOptions
    stream = await asyncio.wait_for(thumbnail.open_read_async(), timeout=3)
    try:
        if not 0 < stream.size <= 5_000_000:
            return b""
        buf = await asyncio.wait_for(
            stream.read_async(Buffer(stream.size), stream.size, InputStreamOptions.NONE), timeout=3)
        return bytes(memoryview(buf))
    finally:
        stream.close()


class SessionArtwork:
    """Retry late/failed Windows artwork without reusing a previous song's cover."""
    def __init__(self, reader=read_thumbnail):
        self.reader = reader
        self.key = None
        self.data = b""
        self.retry_at = 0.

    async def update(self, key, thumbnail, now):
        if key != self.key:
            self.key, self.data, self.retry_at = key, b"", 0.
        if thumbnail is None or now < self.retry_at:
            return self.data
        try:
            data = await self.reader(thumbnail)
            # Decode only the small cover, on the media thread. Empty/invalid
            # reads remain retryable rather than sticking for the whole song.
            if valid_artwork(data):
                self.data = data
                self.retry_at = now + 30.
                return self.data
        except Exception:
            log.debug("Artwork unavailable; will retry", exc_info=True)
        self.retry_at = now + 2.
        return self.data


class SpotifyWorker(QThread):
    changed = Signal(object)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.commands = queue.Queue()
        self.loop = None
        self.task = None

    def command(self, name, value=None):
        self.commands.put((name, value))

    def run(self):
        try:
            asyncio.run(self.poll())
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Windows media bridge failed")
            self.status.emit("Windows media controls are unavailable. Restart Halo to reconnect.")

    def stop(self):
        self.requestInterruption()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    async def poll(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )
        manager = await asyncio.wait_for(Manager.request_async(), timeout=8)
        current_key = None
        covers = SessionArtwork()
        clock = TimelineClock()
        while not self.isInterruptionRequested():
            try:
                # Never control another player's session if Spotify disappears.
                sessions = [s for s in manager.get_sessions()
                            if "spotify" in s.source_app_user_model_id.casefold()]
                session = sessions[0] if sessions else None
                while not self.commands.empty():
                    name, value = self.commands.get_nowait()
                    if not session:
                        continue
                    if name == "toggle":
                        await asyncio.wait_for(session.try_toggle_play_pause_async(), timeout=3)
                    elif name == "next":
                        await asyncio.wait_for(session.try_skip_next_async(), timeout=3)
                    elif name == "previous":
                        await asyncio.wait_for(session.try_skip_previous_async(), timeout=3)
                    elif name == "seek":
                        await asyncio.wait_for(session.try_change_playback_position_async(int(value * 10_000_000)), timeout=3)
                if not session:
                    current_key = None
                    covers = SessionArtwork()
                    clock = TimelineClock()
                    self.changed.emit(Track(observed_at=time.monotonic()))
                else:
                    props = await asyncio.wait_for(session.try_get_media_properties_async(), timeout=4)
                    timeline = session.get_timeline_properties()
                    info = session.get_playback_info()
                    playing = info.playback_status == Status.PLAYING
                    key = (props.title, props.artist, props.album_title)
                    if key != current_key:
                        current_key = key
                        clock = TimelineClock()
                    artwork = await covers.update(key, props.thumbnail, time.monotonic())
                    now = time.monotonic()
                    duration = max(0.0, (timeline.end_time - timeline.start_time).total_seconds())
                    raw_position = max(0.0, (timeline.position - timeline.start_time).total_seconds())
                    elapsed = (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds()
                    position = clock.update(raw_position, timeline.last_updated_time, playing, duration, now, elapsed)
                    self.changed.emit(Track(props.title or "Spotify", props.artist or "", props.album_title,
                                            duration, position, playing, True, artwork, now))
            except Exception:
                log.debug("Transient Spotify polling failure", exc_info=True)
                self.status.emit("Reconnecting to Spotify…")
            await asyncio.sleep(.5)

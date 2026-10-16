import unittest
from unittest.mock import AsyncMock
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from halo.spotify import SessionArtwork


def cover(colour):
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class SessionArtworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_thumbnail_arriving_after_metadata_is_read_for_the_same_song(self):
        data = cover("red")
        reader = AsyncMock(return_value=data)
        cache = SessionArtwork(reader)
        self.assertEqual(await cache.update("one", None, 1.), b"")
        self.assertEqual(await cache.update("one", object(), 1.5), data)
        reader.assert_awaited_once()

    async def test_transient_and_invalid_reads_retry_without_another_song_change(self):
        data = cover("blue")
        for failure in (OSError("stream busy"), b"invalid image", b""):
            with self.subTest(failure=failure):
                reader = AsyncMock(side_effect=[failure, data])
                cache = SessionArtwork(reader)
                self.assertEqual(await cache.update("one", object(), 1.), b"")
                self.assertEqual(await cache.update("one", object(), 2.), b"")
                self.assertEqual(reader.await_count, 1)
                self.assertEqual(await cache.update("one", object(), 3.), data)

    async def test_song_change_clears_old_cover_and_success_avoids_continuous_reads(self):
        data = cover("green")
        reader = AsyncMock(return_value=data)
        cache = SessionArtwork(reader)
        self.assertEqual(await cache.update("one", object(), 1.), data)
        self.assertEqual(await cache.update("one", object(), 2.), data)
        self.assertEqual(reader.await_count, 1)
        self.assertEqual(await cache.update("two", None, 3.), b"")

    async def test_temporary_same_song_failure_keeps_the_good_cover(self):
        data = cover("magenta")
        cache = SessionArtwork(AsyncMock(side_effect=[data, OSError("busy")]))
        self.assertEqual(await cache.update("one", object(), 1.), data)
        self.assertEqual(await cache.update("one", object(), 31.), data)

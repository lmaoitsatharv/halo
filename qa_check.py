"""Exercise Halo UI and worker lifecycle; save only original demo text."""
import os
from pathlib import Path
import time
from PySide6.QtCore import QSettings, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication
from halo.app import Controller, MainWindow, STYLE
from halo.models import Track, Lyrics, parse_lrc

app = QApplication([])
app.setStyleSheet(STYLE)
root = Path("qa")
root.mkdir(exist_ok=True)
settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
controller = Controller(settings, offline=True)
window = MainWindow(controller)
window.show()
controller.set_demo(True)
failures = []


def verify():
    try:
        assert window.title.text() == "In the light we made"
        assert window.play.isEnabled()
        assert len(controller.lyrics.lines) == 12
        window.open_position_settings()
        app.processEvents()
        dialog = window.position_dialog
        dialog.set_position(0, 0)
        assert QApplication.primaryScreen().availableGeometry().contains(window.overlay.geometry())
        dialog.set_position(100, 100)
        assert QApplication.primaryScreen().availableGeometry().contains(window.overlay.geometry())
        dialog.set_position(50, 50)
        area = QApplication.primaryScreen().availableGeometry()
        assert abs(window.overlay.geometry().center().x() - area.center().x()) <= 1
        assert abs(window.overlay.geometry().center().y() - area.center().y()) <= 1
        controller.settings.sync()
        saved = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
        assert saved.value("floating_x", type=int) == 50 and saved.value("floating_y", type=int) == 50
        controller.set("floating_screen", "missing-monitor")
        assert window.overlay.target_screen is QApplication.primaryScreen()
        dialog.reset()
        assert controller.floating_screen == "" and controller.floating_y == 90
        controller.set("floating", False)
        dialog.desktop_preview.setChecked(True)
        window.draw()
        assert window.overlay.isVisible() and window.overlay.previewing
        dialog.grab().save(str(root / "position-settings.png"))
        dialog.accept()
        window.draw()
        assert not window.overlay.isVisible() and not dialog.desktop_preview.isChecked()
        controller.transport("toggle")
        assert not controller.track.playing
        paused = controller.position
        controller.tick()
        assert abs(controller.position - paused) < .1
        controller.seek(26)
        controller.tick()
        assert controller.lyrics.index_at(controller.position) == 5
        controller.transport("toggle")
        controller.set("palette", "Violet hour")
        assert controller.primary.name() == "#d4b5ff"
        controller.set("floating", True)
        window.draw()
        assert not window.overlay.isVisible(), "Floating text should not cover the settings window"
        controller.seek(4.9)
        controller.tick()
        window.overlay.visual_index = 0
        window.overlay.last_generation = controller.generation
        window.showMinimized()
        app.processEvents()
        window.draw()
        assert window.isVisible() and window.isMinimized(), "Exercise Qt's visible-but-minimized state"
        assert window.overlay.isVisible(), "Floating lyrics must appear when the main window is minimized"
        wait = QEventLoop()
        QTimer.singleShot(350, wait.quit)
        wait.exec()
        assert controller.position > 5, "Playback must keep advancing while minimized"
        assert controller.lyrics.index_at(controller.position) == 1, "The lyric cue must advance while minimized"
        assert window.overlay.visual_index > 0, "The floating lyric view must keep painting while minimized"
        window.showNormal()
        app.processEvents()
        window.draw()
        assert not window.overlay.isVisible(), "Restoring Halo must hide floating text over the settings window"
        window.hide()
        window.draw()
        assert window.overlay.isVisible()
        window.show()
        window.fullscreen()
        app.processEvents()
        window.draw()
        assert window.immersive.isFullScreen()
        assert not window.overlay.isVisible()
        assert all(not edge.isVisible() for edge in window.edges)
        # Verify rendered edge pixels, not merely overlay visibility: fullscreen
        # paints its own glow while the desktop overlay windows stay hidden.
        controller.set("glow", True)
        controller.set("intensity", 100)
        controller.set("glow_width", 40)
        controller.pulse = .75
        glow_on = window.immersive.grab().toImage()
        controller.set("glow", False)
        glow_off = window.immersive.grab().toImage()
        dpr = glow_on.devicePixelRatio()
        points = [(glow_on.width() // 2, int(10 * dpr)),
                  (glow_on.width() // 2, glow_on.height() - int(10 * dpr)),
                  (int(10 * dpr), glow_on.height() // 2),
                  (glow_on.width() - int(10 * dpr), glow_on.height() // 2)]
        for x, y in points:
            on, off = glow_on.pixelColor(x, y), glow_off.pixelColor(x, y)
            assert sum(abs(a - b) for a, b in zip(on.getRgb()[:3], off.getRgb()[:3])) > 15, \
                "Immersive glow must be visible on all four edges"
        controller.set("glow", True)
        window.immersive.grab().save(str(root / "immersive.png"))
        original_title = controller.track.title
        original_lyrics = controller.lyrics
        controller.track.title = "A quiet collection of small moments beneath the evening sky"
        controller.lyrics = Lyrics(parse_lrc("[00:00]These are original words for a longer lyric line that should wrap comfortably in a smaller listening room\n[00:15]And another original line"))
        controller.generation += 1
        controller.seek(1)
        controller.tick()
        controller.trackChanged.emit()
        controller.lyricsChanged.emit()
        window.immersive.showNormal()
        window.immersive.resize(960, 640)
        app.processEvents()
        window.draw()
        window.immersive.grab().save(str(root / "immersive-small.png"))
        assert window.immersive.cover.geometry().bottom() < window.immersive.height()
        window.immersive.leave()
        assert window.isVisible() and not window.immersive.isVisible()
        controller.track.title = original_title
        controller.lyrics = original_lyrics
        controller.trackChanged.emit()
        controller.lyricsChanged.emit()
        window.immersive.hide()
        controller.set("palette", "Album colours")
        controller.set("floating", False)
        controller.seek(11)
        controller.tick()
        window.canvas.visual_index = 2
        window.grab().save(str(root / "main.png"))
        controller.set_demo(False)
        assert not controller.track.connected
        assert not window.play.isEnabled()
        controller.requestLyrics.disconnect(controller.lyrics_worker.fetch)
        controller.accept_track(Track("Original title", "Original artist", "Original album", 120,
                                      15, True, True, observed_at=time.monotonic()))
        stale = controller.generation - 1
        controller.accept_lyrics(stale, Lyrics(parse_lrc("[00:00]Stale lyrics")))
        assert not controller.lyrics.lines
        print("UI PASS: positions, preview, saved settings, monitor fallback, demo, pause, seeking, palette, minimized lyric playback, fullscreen, responsive layout, disconnect, stale lyrics")
    except Exception as error:
        import traceback
        traceback.print_exc()
        failures.append(error)
    finally:
        window.quit()


app.aboutToQuit.connect(controller.close)
QTimer.singleShot(400, verify)
app.exec()
if failures:
    raise SystemExit(1)
print("Lifecycle PASS: background workers stopped cleanly")

# Illustrated lyrics and immersive backgrounds

Ship displays smooth whole lines with smaller, quieter context and unframed vector symbols. Fisheye displays an illustrated word stack, and Visual displays one word and symbol at a time. The former visual variants are now named Ship and Fisheye; the plain variants have been retired. Existing saved choices carry over automatically. Illustrations use a small English keyword vocabulary and a star fallback. Pause and Reduce motion freeze decoration; seeking, track changes and blank singing breaks retain the lyric-clock behavior.

Open **Background…** in immersive view or **Immersive** in Halo's sidebar. Both show the background controls inside the main Halo window; when you opened them from immersive view, leaving the settings returns you to immersive view. Background and lyric style are independent. Choose ambient light, Spotify artwork, an online cover match, a local image, or a muted looping video. These choices affect Halo's immersive view only.

Five starting looks are available: Cinematic, Soft focus, Vivid, Monochrome and Dreamy. Adjustable treatment includes dimming, blur, colour richness, vignette and palette tint. Fill framing supports zoom, horizontal/vertical focus and slow drift or breathing. Full-image framing retains the whole image and disables crop/camera controls. Video can follow music playback or continue while its view is active. Reduce motion holds a poster frame. Leaving the view pauses decoding; closing the settings preview releases its decoder.

Local media is referenced at its existing location. Moving or removing it causes a safe ambient fallback and a settings status. Image imports are bounded to 64 MiB, 36 megapixels and 12,000 pixels per side; only supported raster formats are decoded. Local videos are bounded to 2 GiB. Accepted video frames are capped at 1920×1080 and 30 per second. Video colour-treatment work is limited further to 960×540 when saturation changes. Supported codecs depend on the installed media backend.

Online artwork uses the existing metadata-matched MusicBrainz / Cover Art Archive worker and its rate limits. It is enabled by choosing the online artwork source. It sends song metadata for matching, preserves Spotify's foreground cover, and uses Spotify artwork when no online match is available. No music audio or local wallpaper file is uploaded.

The implementation uses [Qt Media Player](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html) and [Video Sink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QVideoSink.html) for local video. No audio output is created and the selected audio track is disabled. Native tests use an original generated H.264/AAC clip to verify that a video containing audio still plays silently, loops and obeys pause, hidden state, reduced motion and cleanup.

## Initial background-feature verification on 24 October 2026 (historical; superseded)

> **Superseded.** This is a historical record of the original five-style background release. It does not describe the current interface: the lyric selector now has three styles (Ship, Fisheye and Visual), and since the 0.4.0 single-window redesign Settings is part of the main window rather than a separate window. The test count below (257) belongs to that 24 October build only. Later validation is recorded in the root `VALIDATION.md` of the source repository.

- All **257 native regression tests passed**, including 14 Ship Visual, 20 media, 12 background-settings and 6 controller integration tests.
- Existing UI lifecycle checks passed: positions, settings, preview, saved preferences, monitor fallback, pause, seeking, minimized lyrics, fullscreen return, responsive layout, stale results and clean worker shutdown.
- Compact settings were inspected at 960×600; the new controls remain reachable by scrolling, and the five lyric modes remain accessible.
- Native original-text/image captures were inspected for immersive Ship Visual and the background settings. Existing plain Ship is covered by unchanged rendering assertions.
- The new floating Ship Visual uses a bounded raster cache to reduce repeated outline work. Video colour processing is bounded to keep the UI responsive. Local render-cost measurements exclude screen refresh and are not frame-rate guarantees.
- No Spotify playback changes or audio capture were needed for this feature's regression tests. Generated test media and all QA settings stay separate from the user's saved preferences.

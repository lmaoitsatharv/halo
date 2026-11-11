# Halo

A Windows companion for the music you play, inspired by ambient music lighting and desktop lyrics. It follows **Spotify**, a browser tab (Spotify or Apple Music on the web, YouTube, YouTube Music) or a music app. Independent software; not affiliated with Spotify, Apple, Google, Lumn or Verci.

> **Version:** this guide describes **Halo 0.6.0**, the **Gallery wall** redesign. Halo 0.4.0 and 0.5.0 used a dark glass window with a sidebar; their pages and settings are the same, but they sit on the wall now.

## Download for Windows

### [Download Halo for Windows (.zip)](https://github.com/lmaoitsatharv/halo/releases/latest/download/Halo-Windows-x64.zip)

Windows 10 (1809+) or Windows 11 · 64-bit · Portable · No Python or GitHub account needed

1. Click **Download Halo for Windows** above and save **Halo-Windows-x64.zip**.
2. Right-click the downloaded ZIP → **Extract All…** → **Extract**.
3. Open the extracted **Halo** folder and double-click **Halo.exe** (Windows may show it as **Halo**, type **Application**).
4. Play a song: in the **Spotify** app, in a browser, or in a music app. Choose **Settings** at the top right to customize Halo.

Keep **Halo.exe**, **_internal** and **licenses** together in the extracted folder. Run the app from that folder, after extraction. No installation is needed. To quit completely, right-click the Halo icon in the system tray → **Quit Halo**.

**Updating?** Quit Halo from its tray icon, extract the new ZIP into a fresh folder, then open the new **Halo.exe**. Your saved preferences are kept separately in Windows.

[Website](https://halo-music-companion.vercel.app) · [All releases and checksums](https://github.com/lmaoitsatharv/halo/releases) · [Troubleshooting](#troubleshooting)

![Halo's Listening page on the light wall, playing its original visual demo](docs/images/halo-desktop.png)

## What's new in 0.6.0

- **The Gallery wall.** The window is a wall: the cover hangs as a framed print under a spotlight tinted by the song, a museum label carries the title, artist and album, and the lyric is lettered on the wall with the word being sung in the song's colour. The spotlight breathes only while music plays. Navigation is one row of places (**Listening**, **Modes**, **Lighting**, **Lyrics**, **Immersive**, with **Ctrl+1–5**) and a **Settings** button. Playback sits on a dark handset on every page.
- **Dark mode.** **Settings → General → Appearance** offers **Match Windows** (the default), **Light** and **Dark**: the same wall after hours.
- **The wall runs to the window's top edge**, with only Windows' minimise, maximise and close keys on it.
- **Any player.** Halo follows whatever plays through Windows' media controls: Spotify, a browser tab or a music app. If two play at once, it stays on the one it shows; when that one pauses and another plays, it switches. Video titles from browser tabs are cleaned before the lyrics search, so "Artist - Song (Official Video)" looks up the song.
- **Mini player** (**Ctrl+Shift+M**): a small always-on-top case with the print, the song, the line being sung and a fine progress line. Only the play key shows at rest; hover or Tab in for previous and next, the times, and the keys back to Halo and to the tray. Click the print to bring Halo back.
- **Lyric share cards** (**Ctrl+Shift+S**): a 1080×1350 picture of the line being sung, the print and the label, on a light or dark wall. **Copy** or **Save PNG…**. Made on your PC; nothing is uploaded.
- **Immersive menu.** One key at the top left of Immersive holds **Room ›**, **Lyric style ›**, **Lighting ›**, a **Background** switch, Background settings, Modes and **Return to Halo**. The room's player bar is the same handset as the main window, with Mini player and Return. **F11** goes in and back out.
- **Better word timing.** Without word timestamps, words are now placed at the song's own pace, so a line ends when the singing would rather than being stretched to the next line. On 39 hand-timed songs this cut the typical error from 272 ms to 189 ms. With **Learn word timing from playback** on, a new model that has heard real singing places words on replays: typical error 71 ms (was 128 ms), and two thirds of lines are learned on the first listen. See [Lyrics](#motion-and-lyric-styles).
- **Starline** now draws only the line: it travels to the next star and lands exactly as that word is sung, and the star sparks there. Its speed follows the song.

Already in 0.5.0 and 0.4.0: Momentum, vivid album colours, the Neon and Liquid halo lights, the GPU lens for Fisheye, Lucide symbols, Strata and the glow lyric styles (Cascade, Starline, Neon, Impact), and optional word timing from playback.

Earlier highlights: the Modes library with live previews, smoother audio pulses, missing-cover recovery, saved lyric corrections per song, Ship's whole-line lyrics, and custom immersive backgrounds.

![Halo Settings on the wall, with General selected and a live monitor preview](docs/images/halo-settings.png)

## Use the app

1. Open **Halo.exe** from the extracted **Halo** folder. If you built from source, it is in `dist/Halo/Halo.exe` (or `<dir>/Halo/Halo.exe` when built with `--dist-dir <dir>`).
2. Play a song. Halo detects it automatically through Windows' media controls; no login, API key or Premium account is required by Halo. **Settings → General → Music source** shows which player Halo is following.
3. The row at the top holds **Listening**, **Modes**, **Lighting**, **Lyrics** and **Immersive** (**Ctrl+1** to **Ctrl+5**). **Settings** (**Ctrl+,**) opens on **General**; **‹ Back to listening** or **Esc** leaves it. **Lighting**, **Lyrics** and **Immersive** each show a live monitor preview on the right. Changes save automatically, and the handset stays available on every page. **Lighting** contains the screen-edge and audio switches, style picker, light sliders and colour controls. **Album colours** lights the halo with the two most vivid colours in the cover, raising dark ones while keeping their hue, and fades between tracks; lyrics and accents use readable tints of the same colours. **General** has **Appearance**, **Reduce motion** and the optional **Find missing covers online** switch, which is off by default.
4. The handset holds previous, play, next and the timeline, then **Share** (**Ctrl+Shift+S**), **Mini player** (**Ctrl+Shift+M**) and **Immersive** (**F11**). **Space** plays and pauses; **Ctrl+Left** and **Ctrl+Right** skip.
5. In **Lyrics**, turn on **Floating lyrics**, then minimize Halo or close its window to the tray. Lyrics keep advancing above your desktop with clicks passing through them. Restoring the window, or opening the mini player, hides the floating text.
   Use **Adjust…** in the Position row to choose a monitor, drag the preview, adjust horizontal/vertical position, or use the nine presets. **Preview on desktop** shows the actual placement while the settings are open. **Reset position** restores bottom-center placement on the primary display.
6. **Immersive** (**F11**) opens the selected room inside the same window: Listening room, Lyrics only, Cinema or Orbit. The menu key at its top left changes the room, lyric style and lighting, switches your background on or off, and returns to Halo. The header and player fade, and the cursor hides, after 1.5 seconds without cursor movement; move the mouse to reveal them. Press **Space** to play/pause and **Esc** or **F11** to return.
7. Right-click Halo's icon in the system tray to open Halo, Settings, Modes, the mini player or immersive view, toggle the screen-edge glow, or **Quit Halo** completely.

**Try the visual demo** on the Listening page previews lighting and original timed text without a player. **Back to your music** ends the demo. The demo does not play audio.

The main window opens centered in your monitor's usable area, and maximizing is remembered. Settings previews use the same glow and lyric renderers as the app, except that Fisheye in Settings and the Modes library is drawn with the standard painter. When synced lyrics are missing, clearly labelled original sample words appear without starting demo mode or changing playback. Page changes, hover effects and switches animate gently; **Reduce motion** settles them immediately.

## Motion and lyric styles

- **Aura:** calm, balanced album-colour light.
- **Orbit:** a rotating two-colour rim with a travelling comet highlight.
- **Wave:** moving colour ribbons around the screen.
- **Pulse:** breathing light in Flow; in Music sync, bass and percussion accents drive a strong inward bloom and brightness changes.
- **Prism:** a revolving spectrum based on the album palette.
- **Neon:** a glass tube floating just inside the screen edge, with a white-hot filament. Top and bottom glow in one colour, the sides in the other. The four tubes behave like tubelights that sometimes fail to start: a random group goes dark, flashes a few times and catches. With synced lyrics these starts land on lyric lines, and with **React to audio** the struggling tubes flash with the music's loud accents.
- **Liquid:** glossy drops of light cling to the screen edges. They drift, bulge, pinch off into droplets and fall back in, mixing your two colours where they merge.

The lyric-style selector controls the main preview, floating lyrics and all immersive scenes:

- **Ship:** smooth whole-line scrolling, smaller surrounding lines and fine, unframed illustrations. No word highlighting or spotlight box.
- **Fisheye:** a kinetic word stack with quieter surrounding words and tilted colour strips, bent by a GPU lens when one is available, with [Lucide](https://lucide.dev) line symbols.
- **Visual:** one large word and symbol at a time, with soft transitions.

Open **Modes** (or **Browse modes** in Immersive's menu, or **Modes** in the tray menu) to browse live previews of more lyric styles, immersive rooms and halo lights. **Add to my modes** saves a look to its usual selector; **Use mode** adds and applies it. Search, category filters, **My modes** and **Hide included** help keep your collection organised.

Fourteen additional designs are available in the bundled gallery:

| Lyrics | Immersive rooms | Halo light |
| --- | --- | --- |
| **Monument** — an editorial verse poster | **Gallery** — framed artwork with a travelling key-light | **Aurora** — flowing light curtains |
| **Marquee** — a horizontal word ribbon | **Runway** — a perspective light corridor | **Echo** — opposing waves and expanding ripples |
| **Afterimage** — layered typographic echoes | **Refraction** — glass facets and spectral ribbons | **Meteor** — three separated comets and their trails |
| **Strata** — a tilted wall of words that sways in 3D and swings to each new line | | |
| **Cascade** — words climb a rising stack, the newest large and lit on a bold block | | |
| **Starline** — a bright line travels to each word and lands as it is sung, where the star sparks; each verse clears for the next | | |
| **Neon** — a line of glass tubes that strike on word by word | | |
| **Impact** — one huge word at a time, thrown at the screen with a shockwave | | |

Previews follow the current song's lyrics, playback position, saved correction and artwork. Clearly labelled sample words appear when timed lyrics are unavailable. Preview motion can be paused and honours Reduce motion. See the [Modes guide](docs/modes.md).

**Word timing.** Ship follows the source's line timestamps. The word-based styles use supplied word timestamps from LRCLIB Lyricsfile data or Enhanced LRC imports when available. Otherwise they estimate when each word is sung: each line is sung at the song's own pace, taken from its fullest lines, with words weighted by their syllables and the last word held. The lyrics badge distinguishes **Word synced**, **Mixed timing**, and **Line synced · words estimated**. Supplied timestamps can still be inaccurate.

**Learn word timing from playback**, off by default, listens to your PC's sound while a song plays. On a first listen the words keep the estimate while Halo listens (the badge reads **Line synced · learning word timing**). When the song ends, the lines it heard clearly are saved, and replays use them (**Word timing learned on this PC**); lines it was unsure of stay estimated until another listen. Learned timing is an estimate, not verified sync.

Measured on 39 hand-timed songs in English, French, German and Spanish that were never used for training or tuning, with line starts made a little inexact as real lyrics are:

| | Typical error | Words within 0.1 s |
| --- | --- | --- |
| Estimate (learning off, or a first listen), 0.5.0 | 272 ms | 23% |
| Estimate, 0.6.0 | 189 ms | 30% |
| Replay with learned timing, 0.5.0 | 128 ms | 45% |
| Replay with learned timing, 0.6.0 | 71 ms | 58% |

Click a visible lyric to seek to that line. **Reduce motion** keeps steady typography and a calm halo, and pausing freezes the animated flow.

In **Lyrics** → **Timing & lyrics**, **Earlier** advances lyrics by 0.1 seconds and **Later** delays them. The slider supports a correction of up to 10 seconds either way. **Reset** clears this recording's correction. Corrections are remembered across song changes and restarts. A fixed correction cannot repair uneven timestamps.

For different or incorrect words, use **Wrong lyrics? Choose a match…** to compare matched releases, their album, duration and a short preview. Your chosen source is remembered. You can also **Import timed lyrics…** from UTF-8 `.lrc`, Enhanced LRC (`.lrc` or `.elrc`), or Lyricsfile 1.0 (`.lyricsfile.yaml`, `.yaml`, `.yml`). Saved choices and imports take priority over automatic lookup. **Use automatic lyrics again** clears the saved source while keeping its timing correction.

## Immersive backgrounds

Open **Immersive** at the top, or **Background settings…** in Immersive's menu. Select the original **Ambient** scene, current-song **Album artwork**, a local **Image**, or a local **Video**. The menu's **Background** switch turns your background off (Halo's own light) and back on, remembering the last one. These choices apply inside Halo's immersive view; they do not change the Windows desktop wallpaper.

The right-hand preview uses the actual media and rendering controls. Start with **Cinematic**, **Soft focus**, **Vivid**, **Monochrome** or **Dreamy**, then adjust blur, dimming, saturation, vignette and album-colour tint. Framing controls include fill/fit, zoom and horizontal/vertical focus. Still, drift and breathe motion have an adjustable speed.

Videos loop silently. Playback can follow music or continue while the immersive view is open. Hidden views stop decoding, and Reduce motion freezes moving backgrounds. Supported video formats depend on the available decoder; an unreadable or missing file falls back to the ambient scene and shows a useful status in settings. Media files stay in their original location, so keep them available after selecting them.

Album backgrounds use your player's artwork by default (**Player cover**). Selecting **Online** searches MusicBrainz and Cover Art Archive for the current recording, while keeping the player's foreground cover. The player's artwork is used while a matching online image is unavailable.

The halo preserves dark, saturated and neutral colours. Black creates an unlit section instead of a grey or opaque black border. Rim thickness is independent of the soft glow's spread and opacity. Changing either colour switches to **Custom**; preset changes preserve your saved custom colours and brightness values.

**Flow** moves at a steady speed, **Music sync** swells on output-audio accents, **Momentum** lets each beat push the colours around the screen before they coast, **Idle** moves slowly and **Still** keeps the light stationary. The audio toggle stays in sync with Music sync and Momentum. Music sync adapts to the playback volume and detects sudden bass and percussion changes; it does not estimate tempo or predict a precise beat grid.

Lighting research used [Lumn's official overview](https://www.trylumn.xyz/). Lyric styling was guided by the Verci demo video supplied with this project. Halo uses its own native renderer, motion and layouts. Its line symbols are [Lucide](https://lucide.dev) icons, matched to words by Halo's own word list.

## What this version does

- Reads title, artist, album artwork, playing/paused status, duration and timing from Windows' media session for the player it follows: Spotify, a browser tab or a music app.
- Provides previous, next, play/pause and timeline seeking controls for that player.
- Shows animated line-synced lyrics and uses supplied word timestamps where available, with an estimated fallback at the song's pace.
- Searches other releases and common title spellings. Every lookup route checks title, artist, duration and explicit performance/version labels; matching albums and closer durations rank first. For a browser tab only, if nothing matches, it searches again without trusting the reported length, still requiring the same title, artist and version. This conservative matching can leave some songs without lyrics.
- Saves a timing correction from −10000 to +10000 ms for each recording.
- Remembers imported timed lyrics and deliberately selected sources by title, artist, album and rounded duration.
- Optional **React to audio** analyses local output levels and bass/percussion changes via WASAPI loopback. Otherwise, the glow moves gently.
- Saves preferences and minimizes to the tray when its main window is closed.

## Privacy and limitations

Song details and artwork are read locally through [Windows media controls](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager). Lyrics requests send the current song title, artist, album and duration to [LRCLIB](https://lrclib.net/docs); no account or credentials are requested. Automatic results are cached in memory. Explicitly chosen or imported lyrics and song corrections are saved locally in `saved-lyrics/` beside Halo's settings. Saved records are bounded to 2 MiB each and 512 recordings. Share cards are made on your PC and saved or copied only where you choose.

**Players.** Halo follows players that report to Windows' media controls, the ones shown in Windows' media flyout. Players that don't report cannot be named, though the halo still reacts to their sound. Halo was tried with the Spotify app and with Apple Music in Brave; other browsers and apps are expected to work the same way but were not tried. A muted video playing in another tab can take over a second and a half after your player pauses. An upload titled "Song - Artist" (the reverse of the usual order) is read backwards and finds no lyrics.

Players sometimes omit their cover from Windows' media feed. Halo retries late or failed artwork and refreshes the cover and album colours when it arrives. If you enable **Find missing covers online**, Halo sends song-title/artist search terms to [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API) and requests the matching release's front cover from [Cover Art Archive](https://musicbrainz.org/doc/Cover_Art_Archive/API). The player's artwork takes priority. No login details or audio are sent for cover lookup.

Audio-reactive mode measures **all sound on the current default output device**, including other apps. It does not use the microphone, save recordings or send audio anywhere. If the output device changes, it reconnects. Silence and incompatible devices fall back to gentle motion.

**Learn word timing from playback** is optional and off by default, in **Lyrics → Timing & lyrics**. While it is on and a song is playing, a small model running on this PC analyses **all sound on the current default output device**, including other apps, to place each lyric word. Audio stays in memory for about 30 seconds at most and is never saved or sent anywhere; only word times are stored, in a `learned-timing` folder beside your settings, for up to 512 songs. **Forget learned timing** and **Forget all** remove them. It cannot follow lyrics in scripts other than Latin, or imported lyrics; those keep the estimate. Spotify's User Guidelines restrict recording content and feeding it into machine learning models, so turn this on only if you accept that.

Lyrics coverage and accuracy depend on LRCLIB or your import. When words are wrong, choose a different matched source or import corrected timed lyrics. A constant offset helps consistently early/late lyrics; it cannot repair uneven drift. If the service is unavailable, use **Retry** after a moment. Ads, podcasts, videos and untimed tracks may have no synced lyrics. Unless **Learn word timing from playback** is on, Halo does not analyse the vocals.

Malformed or unusually large lyric inputs are rejected before display. Imports are limited to 512 KiB, 2,000 cues, 32 timestamps per source line, 2,000 characters and 256 words per cue, and 20,000 expanded words and 250,000 expanded characters across the track. HTTP lyric responses are limited to 4 MiB. A rejected import keeps the current lyrics.

This app uses an ordinary fullscreen view. It does not draw over the secure Windows lock screen. Overlays can also be hidden by games running in exclusive fullscreen.

Fisheye's lens, and the Neon and Liquid halo lights, run on the GPU through an offscreen OpenGL 3.3 context. If it cannot start or a pass fails, Halo falls back to standard drawing. `HALO_DISABLE_LENS=1` and `HALO_DISABLE_FIELD_GPU=1` force the fallbacks. These have been tested on one PC only. On laptops with two GPUs, Windows may run them on the discrete GPU; choose **Power saving** for `Halo.exe` in Windows graphics settings to avoid that.

The portable build is unsigned. Source is included here so the app can be reviewed and rebuilt. Target: Windows 10 version 1809 or later, Windows 11, x64. Only the current development PC has been tested so far.

## Troubleshooting

- **Downloaded “Source code (zip)” or used Code → Download ZIP?** That is the developer source. Use the **Download Halo for Windows** link at the top of this page to get the ready-to-run app.
- **Missing files or the app does not start?** Extract the entire ZIP first. Keep the `_internal` folder beside **Halo.exe**; copying only the executable will not work.
- **Windows shows a publisher or SmartScreen warning?** This build is unsigned. Check that your download came from this repository's Releases page. A SHA-256 checksum is included with each release.
- **No song appears?** Start playback, and check that the song shows in Windows' media flyout (the panel that appears when you press a volume key). Halo can only follow players that appear there.
- **Halo shows the wrong player?** It stays on the player it is showing while that one plays. Pause it, and Halo switches to the one still playing.
- **No lyrics?** Some tracks have no timed lyrics. Try **Retry** or import a local `.lrc` file in **Lyrics**.
- **Closed the window but Halo is still running?** It stays in the system tray. Right-click its icon → **Quit Halo** to stop it completely.

## Run from source

Python 3.12 is used for this build. From this folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

All app code is in `halo/`.

Source runs keep settings/logs in `.data/` beside the source. Packaged builds use `%LOCALAPPDATA%\Halo`. `HALO_DATA_DIR` overrides that location. Logs rotate and record status and errors; Halo does not intentionally record audio samples or lyric text. Learned word timing files hold word times, a hashed recording key and the lyric source id. The source id and file dates amount to a listening history, so treat that folder as private. Developer diagnostics and explicitly requested screenshots/reports can preserve listening metadata or visible lyrics, so review those files before sharing them.

## Build and verify

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe qa_check.py
.venv\Scripts\python.exe diagnostics.py
.venv\Scripts\python.exe build.py
```

`diagnostics.py` only reads the media session; it does not change playback. `qa_check.py` checks UI state, overlays and worker shutdown using original demo text. The test suite covers timestamp parsing, matching, player choice, pause/resume/seek, audio levels, motion controls, rendered halo modes and lyric typography.

Install `requirements-dev.txt` for the packaging tool (PyInstaller). `build.py` runs PyInstaller with command-line options; it does not use a `.spec` file. It uses a clean native-library search path and includes an icon, dependency notices, this guide, the `docs` folder and a portable ZIP. Run the build in a normal Windows development environment; restricted application containers cannot access the desktop media session.

By default, `build.py` writes the app folder to `dist\Halo` and the archive to `dist\Halo-Windows-x64.zip`. With `--dist-dir <dir>`, it writes `<dir>\Halo` and `<dir>\Halo-Windows-x64.zip` instead. The package contains `source-manifest.json`, which records the exact module hashes, and `VERSION.txt`, which records the version from `halo/__init__.py`.

If Halo may be running from an existing build, do not overwrite that folder. Package with `--dist-dir` pointing to a fresh, empty staging folder, check the new executable, quit the running Halo from its tray icon, then replace the existing app folder.

The packaged app must be distributed as **the whole `Halo` folder** (or the ZIP that contains it), including `_internal` and `licenses`. Keep the bundled dependency licenses and notices with it.

## Dependencies and data

Qt for Python / PySide6 (LGPLv3), PyWinRT (MIT), NumPy (BSD), SoundCard (BSD), PyYAML (MIT; reads imported Lyricsfile documents), Lucide (ISC, with MIT for its Feather-derived icons; Halo's line symbols). PyInstaller is the build tool. Their bundled licenses and notices are retained in the portable distribution. This project includes no Spotify assets, credentials or copyrighted lyric fixtures.

**The word-timing model** (`halo/word_model_weights.py`, used only when **Learn word timing from playback** is on) was trained by this project on LibriSpeech (CC BY 4.0), Slakh (CC BY 4.0) and the Groove MIDI Dataset (CC BY 4.0), then fine-tuned on sung sections from [MUSDB18](https://sigsep.github.io/datasets/musdb.html) with the [MUSDB18 lyrics extension](https://zenodo.org/record/3989267) by Kilian Schulze-Forster, Clément Doire, Gaël Richard and Roland Badeau. MUSDB18 is provided for educational, non-commercial use, and the lyrics extension is licensed under CC BY-NC-SA 4.0. The weights hold no audio or lyrics. Halo is free and non-commercial; see `licenses/word-model/NOTICE.md` in the download.

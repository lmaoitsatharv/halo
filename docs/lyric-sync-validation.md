# Lyric synchronization update — 17 October 2026

The three implementation tasks were assigned separately, followed by two independent testing agents. All **205 native regression tests passed**, and the existing native UI lifecycle check passed: settings, floating/minimized lyrics, seeking, pause, immersive entry/exit, responsive layout, stale results and worker shutdown.

## What changed

- Every automatic lookup path checks recording metadata, including the exact-record fallback. Explicit live/acoustic/remix/edit/cover labels participate in matching. Album and duration rank candidates; supplied word timing breaks equally strong ties. A bounded source picker supports a deliberate saved selection.
- Earlier/Later adjusts this recording in 100 ms steps, up to ±10 seconds. Its correction, imported timed lyrics and selected sources persist across song changes and restart. Existing global calibration is retained. Errors and obsolete responses preserve the previous usable result.
- Lyricsfile 1.0 and Enhanced LRC imports retain supplied word boundaries. Ordinary line-timed LRC still uses estimated word animation, with a clear status label. Ship keeps its whole-line presentation.

## Independent findings and repairs

The timing reviewer found stretched sub-40 ms syllables, an overly long Visual crossfade, Fisheye trailing on fast words, candidate retention that could discard better later matches, and missing custom-edit version checks. These were fixed and covered by regressions.

The persistence reviewer found stale selection state after Retry, invisible failed-reset errors, an abandoned initial automatic lookup after opening the picker, and a store/parser disagreement about overlapping source intervals. These were fixed and covered by regressions. New controls were checked at 960×600 and 1260×790 logical pixels; all were reachable by scrolling and their labels fit.

## Timing measurements

The independent synthetic test used original source-timed syllables at 10, 12.5, 25 and 50 segments per second. **2,156 boundary assertions passed**, with no systematic shift applied to supplied starts. Selection took about 0.003 ms at the median, below 0.006 ms at the 95th percentile in that run. Native offscreen rendering at 720×420 took about 1–3.1 ms at the 95th percentile across the four styles. These measurements exclude screen refresh, the compositor and audio-device latency.

At 12.5 words per second, the previous fixed Visual fade let a new word reach only 22.58% opacity before replacement. The revised source-timed fade reached 100% before replacement in the same test. Fisheye mean spatial trailing decreased from 1.555 to 0.227 word positions at 60 updates per second. These are animation measurements, not measured milliseconds of vocal alignment.

## Live Spotify check

The real Windows bridge connected to **POWER — Kanye West**. Pause/resume and seeking worked. While paused, the measured position drift was 0 seconds; the paused seek matched the position reported by Windows within 0.001 seconds. Playback state and the original paused position were restored and verified.

This establishes control/clock consistency against Windows metadata. It does **not** establish that lyrics match the singer within 1 ms, nor measure the delay between a control request and audible playback. No audio was recorded or processed by a model.

Four public catalogue smoke tests returned usable line timings in roughly 0.8–1.2 seconds each in the final run. The selected results for POWER, Blinding Lights, Rap God and Runaway supplied **no genuine word timestamps**. This small sample is not a catalogue coverage estimate. Alternate custom-edit metadata was rejected in the final Rap God lookup.

## Honest assessment

Use zero song correction until an audible comparison establishes a consistent mismatch. No reviewer invented a recommended offset for a real song. A stored fixed correction cannot repair uneven drift, missing words or a different performance. Those cases need a better matched source or corrected import. The update improves selection, persistence and display correctness; it does not manufacture accurate word timestamps for every song.

Recording identity uses the title, artist, album and rounded duration supplied by Windows. Identical metadata cannot prove identical audio. Lyricsfile is a draft; its unresolved `metadata.offset_ms` is ignored. Overlapping source intervals are retained, but the current view focuses one line/word rather than rendering simultaneous singers separately. Source gaps hold the previous completed word until the next begins.

Local QA evidence and the two detailed reviewer reports are in `qa/lyrics-upgrade/` in the development workspace. Those files are excluded from publication.

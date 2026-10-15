"""Read-only local Windows media check. Does not change playback."""
import asyncio
import json
from datetime import datetime, timezone
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
from winrt.windows.storage.streams import Buffer, InputStreamOptions


async def main():
    manager = await asyncio.wait_for(Manager.request_async(), timeout=8)
    results = []
    for session in manager.get_sessions():
        if "spotify" not in session.source_app_user_model_id.casefold():
            continue
        props = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        result = {"source": session.source_app_user_model_id, "title": props.title,
                  "artist": props.artist, "album": props.album_title,
                  "playing": str(session.get_playback_info().playback_status),
                  "position": timeline.position.total_seconds(),
                  "duration": timeline.end_time.total_seconds(),
                  "timestamp_age": (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds(),
                  "artwork_bytes": 0}
        if props.thumbnail:
            stream = await props.thumbnail.open_read_async()
            try:
                buf = await stream.read_async(Buffer(stream.size), stream.size, InputStreamOptions.NONE)
                result["artwork_bytes"] = len(bytes(memoryview(buf)))
            finally:
                stream.close()
        results.append(result)
    print(json.dumps({"spotify_sessions": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

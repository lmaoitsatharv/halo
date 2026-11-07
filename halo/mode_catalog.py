"""Built-in mode definitions and a small local collection of chosen extras."""
from dataclasses import dataclass
from functools import lru_cache
import json


MODE_FIELDS = {"lyrics": "lyric_style", "scenes": "immersive_mode", "halo": "halo_mode"}
MODE_TITLES = {"lyrics": "Lyrics", "scenes": "Immersive", "halo": "Halo light"}
BASE_MODE_KEYS = {
    "lyrics": ("ship_visual", "fisheye_visual", "visual"),
    "scenes": ("studio", "lyrics", "cinema", "orbit"),
    "halo": ("aura", "orbit", "wave", "pulse", "prism", "neon", "liquid"),
}


@dataclass(frozen=True)
class ModeSpec:
    kind: str
    key: str
    title: str
    description: str
    included: bool

    @property
    def field(self):
        return MODE_FIELDS[self.kind]

    @property
    def identity(self):
        return self.kind + ":" + self.key


@lru_cache(maxsize=1)
def all_modes():
    # Lazy imports keep the catalogue independent of the application window.
    from .glow import HALO_MODES
    from .lyric_rendering import LYRIC_STYLES
    from .immersive import IMMERSIVE_SCENES
    definitions = {"lyrics": LYRIC_STYLES, "scenes": IMMERSIVE_SCENES, "halo": HALO_MODES}
    return tuple(ModeSpec(kind, key, title, description, key in BASE_MODE_KEYS[kind])
                 for kind, specs in definitions.items() for key, title, description in specs)


def find_mode(kind, key):
    return next((spec for spec in all_modes() if spec.kind == kind and spec.key == key), None)


def read_collection(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if len(raw) <= 65536 else {}
        except (ValueError, TypeError, RecursionError):
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    valid = {kind: {spec.key for spec in all_modes() if spec.kind == kind and not spec.included}
             for kind in MODE_FIELDS}
    return {kind: sorted({key for key in raw.get(kind, []) if isinstance(key, str) and key in valid[kind]})
            if isinstance(raw.get(kind), list) else [] for kind in MODE_FIELDS}


def available_specs(controller, field, specs):
    kind = next((kind for kind, name in MODE_FIELDS.items() if name == field), None)
    if kind is None:
        return tuple(specs)
    if hasattr(controller, "mode_specs"):
        return controller.mode_specs(field)
    return tuple(spec for spec in specs if spec[0] in BASE_MODE_KEYS[kind])

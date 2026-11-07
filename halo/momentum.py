"""Momentum: each beat pushes the halo's colours along the rim, then they coast.

The beat is carried mainly by motion; each push also lifts the light the
last few percent to the full glow intensity, so a beat shows in the light too.
The numbers come from measuring a reference rim light's public demo: about
0.07 laps a second between beats, surges near 0.85, an average near 0.43 laps
a second on a steady beat, and brightness within a few percent.
"""
import math

from .palette import envelope

REST = .07        # laps a second between beats, at the default motion speed
PUSH = 1.3        # extra laps a second at the crest of a full push
COAST = .06       # seconds for a push to fade once the hit has passed
GAP = .28         # shortest time between two pushes
THRESHOLD = .45   # a hit must rise past this to count as a beat
HIT_DECAY = .08   # matches AudioDynamics' accent decay
ATTACK = .03      # seconds for a push to build
LIFT = .08        # the push lifts the light from 92% to the full glow intensity
SWELL = .10       # how much of the rim the brighter colour gains at a crest


class Momentum:
    """Turns the detector's accents into a push that decays.

    Halo's detector also fires on hi-hats and bass notes, nearly always at
    full strength. Only a hit rising past the threshold at least GAP after
    the last push counts, so fast transients cannot stack into a spin.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.surge = 0.
        self.gate = 0.
        self.previous = 0.
        self.since_push = math.inf

    def step(self, elapsed, accent):
        elapsed = max(0., float(elapsed))
        accent = max(0., min(1., float(accent)))
        self.since_push += elapsed
        self.gate *= math.exp(-elapsed / HIT_DECAY)
        if accent > THRESHOLD >= self.previous and self.since_push >= GAP:
            self.gate = max(self.gate, accent)
            self.since_push = 0.
        self.previous = accent
        self.surge = envelope(self.surge, self.gate, elapsed, attack=ATTACK, release=COAST)
        return self.surge

    def rate(self, motion_speed):
        return momentum_rate(motion_speed, self.surge)


def momentum_rate(motion_speed, surge):
    """Laps a second; motion speed 45 is Halo's default."""
    return motion_speed / 45 * (REST + PUSH * surge)


def momentum_strength(surge):
    """Brightness multiplier: 0.92 between beats, 1.0 at the crest of a push."""
    return 1. - LIFT + LIFT * max(0., min(1., surge))


def light_surge(c):
    """The push a renderer should show; reduced motion and other animations show none."""
    if getattr(c, "halo_animation", "flow") != "momentum" or getattr(c, "reduced_motion", False):
        return 0.
    return max(0., min(1., float(getattr(c, "surge", 0.))))


def light_share(c, primary_energy, secondary_energy):
    """The primary colour's share of the rim, widened toward the brighter colour on a push."""
    proportion = max(0., min(1., getattr(c, "color_mix", 60) / 100))
    grow = SWELL * light_surge(c)
    if grow <= 0. or proportion in (0., 1.):
        return proportion
    # With equal colours the secondary widens, as in the reference demo.
    proportion += grow if primary_energy > secondary_energy else -grow
    return max(.02, min(.98, proportion))

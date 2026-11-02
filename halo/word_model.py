"""A small streaming model that scores lyric letters from output audio, in numpy alone.

The same 25 ms window and 10 ms hop fit any sample rate, and one step comes out every 20 ms,
with 40 ms of lookahead. Weights load on first use, so the app pays nothing while this is off.
"""
import base64
from functools import lru_cache
import math
import unicodedata
import zlib

import numpy as np

MEL_BINS = 64
HOP_SECONDS = .01
WINDOW_SECONDS = .025
LOW_HZ, HIGH_HZ = 60., 7600.
FLOOR = 1e-10
FEATURE_MEAN, FEATURE_STD = -12., 4.
ALPHABET = "_|'abcdefghijklmnopqrstuvwxyz"
BLANK, BOUNDARY = 0, 1
TOKEN = {letter: index for index, letter in enumerate(ALPHABET)}
STRIDE = 2
LOOKAHEAD_SECONDS = 4 * HOP_SECONDS
LAYERS = 2
GELU_LIMIT = 6.


def spell(text):
    """Lyric text as words of alphabet letters; anything else is dropped, as in training."""
    plain = unicodedata.normalize("NFKD", text.replace("’", "'")).lower()
    words = ("".join(letter for letter in word if letter in TOKEN and letter not in "_|") for word in plain.split())
    return [word for word in words if word.strip("'")]


def encode(words):
    """Tokens for a run of words with boundaries around them, and where each word's first letter sits."""
    tokens, starts = [BOUNDARY], []
    for word in words:
        starts.append(len(tokens))
        tokens += [TOKEN[letter] for letter in word]
        tokens.append(BOUNDARY)
    return tokens, starts


def _mel(hz):
    return 2595 * np.log10(1 + hz / 700)


def _hz(mel):
    return 700 * (10 ** (mel / 2595) - 1)


@lru_cache(maxsize=4)
def _filters(rate):
    bins = np.fft.rfftfreq(round(rate * WINDOW_SECONDS), 1 / rate)
    edges = _hz(np.linspace(_mel(LOW_HZ), _mel(HIGH_HZ), MEL_BINS + 2))
    rising = (bins[None] - edges[:-2, None]) / (edges[1:-1, None] - edges[:-2, None])
    falling = (edges[2:, None] - bins[None]) / (edges[2:, None] - edges[1:-1, None])
    return np.maximum(0, np.minimum(rising, falling)).astype(np.float32)


@lru_cache(maxsize=1)
def _weights():
    from .word_model_weights import DATA, SHAPES
    packed = np.frombuffer(zlib.decompress(base64.b85decode(DATA)), np.float16)
    weights, offset = {}, 0
    for name, shape in SHAPES.items():
        size = int(np.prod(shape))
        weights[name] = packed[offset:offset + size].reshape(shape).astype(np.float32)
        offset += size
    return weights


@lru_cache(maxsize=1)
def _gelu_table():
    grid = np.linspace(-GELU_LIMIT, GELU_LIMIT, 4801)
    return grid, np.array([x * .5 * (1 + math.erf(x / math.sqrt(2))) for x in grid], np.float32)


def _gelu(x):
    grid, values = _gelu_table()
    return np.where(x > GELU_LIMIT, x, np.interp(x, grid, values))


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def _normalised(x, weights, name):
    scale = weights[name + ".weight"] / np.sqrt(weights[name + ".running_var"] + 1e-5)
    return (x - weights[name + ".running_mean"]) * scale + weights[name + ".bias"]


class WordModel:
    def __init__(self):
        self.weights = _weights()
        self.reset()

    def reset(self):
        hidden = self.weights["memory.weight_hh_l0"].shape[1]
        self.tail = np.empty(0, np.float32)
        self.frames = [np.zeros(MEL_BINS, np.float32)] * 2
        self.convolved = []
        self.state = np.zeros((LAYERS, hidden), np.float32)

    def push(self, samples, rate):
        """Take mono samples. Returns log probabilities, one row per completed 20 ms step."""
        window, hop = round(rate * WINDOW_SECONDS), round(rate * HOP_SECONDS)
        data = np.concatenate((self.tail, np.asarray(samples, np.float32)))
        if len(data) < window:
            self.tail = data
            return np.empty((0, len(ALPHABET)), np.float32)
        count = 1 + (len(data) - window) // hop
        slices = np.lib.stride_tricks.sliding_window_view(data, window)[:count * hop:hop]
        shape = np.hanning(window + 1)[:-1].astype(np.float32)
        power = np.abs(np.fft.rfft(slices * shape, axis=1)) ** 2 / float(np.sum(shape * shape))
        self.tail = data[count * hop:]
        return self.push_features(np.log(power @ _filters(rate).T + FLOOR))

    def push_features(self, features):
        """Take log mel frames. Returns the steps they complete."""
        w = self.weights
        kernel, depthwise, mixing = w["first.0.weight"], w["second.0.weight"][:, 0], w["second.1.weight"][:, :, 0]
        rows = []
        for frame in (features - FEATURE_MEAN) / FEATURE_STD:
            self.frames.append(frame.astype(np.float32))
            if len(self.frames) < 5:
                continue
            stacked = np.stack(self.frames)
            del self.frames[0]
            self.convolved.append(_gelu(_normalised(np.einsum("cfk,kf->c", kernel, stacked), w, "first.1")))
            if len(self.convolved) < 3:
                continue
            step = np.einsum("ck,kc->c", depthwise, np.stack(self.convolved))
            del self.convolved[:STRIDE]
            rows.append(self._remember(_gelu(_normalised(mixing @ step, w, "second.2"))))
        return np.stack(rows) if rows else np.empty((0, len(ALPHABET)), np.float32)

    def _remember(self, x):
        w = self.weights
        for layer in range(LAYERS):
            suffix = f"_l{layer}"
            hidden = self.state[layer]
            reset, update, new = np.split(w["memory.weight_ih" + suffix] @ x + w["memory.bias_ih" + suffix], 3)
            held_reset, held_update, held_new = np.split(w["memory.weight_hh" + suffix] @ hidden + w["memory.bias_hh" + suffix], 3)
            gate = _sigmoid(held_update + update)
            fresh = np.tanh(new + held_new * _sigmoid(held_reset + reset))
            x = self.state[layer] = (hidden - fresh) * gate + fresh
        logits = w["head.weight"] @ x + w["head.bias"]
        return logits - np.logaddexp.reduce(logits)

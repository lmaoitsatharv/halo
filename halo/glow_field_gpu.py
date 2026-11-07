"""Neon and Liquid on the GPU: the light-field model as an OpenGL 3.3 shader.

Each edge strip renders into its own framebuffer at display resolution. The
GPU copies it into a pixel buffer, which is read into a reusable array in the
byte order of a premultiplied ARGB image: only the strips cross the bus, and
the driver's slow synchronous framebuffer read is never used. Any
failure turns the renderer off for good and Halo draws the same model with
NumPy instead. HALO_DISABLE_FIELD_GPU=1 forces that path.
"""
from collections import OrderedDict, deque
import logging
import os
from statistics import median

import numpy as np
import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtGui import (QGuiApplication, QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat,
                           QVector2D, QVector3D, QVector4D)
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                              QOpenGLShader, QOpenGLShaderProgram, QOpenGLVersionFunctionsFactory,
                              QOpenGLVersionProfile, QOpenGLVertexArrayObject)

log = logging.getLogger(__name__)

GL_COLOR_BUFFER_BIT, GL_BLEND, GL_TRIANGLES, GL_RGBA8 = 0x4000, 0x0BE2, 0x0004, 0x8058
GL_BGRA, GL_UNSIGNED_BYTE = 0x80E1, 0x1401
FRAME_BUDGET_MS = 8.
BUDGET_FRAMES = 40
RENDER_SCALES = (1., .75, .5)
MAX_TARGETS = 12
IDLE_RELEASE_MS = 30_000
DROPS = 24

VERTEX = """#version 330 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2. - 1., 0., 1.);
}"""

FRAGMENT = """#version 330 core
out vec4 frag;
uniform vec2 uSize, uOrigin, uScale;
uniform float uMode, uPhase, uBeat, uMusic, uBand, uRim, uOpacity, uMix, uStrength;
uniform vec4 uTubes;
uniform vec3 uA, uB;
// Calibration shared with the NumPy path: tube, filament, glass, white; glow, haze; film, body, liquid glow.
uniform vec4 uNeonA;
uniform vec2 uNeonB;
uniform vec3 uLiquid;
const int DROPS = 24;
uniform vec4 uDropPos[DROPS];    // centre, clockwise tangent
uniform vec4 uDropShape[DROPS];  // along, across, strength, perimeter fraction
uniform vec3 uDropCol[DROPS];
const float TAU = 6.28318530718;

float radius() { return min(16., min(uSize.x, uSize.y) / 4.); }
float perimeter() { float r = radius(); return 2. * (uSize.x + uSize.y - 4. * r) + TAU * r; }
vec3 whiten(vec3 c, float e, float k) { return c + (e - c) * k; }
float energy(vec3 c) { return max(c.r, max(c.g, c.b)); }

float paletteAmount(float c, float prop, float soft) {
    if (prop <= 0.) return 1.;
    if (prop >= 1.) return 0.;
    c = fract(c);
    float tr = min(soft, min(prop, 1. - prop));
    float t = clamp((min(c, 1. - c) - prop * .5) / tr + .5, 0., 1.);
    return t * t * (3. - 2. * t);
}

vec3 knee(vec3 v) { return mix(v, .8 + .2 * (1. - exp(-(v - .8) / .2)), step(.8, v)); }

// Light comes out in units of the local colour at full energy (rgb) plus that energy (a);
// main() rolls off highlights, then applies the energy and the shared strength.
vec4 neon(float u, float d, int tube) {
    float L = perimeter(), r = radius();
    float topCentre = (uSize.x * .5 - r) / L;
    vec3 raw = mix(uA, uB, paletteAmount((u - topCentre) * 2. + .03 * sin(TAU * uPhase), uMix, .08));
    float e = energy(raw);
    vec3 C = e > 1e-6 ? raw / e : vec3(0.);
    vec3 hot = whiten(C, 1., uNeonA.w);
    float tw = max(2.5, uRim * uNeonA.x);
    float centre = tw * .5 + 1.;
    float striation = 1. + .1 * sin(TAU * (u * floor(L / 34.) - 5. * uPhase));
    float stripes = striation * (uMusic > .5 ? .75 + .45 * uBeat : 1.);
    float glowGain = uMusic > .5 ? .5 + uBeat : 1.;
    float off = d - centre;
    float filament = uNeonA.y * exp(-pow(off / max(.7, tw * .15), 2.));
    float glass = uNeonA.z * exp(-pow(abs(off) / (tw * .5), 4.));
    float glow = uNeonB.x * exp(-pow(abs(off) / (d < centre ? tw * .8 : .2 * uBand), 1.3));
    float t0 = clamp(d / uBand, 0., 1.), t1 = clamp(d / (uBand * 1.25), 0., 1.);
    float haze = pow(1. - t0, 1.6) * exp(-1.6 * t0 * t0);
    float wide = pow(1. - t1, 1.6) * exp(-1.6 * t1 * t1);
    if (uMusic > .5) haze += (wide - haze) * uBeat;
    float lit = uTubes[tube];
    return vec4(hot * (filament * stripes * lit) + C * ((glass * stripes + (glow * striation + uNeonB.y * haze) * uOpacity * glowGain) * lit), e);
}

float rimDepth(vec2 p, out vec2 slope) {
    float r = radius();
    vec2 half_ = uSize * .5;
    vec2 q = abs(p - half_) - (half_ - r);
    float sdf = length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r;
    vec2 n = (q.x > 0. && q.y > 0.) ? normalize(q) : (q.x > q.y ? vec2(1., 0.) : vec2(0., 1.));
    slope = -n * sign(p - half_);
    return -sdf;
}

vec3 liquidColour(float u) {
    float L = perimeter();
    float calm = .002;
    vec3 paint = (uA + uB) * .5 * calm;
    float total = calm;
    for (int i = 0; i < DROPS; i++) {
        float gap = mod(u * L - uDropShape[i].w * L + L * .5, L) - L * .5;
        float w = uDropShape[i].z * exp(-.5 * pow(gap / (1.6 * uDropShape[i].x), 2.));
        paint += uDropCol[i] * w;
        total += w;
    }
    return paint / total;
}

vec4 liquid(vec2 p, float uH, float uV, float wH) {
    vec2 depthSlope;
    float depth = rimDepth(p, depthSlope);
    float film = exp(-(depth - max(1.5, uRim * uLiquid.x)) / (.07 * uBand));
    float f = film;
    vec2 grad = film * (-1. / (.07 * uBand)) * depthSlope;
    for (int i = 0; i < DROPS; i++) {
        vec2 dp = p - uDropPos[i].xy;
        vec4 sh = uDropShape[i];
        // Past three spreads a drop adds nothing visible; the NumPy path stops there too.
        if (abs(dp.x) > 3. * sh.x || abs(dp.y) > 3. * sh.x) continue;
        vec2 t = uDropPos[i].zw;
        float a = dot(dp, t), b = dp.y * t.x - dp.x * t.y;
        float g = sh.z * exp(-.5 * (a * a / (sh.x * sh.x) + b * b / (sh.y * sh.y)));
        float pa = -a / (sh.x * sh.x) * g, pb = -b / (sh.y * sh.y) * g;
        f += g;
        grad += vec2(pa * t.x - pb * t.y, pa * t.y + pb * t.x);
    }
    if (f <= .02) return vec4(0.);
    // Along the straight edges one side owns the pixel; only corners blend both.
    vec3 raw = wH > .999 ? liquidColour(uH) : wH < .001 ? liquidColour(uV) : mix(liquidColour(uV), liquidColour(uH), wH);
    float lightEnergy = energy(raw);
    if (lightEnergy <= 1e-6) return vec4(0.);
    float inside = clamp((f - 1.) / max(length(grad), 1e-4) + .5, 0., 1.);
    vec3 n = normalize(vec3(-grad * (uBand * .32), 1.));
    vec3 key = normalize(vec3(-.45, -.65, .62));
    float diffuse = max(dot(n, key), 0.);
    float spec = pow(max(dot(n, normalize(key + vec3(0., 0., 1.))), 0.), 46.);
    float spec2 = pow(max(dot(n, normalize(normalize(vec3(.55, .5, .66)) + vec3(0., 0., 1.))), 0.), 90.);
    float rim = pow(1. - n.z, 2.);
    vec3 C = raw / lightEnergy;
    float e = energy(C);
    // The drops are this mode's glow, so glow opacity sets how strongly they shine.
    float bodyGain = (uLiquid.y + (1. - uLiquid.y) * uOpacity) * (uMusic > .5 ? .85 + .3 * uBeat : 1.);
    vec3 body = (C * (.66 + .34 * diffuse) + whiten(C, e, .5) * rim * .4) * bodyGain + e * (spec * .85 + spec2 * .35);
    vec3 glow = C * uLiquid.z * uOpacity * pow(clamp(f, 0., 1.), 2.) * (1. - inside);
    return vec4(body * inside + glow, lightEnergy);
}

void main() {
    vec2 p = uOrigin + gl_FragCoord.xy / uScale;
    float r = radius();
    vec2 half_ = uSize * .5;
    vec2 q = abs(p - half_) - (half_ - r);
    float sdf = length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r;
    float depth = max(-sdf, 0.);
    float cover = clamp(.5 - sdf * min(uScale.x, uScale.y), 0., 1.);
    float dh = min(p.y, uSize.y - p.y), dv = min(p.x, uSize.x - p.x);
    float corner = depth - min(dh, dv);
    float dH = max(dh + corner, 0.), dV = max(dv + corner, 0.);
    float arc = .25 * TAU * r, L = perimeter();
    float cx = clamp(p.x, r, uSize.x - r), cy = clamp(p.y, r, uSize.y - r);
    float sw = uSize.x - 2. * r, shh = uSize.y - 2. * r;
    bool top = p.y < half_.y, left = p.x < half_.x;
    float sH = top ? cx - r : sw + shh + 2. * arc + (uSize.x - r - cx);
    float sV = left ? 2. * sw + shh + 3. * arc + (uSize.y - r - cy) : sw + arc + (cy - r);
    float wH = 1. / (1. + exp(clamp(3. * (dH - dV) / (.4 * uBand), -60., 60.)));
    vec4 V;
    if (uMode < .5) {
        V = mix(neon(sV / L, dV, left ? 3 : 1), neon(sH / L, dH, top ? 0 : 2), wH);
    } else {
        V = liquid(p, sH / L, sV / L, wH);
    }
    float fade = clamp((uBand - depth) / (.1 * uBand), 0., 1.);
    fade = fade * fade * (3. - 2. * fade);
    // The brightest pixel matches the other modes' crisp rim: energy times strength.
    vec3 rgb = knee(V.rgb) * (V.a * fade * uStrength * cover);
    frag = vec4(rgb, max(rgb.r, max(rgb.g, rgb.b)));
}"""


def field_gpu_disabled():
    return os.environ.get("HALO_DISABLE_FIELD_GPU") == "1"


class FieldBudget:
    """Steps the render scale down while the median of recent frames is over budget."""

    def __init__(self):
        self.scale = RENDER_SCALES[0]
        self._frames = deque(maxlen=BUDGET_FRAMES)

    def record(self, ms):
        self._frames.append(ms)
        if len(self._frames) < BUDGET_FRAMES or median(self._frames) <= FRAME_BUDGET_MS:
            return
        self._frames.clear()
        smaller = [scale for scale in RENDER_SCALES if scale < self.scale]
        if smaller:
            self.scale = smaller[0]
            log.info("Halo light field renders at %.2f of display resolution to stay within %.0f ms",
                     self.scale, FRAME_BUDGET_MS)


class FieldRenderer:
    """Renders the Neon and Liquid strips on an offscreen OpenGL 3.3 context."""

    def __init__(self):
        self.available = False
        self.reason = ""
        self.budget = FieldBudget()
        self._targets = OrderedDict()
        self._buffers = {}
        self._packs = {}
        self._context = self._surface = self._gl = self._program = self._vao = None
        self._idle = QTimer()
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_RELEASE_MS)
        self._idle.timeout.connect(self.release)
        if field_gpu_disabled():
            self.reason = "HALO_DISABLE_FIELD_GPU is set"
            return
        try:
            self._setup()
        except Exception as error:
            self._fail(f"setup failed: {error}")

    def _setup(self):
        form = QSurfaceFormat()
        form.setVersion(3, 3)
        form.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        form.setOption(QSurfaceFormat.FormatOption.ResetNotification)
        self._context = QOpenGLContext()
        self._context.setFormat(form)
        if not self._context.create():
            raise RuntimeError("no OpenGL 3.3 context")
        self._surface = QOffscreenSurface()
        self._surface.setFormat(self._context.format())
        self._surface.create()
        if not self._context.makeCurrent(self._surface):
            raise RuntimeError("the OpenGL context could not be made current")
        try:
            profile = QOpenGLVersionProfile()
            profile.setVersion(3, 3)
            profile.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self._gl = QOpenGLVersionFunctionsFactory.get(profile, self._context)
            if self._gl is None:
                raise RuntimeError("no OpenGL 3.3 functions")
            self._program = QOpenGLShaderProgram()
            for kind, source in ((QOpenGLShader.ShaderTypeBit.Vertex, VERTEX),
                                 (QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT)):
                if not self._program.addShaderFromSourceCode(kind, source):
                    raise RuntimeError(f"shader failed: {self._program.log()}")
            if not self._program.link():
                raise RuntimeError(f"shader link failed: {self._program.log()}")
            self._vao = QOpenGLVertexArrayObject()
            if not self._vao.create():
                raise RuntimeError("no vertex array object")
        finally:
            self._context.doneCurrent()
        self.available = True

    def _fail(self, reason):
        """Turn the GPU path off for good and say why, once."""
        self.available = False
        self.reason = reason
        log.warning("Halo light field GPU renderer is off: %s", reason)
        self.release()

    def render(self, light, sx, sy, blocks):
        """(image, buffer) per strip block, or None when the caller should draw with NumPy.

        Each image wraps its buffer, which the renderer reuses on the next pass:
        draw the images before rendering again.
        """
        if not self.available:
            return None
        try:
            if self._context is None:
                self._setup()
            if not self._context.makeCurrent(self._surface):
                self._fail("the OpenGL context was lost")
                return None
            try:
                images = self._draw(light, sx, sy, blocks)
            finally:
                self._context.doneCurrent()
        except Exception as error:
            self._fail(f"a light pass failed: {error}")
            return None
        self._idle.start()
        return images

    def _draw(self, light, sx, sy, blocks):
        gl, program = self._gl, self._program
        self._vao.bind()
        program.bind()
        gl.glDisable(GL_BLEND)
        program.setUniformValue("uSize", QVector2D(light["w"], light["h"]))
        program.setUniformValue("uScale", QVector2D(sx, sy))
        program.setUniformValue1f("uMode", 0. if light["mode"] == "neon" else 1.)
        for name in ("phase", "beat", "band", "rim", "opacity", "mix", "strength"):
            program.setUniformValue1f("u" + name.capitalize(), float(light[name]))
        program.setUniformValue1f("uMusic", 1. if light["music"] else 0.)
        program.setUniformValue("uTubes", QVector4D(*(float(level) for level in light["levels"])))
        program.setUniformValue("uA", QVector3D(*(float(v) for v in light["a"])))
        program.setUniformValue("uB", QVector3D(*(float(v) for v in light["b"])))
        tube, filament, glass, white, glow, haze, film, body, liquid_glow = (float(v) for v in light["calibration"])
        program.setUniformValue("uNeonA", QVector4D(tube, filament, glass, white))
        program.setUniformValue("uNeonB", QVector2D(glow, haze))
        program.setUniformValue("uLiquid", QVector3D(film, body, liquid_glow))
        drops = light["drops"] or ()
        for i in range(DROPS):
            if i < len(drops):
                x, y, tx, ty, along, across, strength, colour, s = drops[i]
            else:
                # Unused slots sit far away with no strength, so the shader skips them.
                x = y = -1e5
                tx = along = across = 1.
                ty = strength = s = 0.
                colour = (0., 0., 0.)
            program.setUniformValue(f"uDropPos[{i}]", QVector4D(x, y, tx, ty))
            program.setUniformValue(f"uDropShape[{i}]", QVector4D(along, across, strength, s))
            program.setUniformValue(f"uDropCol[{i}]", QVector3D(*(float(v) for v in colour)))
        targets = []
        for index, (c0, c1, r0, r1) in enumerate(blocks):
            cols, rows = c1 - c0, r1 - r0
            fbo = self._target(index, cols, rows)
            if not fbo.bind():
                raise RuntimeError("the light framebuffer could not be bound")
            gl.glViewport(0, 0, cols, rows)
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            program.setUniformValue("uOrigin", QVector2D(c0 / sx, r0 / sy))
            gl.glDrawArrays(GL_TRIANGLES, 0, 3)
            targets.append((fbo, cols, rows))
        # Copy into pixel buffers only after every strip is queued, so the GPU never idles between draws.
        packs = []
        for index, (fbo, cols, rows) in enumerate(targets):
            pack = self._pack(index, cols * rows * 4)
            fbo.bind()
            pack.bind()
            # The first row copied is the framebuffer's lowest: the strip's top.
            gl.glReadPixels(0, 0, cols, rows, GL_BGRA, GL_UNSIGNED_BYTE, shiboken6.VoidPtr(0))
            pack.release()
            fbo.release()
            packs.append(pack)
        images = []
        for index, ((_, cols, rows), pack) in enumerate(zip(targets, packs)):
            pixels = self._buffer(index, cols, rows)
            pack.bind()
            if not pack.read(0, pixels, pixels.nbytes):
                raise RuntimeError("the light pixels could not be read")
            pack.release()
            images.append((QImage(pixels.data, cols, rows, cols * 4, QImage.Format.Format_ARGB32_Premultiplied),
                           pixels))
        program.release()
        self._vao.release()
        return images

    def _pack(self, index, size):
        pack = self._packs.get(index)
        if pack is not None and pack.size() == size:
            return pack
        if pack is not None:
            pack.destroy()
        pack = QOpenGLBuffer(QOpenGLBuffer.Type.PixelPackBuffer)
        if not pack.create():
            raise RuntimeError("no pixel buffer")
        pack.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamRead)
        pack.bind()
        pack.allocate(size)
        pack.release()
        self._packs[index] = pack
        return pack

    def _buffer(self, index, cols, rows):
        pixels = self._buffers.get(index)
        if pixels is None or pixels.shape != (rows, cols, 4):
            pixels = self._buffers[index] = np.empty((rows, cols, 4), dtype=np.uint8)
        return pixels

    def _target(self, index, cols, rows):
        # One framebuffer per strip: every strip is drawn before any is read back.
        key = (index, cols, rows)
        if key in self._targets:
            self._targets.move_to_end(key)
            return self._targets[key]
        form = QOpenGLFramebufferObjectFormat()
        form.setInternalTextureFormat(GL_RGBA8)
        fbo = QOpenGLFramebufferObject(cols, rows, form)
        if not fbo.isValid():
            raise RuntimeError("the light framebuffer is not valid")
        self._targets[key] = fbo
        while len(self._targets) > MAX_TARGETS:
            self._targets.popitem(last=False)
        return fbo

    def close(self):
        """Free the GPU objects for good; render returns None afterwards."""
        self.available = False
        if not self.reason:
            self.reason = "closed"
        self.release()

    def release(self):
        """Free the GPU objects now; an available renderer rebuilds them on its next pass."""
        self._idle.stop()
        context, self._context = self._context, None
        if context is not None and self._surface is not None and context.makeCurrent(self._surface):
            self._targets.clear()
            for pack in self._packs.values():
                pack.destroy()
            if self._vao is not None:
                self._vao.destroy()
            context.doneCurrent()
        self._targets.clear()
        self._packs.clear()
        self._program = self._vao = self._gl = self._surface = None


_shared = None


def shared_field_renderer():
    """The one GPU renderer, created on first use; None outside a running Qt application."""
    global _shared
    if _shared is None:
        if QGuiApplication.instance() is None:
            return None
        _shared = FieldRenderer()
    return _shared


def shutdown_field_renderer():
    """Close and forget the shared GPU renderer, if there is one."""
    global _shared
    renderer, _shared = _shared, None
    if renderer is not None:
        renderer.close()

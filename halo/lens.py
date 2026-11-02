"""A GPU lens for Fisheye: pure mapping maths, a frame budget and an offscreen OpenGL renderer."""
import logging
import math
import os
from collections import OrderedDict, deque
from dataclasses import dataclass
from statistics import median

from PySide6.QtCore import QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVersionFunctionsFactory,
                              QOpenGLVersionProfile, QOpenGLVertexArrayObject)

log = logging.getLogger(__name__)

LENS_STRENGTH = .55
LENS_FRINGE = .02
LENS_X_WEIGHT = .35
FRAME_BUDGET_MS = 12.
BUDGET_FRAMES = 30
SOURCE_SCALES = (1.25, 1.)
MAX_OUTPUT_PIXELS = 2_000_000
COLUMN_SHARE = .65
MIN_CANVAS = (240, 120)
MAX_TARGETS = 4
IDLE_RELEASE_MS = 30_000
OFF_TEXT = "The GPU lens is off on this PC, so Fisheye uses standard drawing."

GL_COLOR_BUFFER_BIT, GL_BLEND, GL_TRIANGLES, GL_RGBA8 = 0x4000, 0x0BE2, 0x0004, 0x8058

VERTEX = """#version 330 core
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2. - 1., 0., 1.);
}"""
FRAGMENT = """#version 330 core
in vec2 v_uv;
out vec4 frag;
uniform sampler2D tex;
uniform float strength;
uniform float fringe;
vec2 warp(vec2 n, float s) {
    float r2 = .35 * n.x * n.x + n.y * n.y;
    return n * (1. - s + s * r2) * .5 + .5;
}
void main() {
    vec2 n = v_uv * 2. - 1.;
    float rim = smoothstep(.25, 1.1, length(n));
    float edge = 1. - smoothstep(.82, 1., abs(n.y));
    vec4 g = texture(tex, warp(n, strength));
    float r = texture(tex, warp(n, strength + fringe * rim)).r;
    float b = texture(tex, warp(n, strength - fringe * rim)).b;
    frag = vec4(r, g.g, b, max(g.a, max(r, b))) * edge;
}"""


def warp_source(nx, ny, strength=LENS_STRENGTH):
    """Where the lens samples the source for output point (nx, ny), all in -1 to 1 units."""
    scale = 1. - strength + strength * (LENS_X_WEIGHT * nx * nx + ny * ny)
    return nx * scale, ny * scale


def output_y(source_y, strength=LENS_STRENGTH):
    """Output height of a source height along nx = 0, the inverse of warp_source by bisection."""
    limit = max(1., abs(source_y))
    low, high = -limit, limit
    for _ in range(40):
        middle = (low + high) / 2
        if warp_source(0, middle, strength)[1] < source_y:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def magnification(ny, strength=LENS_STRENGTH):
    """Output size per source size at output height ny, along nx = 0."""
    return 1. / (1. - strength + 3. * strength * ny * ny)


@dataclass(frozen=True)
class LensGeometry:
    column: QRectF
    output: QSize
    source: QSize
    source_per_logical: float


def lens_geometry(width, height, dpr, scale):
    """The word column, the lens output and the source image to draw for a canvas of width x height."""
    column_width = width * COLUMN_SHARE
    column = QRectF((width - column_width) / 2, 0, column_width, height)
    wide, high = column_width * dpr, height * dpr
    fit = min(1., math.sqrt(MAX_OUTPUT_PIXELS / max(1., wide * high)))
    # Rounded sizes can overshoot the cap, so a capped output rounds down.
    snap = round if fit == 1. else math.floor
    output = QSize(max(1, snap(wide * fit)), max(1, snap(high * fit)))
    source = QSize(max(1, round(output.width() * scale)), max(1, round(output.height() * scale)))
    return LensGeometry(column, output, source, dpr * fit * scale)


def lens_disabled():
    return os.environ.get("HALO_DISABLE_LENS") == "1"


class LensBudget:
    """Steps the source scale down, then the lens off, while the median of the last 30 frames is over budget."""
    def __init__(self):
        self.scale = SOURCE_SCALES[0]
        self.enabled = True
        self._frames = deque(maxlen=BUDGET_FRAMES)
        self._skip = False

    def skip_next(self):
        """Leave out the next frame, whose time went on rebuilding the GPU objects."""
        self._skip = True

    def record(self, ms):
        if not self.enabled:
            return
        if self._skip:
            self._skip = False
            return
        self._frames.append(ms)
        if len(self._frames) < BUDGET_FRAMES or median(self._frames) <= FRAME_BUDGET_MS:
            return
        self._frames.clear()
        smaller = [scale for scale in SOURCE_SCALES if scale < self.scale]
        if smaller:
            self.scale = smaller[0]
        else:
            self.enabled = False
            log.info("Fisheye GPU lens turned off: frames stayed over %.0f ms at the smallest source", FRAME_BUDGET_MS)


class LensRenderer:
    """Warps a premultiplied RGBA image through the Fisheye lens on an offscreen OpenGL 3.3 context."""
    def __init__(self):
        self.available = False
        self.reason = ""
        self.budget = LensBudget()
        self._targets = OrderedDict()
        self._context = self._surface = self._gl = self._program = self._vao = None
        self._idle = QTimer()
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_RELEASE_MS)
        self._idle.timeout.connect(self.release)
        if lens_disabled():
            self.reason = "HALO_DISABLE_LENS is set"
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
        """Turn the lens off for good and say why. Only the first failure gets here, so it logs once."""
        self.available = False
        self.reason = reason
        log.warning("Fisheye GPU lens is off: %s", reason)
        self.release()

    def apply(self, image, output):
        """The image warped through the lens at the output size, or None when the caller should draw itself."""
        if not self.available or not self.budget.enabled or image.isNull() or output.isEmpty():
            return None
        try:
            if self._context is None:
                self._setup()
                self.budget.skip_next()
            if not self._context.makeCurrent(self._surface):
                self._fail("the OpenGL context was lost")
                return None
            try:
                result = self._draw(image, output)
            finally:
                self._context.doneCurrent()
        except Exception as error:
            self._fail(f"a lens pass failed: {error}")
            return None
        self._idle.start()
        return result

    def _draw(self, image, output):
        if image.format() != QImage.Format.Format_RGBA8888_Premultiplied:
            image = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        fbo, texture = self._target(image.size(), output)
        texture.setData(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.UInt8, image.constBits())
        gl = self._gl
        self._vao.bind()
        if not fbo.bind():
            raise RuntimeError("the lens framebuffer could not be bound")
        gl.glViewport(0, 0, output.width(), output.height())
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        gl.glDisable(GL_BLEND)
        self._program.bind()
        texture.bind(0)
        self._program.setUniformValue1i("tex", 0)
        self._program.setUniformValue1f("strength", LENS_STRENGTH)
        self._program.setUniformValue1f("fringe", LENS_FRINGE)
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)
        result = fbo.toImage(False)
        fbo.release()
        self._program.release()
        self._vao.release()
        if result.isNull():
            raise RuntimeError("the lens pass returned no image")
        return result

    def _target(self, source, output):
        """The framebuffer and source texture for this size pair, newest used last."""
        key = (source.width(), source.height(), output.width(), output.height())
        if key in self._targets:
            self._targets.move_to_end(key)
            return self._targets[key]
        form = QOpenGLFramebufferObjectFormat()
        form.setInternalTextureFormat(GL_RGBA8)
        fbo = QOpenGLFramebufferObject(output.width(), output.height(), form)
        if not fbo.isValid():
            raise RuntimeError("the lens framebuffer is not valid")
        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        texture.setSize(source.width(), source.height())
        texture.allocateStorage(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.UInt8)
        texture.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToBorder)
        texture.setBorderColor(QColor(0, 0, 0, 0))
        self._targets[key] = fbo, texture
        while len(self._targets) > MAX_TARGETS:
            self._targets.popitem(last=False)[1][1].destroy()
        return fbo, texture

    def close(self):
        """Free the GPU objects for good. Safe in any state; apply returns None afterwards."""
        self.available = False
        if not self.reason:
            self.reason = "closed"
        self.release()

    def release(self):
        """Free the GPU objects now. The lens stays as it was, so an available one rebuilds them on its next pass."""
        self._idle.stop()
        context, self._context = self._context, None
        if context is not None and self._surface is not None and context.makeCurrent(self._surface):
            while self._targets:
                self._targets.popitem()[1][1].destroy()
            if self._vao is not None:
                self._vao.destroy()
            self._program = self._vao = self._gl = None
            context.doneCurrent()
        self._targets.clear()
        self._program = self._vao = self._gl = self._surface = None


_shared = None


def shared_lens():
    """The one renderer, created on first use."""
    global _shared
    if _shared is None:
        _shared = LensRenderer()
    return _shared


def shutdown_lens():
    """Close and forget the shared renderer, if there is one."""
    global _shared
    lens, _shared = _shared, None
    if lens is not None:
        lens.close()


def lens_status_text():
    """One line for settings when a lens was tried and is off, otherwise nothing. Never creates a renderer."""
    if _shared is None or (_shared.available and _shared.budget.enabled):
        return ""
    return OFF_TEXT

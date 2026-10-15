"""Compact native controls for the halo's light and its two raw colours."""
from PySide6.QtCore import Qt, QRectF, QSignalBlocker, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                              QComboBox, QSlider, QStackedWidget, QButtonGroup,
                              QColorDialog, QSizePolicy)


HALO_ANIMATIONS = (
    ("flow", "Flow", "Keep the halo moving smoothly."),
    ("music", "Music sync", "Let the halo move with the sound."),
    ("idle", "Idle", "Use a slow resting animation."),
    ("still", "Still", "Hold the halo steady. Your motion speed is saved for later."),
)
PALETTES = ("Album colours", "Violet hour", "Sea glass", "Ember", "Custom")


class ColorWell(QPushButton):
    """An actual, unbrightened colour sample with a readable hex label."""
    def __init__(self, role, parent=None):
        super().__init__(parent)
        self.role = role
        self.color = QColor("#0a0d14" if role == "primary" else "#005dff")
        self.setObjectName("haloColorWell")
        self.setMinimumSize(110, 50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setColor(self.color)

    def setColor(self, color):
        candidate = QColor(color)
        if not candidate.isValid():
            return
        candidate.setAlpha(255)
        changed = candidate != self.color
        self.color = candidate
        self.setText(candidate.name().upper())
        self.setAccessibleName(f"Choose {self.role} halo colour, {self.text()}")
        self.setToolTip(f"Choose the {self.role} halo colour. Current colour: {self.text()}.")
        if changed:
            self.update()

    @property
    def hex_color(self):
        return self.color.name()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor("#272c3b" if self.underMouse() else "#1a1e28"))
        p.setPen(QPen(QColor("#a995d3" if self.hasFocus() else "#464d60" if self.underMouse() else "#373e50"), 1.2))
        p.drawRoundedRect(box, 11, 11)
        p.setBrush(self.color)
        p.setPen(QPen(QColor("#626b7c"), 1))
        p.drawEllipse(QRectF(12, (self.height() - 24) / 2, 24, 24))
        face = QFont("Segoe UI")
        face.setPixelSize(11)
        p.setFont(face)
        p.setPen(QColor("#dce0ed"))
        p.drawText(QRectF(45, 0, self.width() - 53, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class LightControls(QWidget):
    """Light/Colours pages share controller state without changing UI accents."""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("haloFineTune")
        self.setStyleSheet("""
            QPushButton#haloTuneTab { border: 0; border-radius: 9px; padding: 7px 10px; background: transparent; color: #9098ac; font-size: 11px; }
            QPushButton#haloTuneTab:checked { background: #343447; color: #f0eafa; }
            QPushButton#haloTuneTab:focus { border: 1px solid #ad98d9; padding: 6px 9px; }
            QLabel#haloTuneLabel { font-size: 11px; color: #b4bbce; }
            QLabel#haloTuneValue { font-size: 11px; color: #e0d5f6; }
            QLabel#haloTuneBalance { font-size: 10px; color: #8893ac; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        tabrow = QHBoxLayout()
        tabrow.setSpacing(4)
        self.tabs = QButtonGroup(self)
        self.pages = QStackedWidget(self)
        for index, title in enumerate(("Light", "Colours")):
            tab = QPushButton(title)
            tab.setObjectName("haloTuneTab")
            tab.setCheckable(True)
            tab.setAccessibleName(f"Fine tune {title.lower()}")
            tab.setChecked(index == 0)
            self.tabs.addButton(tab, index)
            tabrow.addWidget(tab, 1)
        self.tabs.idClicked.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(lambda index: self.tabs.button(index).setChecked(True))
        root.addLayout(tabrow)
        root.addWidget(self.pages)
        self.sliders = {}
        self.value_labels = {}
        self.suffixes = {}
        self.color_dialog = None

        light = self._page()
        light.addWidget(self._label("Animation"))
        self.animation_select = QComboBox()
        self.animation_select.setAccessibleName("Halo animation")
        for key, title, description in HALO_ANIMATIONS:
            self.animation_select.addItem(title, key)
            self.animation_select.setItemData(self.animation_select.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self.animation_select.setToolTip("Choose how the halo moves.")
        self.animation_select.currentIndexChanged.connect(lambda index: controller.set("halo_animation", self.animation_select.itemData(index)) if index >= 0 else None)
        light.addWidget(self.animation_select)
        self._slider(light, "Rim width", "rim_width", 1, 12, " px", "Set the thickness of the bright edge line.", 3)
        self._slider(light, "Glow spread", "glow_width", 12, 160, " px", "Set how far the soft glow reaches inward from the screen edge.", 40)
        self._slider(light, "Glow opacity", "glow_opacity", 0, 100, "%", "Set how transparent the soft glow appears.", 65)
        self._slider(light, "Glow intensity", "intensity", 0, 100, "%", "Set the overall strength of the halo.", 62)
        self._slider(light, "Motion speed", "motion_speed", 0, 100, "%", "Set how quickly the halo moves. Still keeps your saved speed for later.", 45)
        light.addStretch(1)

        colours = self._page()
        colours.addWidget(self._label("Colour palette"))
        self.palette_select = QComboBox()
        self.palette_select.setAccessibleName("Colour palette")
        self.palette_select.setToolTip("Use album colours, choose a preset, or set your own two colours.")
        self.palette_select.addItems(PALETTES)
        self.palette_select.currentTextChanged.connect(lambda value: controller.set("palette", value))
        colours.addWidget(self.palette_select)
        wells = QHBoxLayout()
        wells.setSpacing(8)
        for role, title in (("primary", "Primary"), ("secondary", "Secondary")):
            column = QVBoxLayout()
            column.setSpacing(6)
            column.addWidget(self._label(title))
            well = ColorWell(role)
            well.clicked.connect(lambda checked=False, side=role: self._choose_color(side))
            setattr(self, f"{role}_well", well)
            column.addWidget(well)
            wells.addLayout(column, 1)
        colours.addLayout(wells)
        self._slider(colours, "Primary brightness", "primary_brightness", 0, 100, "%", "Dim the primary colour without changing its saved colour.", 100)
        self._slider(colours, "Secondary brightness", "secondary_brightness", 0, 100, "%", "Dim the secondary colour independently.", 100)
        self._slider(colours, "Primary share", "color_mix", 0, 100, "%", "Choose how much of the halo uses the primary colour. The rest uses the secondary colour.", 60)
        self.mix_balance = self._label("", "haloTuneBalance")
        self.mix_balance.setAlignment(Qt.AlignmentFlag.AlignCenter)
        colours.addWidget(self.mix_balance)
        colours.addStretch(1)

        controller.settingChanged.connect(self.sync)
        controller.trackChanged.connect(self.sync)
        if hasattr(controller, "paletteChanged"):
            controller.paletteChanged.connect(self.sync)
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(125)
        self.preview_timer.timeout.connect(self._refresh_live_wells)
        self.preview_timer.start()
        self.sync()

    def _page(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.pages.addWidget(widget)
        return layout

    @staticmethod
    def _label(text, name="haloTuneLabel"):
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _slider(self, layout, title, field, low, high, suffix, tooltip, default):
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 1, 0, 1)
        box.setSpacing(5)
        heading = QHBoxLayout()
        heading.addWidget(self._label(title))
        heading.addStretch(1)
        value_label = self._label("", "haloTuneValue")
        heading.addWidget(value_label)
        box.addLayout(heading)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(getattr(self.controller, field, default))
        slider.setAccessibleName(title)
        slider.setToolTip(tooltip)
        slider.valueChanged.connect(lambda value: self.controller.set(field, value))
        box.addWidget(slider)
        layout.addWidget(row)
        self.sliders[field] = slider
        self.value_labels[field] = value_label
        self.suffixes[field] = suffix

    def _raw_color(self, side):
        if self.controller.palette == "Custom":
            return QColor(getattr(self.controller, f"custom_{side}", "#0a0d14" if side == "primary" else "#005dff"))
        return QColor(getattr(self.controller, f"halo_{side}", "#0a0d14" if side == "primary" else "#005dff"))

    def _refresh_live_wells(self):
        if self.isVisible() and self.controller.palette != "Custom":
            self.primary_well.setColor(self._raw_color("primary"))
            self.secondary_well.setColor(self._raw_color("secondary"))

    def _choose_color(self, side):
        if self.color_dialog is not None:
            self.color_dialog.raise_()
            self.color_dialog.activateWindow()
            return
        dialog = QColorDialog(self._raw_color(side), self)
        dialog.setWindowTitle(f"{side.capitalize()} halo colour")
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dialog.colorSelected.connect(lambda color: self.set_custom_color(side, color))
        dialog.finished.connect(lambda result: self._finish_dialog(dialog))
        self.color_dialog = dialog
        dialog.open()

    def _finish_dialog(self, dialog):
        if self.color_dialog is dialog:
            self.color_dialog = None
        dialog.deleteLater()

    def set_custom_color(self, side, color):
        if side not in ("primary", "secondary"):
            raise ValueError("Colour side must be primary or secondary.")
        color = QColor(color)
        if not color.isValid():
            raise ValueError("Choose a valid colour.")
        self.controller.set(f"custom_{side}", color.name())
        if self.controller.palette != "Custom":
            self.controller.set("palette", "Custom")

    def sync(self, *_):
        c = self.controller
        with QSignalBlocker(self.palette_select):
            self.palette_select.setCurrentText(c.palette)
        with QSignalBlocker(self.animation_select):
            self.animation_select.setCurrentIndex(max(0, self.animation_select.findData(getattr(c, "halo_animation", "flow"))))
        for field, slider in self.sliders.items():
            value = getattr(c, field, slider.value())
            with QSignalBlocker(slider):
                slider.setValue(value)
            self.value_labels[field].setText(f"{slider.value()}{self.suffixes[field]}")
        self.sliders["motion_speed"].setEnabled(getattr(c, "halo_animation", "flow") != "still")
        self.primary_well.setColor(self._raw_color("primary"))
        self.secondary_well.setColor(self._raw_color("secondary"))
        share = self.sliders["color_mix"].value()
        self.mix_balance.setText(f"Primary {share}%  ·  Secondary {100 - share}%")

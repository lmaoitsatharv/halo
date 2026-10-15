from PySide6.QtCore import Qt, QRectF, Signal, QSignalBlocker
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                              QSlider, QPushButton, QComboBox, QCheckBox, QWidget, QApplication)
from .models import floating_geometry
from .widgets import font, tint


class PositionPreview(QWidget):
    moved = Signal(int, int)

    def __init__(self, controller, screen_lookup):
        super().__init__()
        self.c = controller
        self.screen_lookup = screen_lookup
        self.setMinimumHeight(128)
        self.setMaximumHeight(156)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("Floating lyrics position preview; drag to reposition")
        self.c.settingChanged.connect(self.update)

    def bounds(self):
        screen = self.screen_lookup().availableGeometry()
        area = QRectF(self.rect()).adjusted(12, 10, -12, -10)
        scale = min(area.width() / screen.width(), area.height() / screen.height())
        w, h = screen.width() * scale, screen.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), screen, scale

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        monitor, screen, scale = self.bounds()
        p.setBrush(QColor("#0b1311"))
        p.setPen(QPen(QColor("#405247"), 1))
        p.drawRoundedRect(monitor, 10, 10)
        x, y, w, h = floating_geometry((0, 0, screen.width(), screen.height()), self.c.floating_x, self.c.floating_y)
        marker = QRectF(monitor.x() + x * scale, monitor.y() + y * scale, w * scale, h * scale)
        p.setBrush(tint(self.c.primary, 32))
        p.setPen(QPen(tint(self.c.primary, 170), 1))
        p.drawRoundedRect(marker, 6, 6)
        p.setFont(font(10, QFont.Weight.DemiBold))
        p.setPen(self.c.primary)
        p.drawText(marker, Qt.AlignmentFlag.AlignCenter, "Your lyrics")

    def move_to(self, point):
        monitor, screen, scale = self.bounds()
        low = floating_geometry((0, 0, screen.width(), screen.height()), 0, 0)
        high = floating_geometry((0, 0, screen.width(), screen.height()), 100, 100)
        px = (point.x() - monitor.x()) / scale - low[2] / 2
        py = (point.y() - monitor.y()) / scale - low[3] / 2
        x = round(100 * (px - low[0]) / (high[0] - low[0])) if high[0] > low[0] else 50
        y = round(100 * (py - low[1]) / (high[1] - low[1])) if high[1] > low[1] else 50
        self.moved.emit(max(0, min(100, x)), max(0, min(100, y)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.move_to(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move_to(event.position())


class PositionDialog(QDialog):
    def __init__(self, controller, owner):
        super().__init__(owner)
        self.c = controller
        self.owner = owner
        self.setWindowTitle("Floating lyrics position")
        self.setObjectName("positionDialog")
        self.setStyleSheet("QDialog#positionDialog { background: #121c17; }")
        self.setMinimumWidth(440)
        self.resize(460, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(9)
        title = QLabel("Put your lyrics where you want them.")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title.setWordWrap(True)
        layout.addWidget(title)
        hint = QLabel("Drag the preview or use the position sliders.")
        hint.setStyleSheet("color: #9daa9e;")
        layout.addWidget(hint)
        self.monitor = QComboBox()
        self.monitor.setAccessibleName("Floating lyrics monitor")
        self.update_monitors()
        self.monitor.currentIndexChanged.connect(lambda _: self.c.set("floating_screen", self.monitor.currentData() or ""))
        layout.addWidget(self.monitor)
        self.preview = PositionPreview(controller, owner.overlay_screen)
        self.preview.moved.connect(self.set_position)
        layout.addWidget(self.preview)
        self.x_slider = self.make_slider(layout, "Horizontal", "floating_x", "Left", "Right")
        self.y_slider = self.make_slider(layout, "Vertical", "floating_y", "Top", "Bottom")
        grid = QGridLayout()
        for row, y in enumerate((0, 50, 90)):
            for column, x in enumerate((0, 50, 100)):
                name = ("Top", "Middle", "Bottom")[row] + " " + ("left", "center", "right")[column]
                preset = QPushButton(("↖", "↑", "↗", "←", "●", "→", "↙", "↓", "↘")[row * 3 + column])
                preset.setToolTip(name)
                preset.setAccessibleName("Position " + name)
                preset.setAutoDefault(False)
                preset.setFixedHeight(34)
                preset.setStyleSheet("padding: 4px; font-size: 16px;")
                preset.clicked.connect(lambda checked=False, x=x, y=y: self.set_position(x, y))
                grid.addWidget(preset, row, column)
        layout.addLayout(grid)
        self.desktop_preview = QCheckBox("Preview on desktop")
        self.desktop_preview.setToolTip("Shows a click-through preview, even while Halo is open.")
        layout.addWidget(self.desktop_preview)
        footer = QHBoxLayout()
        reset = QPushButton("Reset position")
        reset.setAutoDefault(False)
        reset.clicked.connect(self.reset)
        footer.addWidget(reset)
        footer.addStretch()
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
        QApplication.instance().screenAdded.connect(lambda _: self.update_monitors())
        QApplication.instance().screenRemoved.connect(lambda _: self.update_monitors())

    def update_monitors(self):
        blocker = QSignalBlocker(self.monitor)
        self.monitor.clear()
        self.monitor.addItem("Primary display", "")
        for index, screen in enumerate(QApplication.screens(), 1):
            area = screen.availableGeometry()
            self.monitor.addItem(f"Display {index} · {area.width()} × {area.height()}", screen.name())
        selected = self.monitor.findData(self.c.floating_screen)
        self.monitor.setCurrentIndex(max(0, selected))
        del blocker

    def make_slider(self, layout, title, setting, low_label, high_label):
        row = QHBoxLayout()
        row.addWidget(QLabel(title + " · " + low_label + " → " + high_label))
        row.addStretch()
        value = QLabel(str(getattr(self.c, setting)) + "%")
        row.addWidget(value)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(getattr(self.c, setting))
        slider.setAccessibleName(title + " lyrics position")
        slider.valueChanged.connect(lambda number: (self.c.set(setting, number), value.setText(str(number) + "%")))
        layout.addWidget(slider)
        return slider

    def set_position(self, x, y):
        self.x_slider.setValue(x)
        self.y_slider.setValue(y)

    def reset(self):
        self.c.set("floating_screen", "")
        self.monitor.setCurrentIndex(0)
        self.set_position(50, 90)

    def done(self, result):
        self.desktop_preview.setChecked(False)
        super().done(result)

"""Video / audio player page for the quick-preview lightbox.

Frames come through a QVideoSink and are painted here instead of using
QVideoWidget: since Qt 6.5 QVideoWidget embeds a native child window, which
would take keyboard focus from the lightbox (Up / Down / Esc) and break its
translucent backdrop.
"""

import logging

from PySide6.QtCore import QCoreApplication, QPoint, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

SEEK_STEP_MS = 5000


def _clock(ms: int) -> str:
    s = max(0, ms) // 1000
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class _VideoFrame(QWidget):
    """Paints the current frame scaled to fit (enlarged too, as video players do)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()

    def set_frame(self, frame: QVideoFrame) -> None:
        self._image = frame.toImage()
        self.update()

    def image(self) -> QImage:
        return self._image

    def _target(self) -> QRect:
        size = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRect(QPoint(0, 0), size)
        rect.moveCenter(self.rect().center())
        return rect

    def paintEvent(self, _event):
        if self._image.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self._target(), self._image)

    def mousePressEvent(self, event):
        # Clicks on the picture pause / resume; beside it they reach the backdrop and close.
        if self._image.isNull() or not self._target().contains(event.position().toPoint()):
            event.ignore()
        else:
            self.clicked.emit()


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, _event):
        self.clicked.emit()


class MediaView(QWidget):
    """Plays one file at a time with a play button and seek bar; `failed` carries a
    message for the user."""

    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(QAudioOutput(self))
        sink = QVideoSink(self)
        self._player.setVideoOutput(sink)

        self._frame = _VideoFrame()
        self._frame.clicked.connect(self.toggle)
        sink.videoFrameChanged.connect(self._frame.set_frame)
        note = _ClickLabel("♪")
        note.setObjectName("previewNote")
        note.clicked.connect(self.toggle)
        self._note_page = QWidget()
        QVBoxLayout(self._note_page).addWidget(note, 0, Qt.AlignmentFlag.AlignCenter)
        self._screen = QStackedWidget()
        self._screen.addWidget(self._frame)
        self._screen.addWidget(self._note_page)

        self._play_btn = QPushButton()
        self._play_btn.setObjectName("previewPlay")
        self._play_btn.clicked.connect(self.toggle)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("previewSeek")
        self._slider.setPageStep(SEEK_STEP_MS)
        self._slider.actionTriggered.connect(
            lambda _action: self._player.setPosition(self._slider.sliderPosition())
        )
        self._time = QLabel()
        self._time.setObjectName("previewDim")
        for w in (self._play_btn, self._slider):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keys stay with the lightbox
        bar = QWidget()
        bar.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)  # gaps don't close it
        controls = QHBoxLayout(bar)
        controls.setContentsMargins(0, 6, 0, 0)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._slider, 1)
        controls.addWidget(self._time)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._screen, 1)
        layout.addWidget(bar)

        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)
        self._on_state(QMediaPlayer.PlaybackState.StoppedState)
        # Destroying a player that still has a source deadlocks too, so let go of it
        # before the window is torn down on quit (main window closed mid-playback).
        QCoreApplication.instance().aboutToQuit.connect(self.stop)

    # --- Public ---

    def play(self, path: str, video: bool) -> None:
        self._screen.setCurrentWidget(self._frame if video else self._note_page)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def stop(self) -> None:
        # Clearing the source stops playback and releases the file. Not stop(): in Qt 6.11
        # the FFmpeg backend deadlocks when stop() comes right after a seek (Left / Right).
        self._player.setSource(QUrl())
        self._frame.set_frame(QVideoFrame())

    def toggle(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def seek_by(self, ms: int) -> None:
        position = self._player.position() + ms
        self._player.setPosition(max(0, min(self._player.duration(), position)))

    def player(self) -> QMediaPlayer:
        return self._player

    # --- Player signals ---

    def _on_duration(self, ms: int) -> None:
        self._slider.setRange(0, ms)
        self._on_position(self._player.position())

    def _on_position(self, ms: int) -> None:
        if not self._slider.isSliderDown():
            self._slider.setValue(ms)
        self._time.setText(f"{_clock(ms)} / {_clock(self._player.duration())}")

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("❚❚" if playing else "▶")
        self._play_btn.setToolTip("暫停（Enter）" if playing else "播放（Enter）")

    def _on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        log.warning("Cannot play %s: %s", self._player.source().toLocalFile(), message)
        self.failed.emit("無法播放這個檔案")

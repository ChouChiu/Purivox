from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from shared.i18n import tr
from shared.ui import (
    HeightForWidth,
    Lane,
    LayoutMetrics,
    LayoutMode,
    PageScrollArea,
    ResponsiveColumns,
)


class FeatureCard(HeightForWidth, CardWidget):
    def __init__(self, icon: FluentIcon, parent: QWidget | None = None):
        super().__init__(parent)
        self.setClickEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.icon = IconWidget(self)
        self.icon.setIcon(icon)
        self.icon.setFixedSize(36, 36)
        self.title = StrongBodyLabel(self)
        header.addWidget(self.icon)
        header.addWidget(self.title, 1)
        layout.addLayout(header)

        self.meta = CaptionLabel(self)
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)

        self.description = BodyLabel(self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.open_button = PrimaryPushButton(FluentIcon.RIGHT_ARROW, "", self)
        layout.addWidget(self.open_button)


class HomePage(PageScrollArea):
    mr_requested = Signal()
    ai_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        self.layout.setSpacing(20)

        self.brand = CaptionLabel("PURIVOX")
        self.title = TitleLabel()
        self.intro = BodyLabel()
        self.intro.setWordWrap(True)
        self.intro.setMaximumWidth(760)
        self.layout.addWidget(self.brand)
        self.layout.addWidget(self.title)
        self.layout.addWidget(self.intro)

        self.section_title = SubtitleLabel()
        self.section_hint = BodyLabel()
        self.section_hint.setWordWrap(True)
        self.layout.addSpacing(8)
        self.layout.addWidget(self.section_title)
        self.layout.addWidget(self.section_hint)

        # The two entry cards sit side by side wherever a line of prose fits
        # beside another, and stack only once the window is phone-narrow.
        self.cards = ResponsiveColumns(self.content)
        self.mr_card = FeatureCard(FluentIcon.MUSIC, self.cards)
        self.ai_card = FeatureCard(FluentIcon.MIX_VOLUMES, self.cards)
        self.cards.add(self.mr_card, Lane.PRIMARY)
        self.cards.add(self.ai_card, Lane.SECONDARY)
        self.cards.set_columns(2)
        self.layout.addWidget(self.cards)
        self.layout.addStretch()

        self.mr_card.clicked.connect(self.mr_requested.emit)
        self.ai_card.clicked.connect(self.ai_requested.emit)
        self.mr_card.open_button.clicked.connect(self.mr_requested.emit)
        self.ai_card.open_button.clicked.connect(self.ai_requested.emit)

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        self.cards.set_columns(1 if metrics.mode is LayoutMode.PORTRAIT else 2)
        self.cards.set_spacing(metrics.page_spacing)

    def retranslate(self) -> None:
        self.title.setText(tr("home_greeting"))
        self.intro.setText(tr("home_intro"))
        self.section_title.setText(tr("home_choose_title"))
        self.section_hint.setText(tr("home_choose_hint"))

        self.mr_card.title.setText(tr("nav_mr"))
        self.mr_card.meta.setText(tr("home_mr_meta"))
        self.mr_card.description.setText(tr("home_mr_description"))
        self.mr_card.open_button.setText(tr("home_open_mr"))

        self.ai_card.title.setText(tr("nav_ai"))
        self.ai_card.meta.setText(tr("home_ai_meta"))
        self.ai_card.description.setText(tr("home_ai_description"))
        self.ai_card.open_button.setText(tr("home_open_ai"))

        self.mr_card.setAccessibleName(self.mr_card.title.text())
        self.ai_card.setAccessibleName(self.ai_card.title.text())

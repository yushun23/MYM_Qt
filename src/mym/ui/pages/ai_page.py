"""AIPage – chat interface with action proposals and confirmation workflow."""

import json
import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

from mym.application.services.ai_service import (
    ActionProposal,
    AIService,
)
from mym.ui.widgets.canvas_renderer import CanvasRenderer
from mym.ui.widgets.attachment_handler import AttachmentHandler
from mym.domain.entities.ai_ import ChatMessage
from mym.ui.navigation import AppEventBus

logger = logging.getLogger(__name__)


class AIPage(QWidget):
    """AI assistant chat interface."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._current_session_id: int | None = None
        self._pending_proposals: dict[int, ActionProposal] = {}
        self._setup_ui()

    def _session(self):
        if self._session_factory:
            return self._session_factory()
        return None

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        # Left sidebar – session list
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)

        left_header = QHBoxLayout()
        new_btn = QPushButton("+ 新对话")
        new_btn.clicked.connect(self._on_new_session)
        left_header.addWidget(new_btn)

        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self._on_delete_session)
        left_header.addWidget(delete_btn)
        left.addLayout(left_header)

        self._session_list = QListWidget()
        self._session_list.currentRowChanged.connect(self._on_session_selected)
        left.addWidget(self._session_list)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(220)

        # Right side – chat area
        right = QVBoxLayout()

        # Privacy notice
        privacy = QLabel(
            "⚠️ 隐私提示: 通过AI发送的数据将发送给第三方模型提供商。"
            "请勿发送敏感个人信息。AI记账操作需要人工确认。"
        )
        privacy.setWordWrap(True)
        privacy.setStyleSheet(
            "background-color: #FFF3E0; color: #E65100; padding: 8px; "
            "border-radius: 4px; font-size: 12px;"
        )
        right.addWidget(privacy)

        # Attachment handler (P32)
        self._attachment_handler = AttachmentHandler()
        self._attachment_handler.content_ready.connect(self._on_attachment_ready)
        right.addWidget(self._attachment_handler)

        # Chat display
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setStyleSheet("font-size: 13px;")
        right.addWidget(self._chat_display)

        # Canvas area for analysis results (P31)
        self._canvas_area = QScrollArea()
        self._canvas_area.setWidgetResizable(True)
        self._canvas_area.setMaximumHeight(400)
        self._canvas_area.setVisible(False)
        self._canvas_widget = CanvasRenderer()
        self._canvas_area.setWidget(self._canvas_widget)
        right.addWidget(self._canvas_area)

        # Action proposal area
        self._action_frame = QFrame()
        self._action_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._action_frame.setVisible(False)
        action_layout = QVBoxLayout(self._action_frame)
        self._action_label = QLabel("建议操作:")
        self._action_label.setStyleSheet("font-weight: bold;")
        action_layout.addWidget(self._action_label)
        self._action_summary = QLabel("")
        action_layout.addWidget(self._action_summary)

        action_btns = QHBoxLayout()
        approve_btn = QPushButton("✓ 确认执行")
        approve_btn.setStyleSheet("QPushButton { background-color: #2E7D32; }")
        approve_btn.clicked.connect(self._on_approve_action)
        action_btns.addWidget(approve_btn)

        reject_btn = QPushButton("✗ 取消")
        reject_btn.setStyleSheet("QPushButton { background-color: #D32F2F; }")
        reject_btn.clicked.connect(self._on_reject_action)
        action_btns.addWidget(reject_btn)
        action_layout.addLayout(action_btns)
        right.addWidget(self._action_frame)

        # Input area
        input_row = QHBoxLayout()
        self._input_edit = QPlainTextEdit()
        self._input_edit.setMaximumHeight(100)
        self._input_edit.setPlaceholderText("输入你的问题... (回车发送, Shift+回车换行)")
        input_row.addWidget(self._input_edit)

        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)
        right.addLayout(input_row)

        right_widget = QWidget()
        right_widget.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([220, 600])

        layout.addWidget(splitter)

        # Install event filter for Enter key
        self._input_edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj == self._input_edit and event.type() == QEvent.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_Return
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def on_enter(self) -> None:
        self._load_sessions()

    def on_leave(self) -> None:
        pass

    def _load_sessions(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            sessions = svc.list_sessions()
            self._session_list.blockSignals(True)
            self._session_list.clear()
            for s in sessions:
                item = QListWidgetItem(s.title)
                item.setData(Qt.ItemDataRole.UserRole, s.id)
                self._session_list.addItem(item)
            if sessions:
                self._session_list.setCurrentRow(0)
            self._session_list.blockSignals(False)
        finally:
            session.close()

    def _on_new_session(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            chat = svc.create_session()
            session.commit()
            self._load_sessions()
        finally:
            session.close()

    def _on_delete_session(self) -> None:
        item = self._session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)

        reply = QMessageBox.question(
            self, "确认删除", "确定要删除该对话吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            svc.delete_session(session_id)
            session.commit()
            self._current_session_id = None
            self._chat_display.clear()
            self._load_sessions()
        finally:
            session.close()

    def _on_session_selected(self, row: int) -> None:
        if row < 0:
            return
        item = self._session_list.item(row)
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_session_id = session_id
        self._load_messages()

    def _load_messages(self) -> None:
        if not self._current_session_id:
            return
        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            messages = svc.get_messages(self._current_session_id)

            self._chat_display.clear()
            for msg in messages:
                role_label = {"user": "👤 你", "assistant": "🤖 AI", "system": "📋"}.get(
                    msg.role, msg.role
                )
                self._chat_display.append(f"**{role_label}:**\n{msg.content}\n")

            # Hide action frame if no pending action
            self._action_frame.setVisible(False)
        finally:
            session.close()

    def _on_send(self) -> None:
        text = self._input_edit.toPlainText().strip()
        if not text:
            return
        if not self._current_session_id:
            QMessageBox.information(self, "提示", "请先创建或选择一个对话")
            return

        self._input_edit.clear()

        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)

            # Add user message
            svc.add_message(self._current_session_id, "user", text)
            session.flush()

            # Check for action-intent keywords and generate a mock response
            response, proposal = self._mock_ai_response(text, svc)

            if proposal:
                msg = svc.add_message(
                    self._current_session_id, "assistant",
                    response, has_action_proposal=True,
                )
                msg.action_status = "pending"
                session.flush()
                self._pending_proposals[msg.id] = proposal
            else:
                svc.add_message(self._current_session_id, "assistant", response)

            session.commit()
            self._load_messages()

            if proposal:
                self._show_action_proposal(proposal)

        finally:
            session.close()

    def _mock_ai_response(
        self, user_text: str, svc: AIService
    ) -> tuple[str, ActionProposal | None]:
        """Generate a mock AI response for demo purposes.

        In production, this would call the actual AI API.
        """
        text_lower = user_text.lower()

        # Detect action intent
        if any(kw in text_lower for kw in ["记账", "记一笔", "支出", "收入", "消费", "花了"]):
            # Try to extract amount
            import re
            amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:元|块)?', text_lower)
            amt = amounts[0] if amounts else "100"

            return (
                f"我理解你想记录一笔交易。\n\n"
                f"建议操作: 记录一笔支出 ¥{amt}\n"
                f"请确认以下信息:\n"
                f"- 金额: ¥{amt}\n"
                f"- 分类: 餐饮\n"
                f"- 日期: 今天\n\n"
                f"请点击下方确认按钮执行。",
                ActionProposal(
                    action="add_transaction",
                    params={
                        "type": "expense",
                        "amount": amt,
                        "date": __import__("datetime").date.today().isoformat(),
                        "category": "餐饮",
                        "account": "现金",
                        "description": user_text,
                    },
                    risk_level=__import__("mym.domain.enums", fromlist=["ActionRiskLevel"]).ActionRiskLevel.MEDIUM,
                    summary=f"记录支出 ¥{amt}",
                ),
                None,
            )

        if any(kw in text_lower for kw in ["查询", "流水", "账单", "明细"]):
            return (
                "以下是最近的交易记录:\n\n"
                "【最近流水】\n"
                "1. 2025-07-01  餐饮  -¥35.00\n"
                "2. 2025-07-02  交通  -¥12.00\n"
                "3. 2025-07-03  工资  +¥5000.00\n\n"
                "如需更详细查询，请告诉我具体条件。",
                None,
                None,
                None,
            )

        if any(kw in text_lower for kw in ["总结", "汇总", "统计", "报表"]):
            return (
                f"📊 本月收支汇总:\n\n"
                f"收入: ¥5,000.00\n"
                f"支出: ¥2,350.00\n"
                f"结余: ¥2,650.00\n\n"
                f"主要支出:\n"
                f"- 餐饮 ¥1,200.00 (51%)\n"
                f"- 交通 ¥400.00 (17%)\n"
                f"- 购物 ¥750.00 (32%)",
                None,
                None,
                None,
            )

        return (
            "你好！我是MYM智能助手。我可以帮你:\n\n"
            "📝 **记账**: 说\"记一笔午餐50元\"\n"
            "📊 **查询**: 说\"查看本月流水\"\n"
            "📈 **汇总**: 说\"本月收支总结\"\n\n"
            "有什么我可以帮你的吗？",
            None,
            None,
        )

    def _show_action_proposal(self, proposal: ActionProposal) -> None:
        self._action_frame.setVisible(True)
        risk_labels = {
            "low": "🟢 低风险",
            "medium": "🟡 中风险",
            "high": "🔴 高风险",
        }
        self._action_label.setText(
            f"建议操作: {proposal.action} "
            f"({risk_labels.get(proposal.risk_level.value, proposal.risk_level.value)})"
        )
        self._action_summary.setText(proposal.summary)
        self._action_summary.setProperty("_pending_proposal", proposal)

    def _on_approve_action(self) -> None:
        # Get the current pending proposal
        if not self._pending_proposals:
            return

        # Find the pending proposal
        proposal = None
        msg_id = None
        for mid, prop in self._pending_proposals.items():
            proposal = prop
            msg_id = mid
            break

        if not proposal or not msg_id:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            result = svc.execute_action(proposal, self._current_session_id)

            if result.get("success"):
                svc.update_action_status(msg_id, "executed")
                svc.record_audit(proposal.action, proposal, result)
                svc.add_message(
                    self._current_session_id, "system",
                    f"✅ 已执行: {result.get('data', '')}",
                )
                AppEventBus.instance().ledger_changed.emit()
            else:
                svc.update_action_status(msg_id, "rejected")
                svc.add_message(
                    self._current_session_id, "system",
                    f"❌ 执行失败: {result.get('errors', [])}",
                )

            session.commit()
            del self._pending_proposals[msg_id]
            self._action_frame.setVisible(False)
            self._load_messages()
        finally:
            session.close()

    def _on_reject_action(self) -> None:
        if not self._pending_proposals:
            return

        msg_id = next(iter(self._pending_proposals))
        proposal = self._pending_proposals.pop(msg_id)

        session = self._session()
        if not session:
            return
        try:
            svc = AIService(session)
            svc.update_action_status(msg_id, "rejected")
            svc.add_message(
                self._current_session_id, "system",
                "⚠️ 操作已取消",
            )
            session.commit()
        finally:
            session.close()

        self._action_frame.setVisible(False)
        self._load_messages()

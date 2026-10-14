import uuid
import threading
from typing import Tuple, Optional, Dict, Any, List
from notifications.providers.base import BaseWhatsAppProvider


class MockWhatsAppProvider(BaseWhatsAppProvider):
    """
    Mock WhatsApp Provider for local development, testing, and CI.
    Records dispatched messages in a thread-safe registry and prints
    formatted previews to the application console.
    """
    _lock = threading.Lock()
    _sent_messages: List[Dict[str, Any]] = []

    def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        mock_wamid = f"wamid.mock.{uuid.uuid4().hex}"
        record = {
            'wamid': mock_wamid,
            'recipient_phone': recipient_phone,
            'message_text': message_text,
            'template_name': template_name,
            'context': context or {},
        }

        with self._lock:
            self._sent_messages.append(record)

        # Console notification preview
        print("\n=======================================================")
        print(f" [WHATSAPP DISPATCH - SENDER: 7039145304]")
        print(f" Recipient: {recipient_phone}")
        print(f" Template:  {template_name or 'Custom'}")
        print(f" WAMID:     {mock_wamid}")
        print(f" Body:\n{message_text.strip()}")
        print("=======================================================\n")

        return True, mock_wamid, None

    @classmethod
    def get_sent_messages(cls) -> List[Dict[str, Any]]:
        with cls._lock:
            return list(cls._sent_messages)

    @classmethod
    def clear_sent_messages(cls):
        with cls._lock:
            cls._sent_messages.clear()

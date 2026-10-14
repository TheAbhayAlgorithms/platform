import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from django.conf import settings

logger = logging.getLogger(__name__)

class WhatsAppProvider(ABC):
    """Abstract interface for sending WhatsApp messages & OTPs."""

    @abstractmethod
    def send_otp(self, phone: str, otp_code: str) -> bool:
        """Send a 6-digit OTP to a mobile number."""
        pass

    @abstractmethod
    def send_template_message(
        self, phone: str, template_name: str, parameters: Dict[str, Any]
    ) -> bool:
        """Send a pre-approved template message."""
        pass


class MockWhatsAppProvider(WhatsAppProvider):
    """
    Mock provider for local development and testing.
    Logs messages to logger and maintains an in-memory sent list for test assertions.
    """
    _sent_messages: List[Dict[str, Any]] = []

    def send_otp(self, phone: str, otp_code: str) -> bool:
        record = {
            'type': 'otp',
            'phone': phone,
            'otp_code': otp_code,
            'sender': getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304'),
        }
        self._sent_messages.append(record)
        logger.info(
            f"[MOCK WHATSAPP OTP] Sender: {record['sender']} -> To: {phone} | Code: {otp_code} | (Valid for 5 mins)"
        )
        print(f"\n[MOCK WHATSAPP OTP] To: {phone} | OTP: {otp_code}\n")
        return True

    def send_template_message(
        self, phone: str, template_name: str, parameters: Dict[str, Any]
    ) -> bool:
        record = {
            'type': 'template',
            'phone': phone,
            'template_name': template_name,
            'parameters': parameters,
            'sender': getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304'),
        }
        self._sent_messages.append(record)
        logger.info(
            f"[MOCK WHATSAPP TEMPLATE] Sender: {record['sender']} -> To: {phone} | Template: {template_name} | Params: {parameters}"
        )
        return True

    @classmethod
    def get_sent_messages(cls) -> List[Dict[str, Any]]:
        return cls._sent_messages

    @classmethod
    def clear_sent_messages(cls):
        cls._sent_messages.clear()

    @classmethod
    def get_last_otp(cls, phone: Optional[str] = None) -> Optional[str]:
        for msg in reversed(cls._sent_messages):
            if msg.get('type') == 'otp':
                if phone is None or msg.get('phone') == phone:
                    return msg.get('otp_code')
        return None


def get_whatsapp_provider() -> WhatsAppProvider:
    """Factory function returning active WhatsApp provider based on settings."""
    provider_name = getattr(settings, 'WHATSAPP_PROVIDER', 'mock').lower()
    if provider_name == 'mock':
        return MockWhatsAppProvider()
    # CloudAPIProvider will be fully wired in Phase 2 Module 9
    return MockWhatsAppProvider()

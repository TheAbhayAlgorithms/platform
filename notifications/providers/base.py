from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict, Any


class BaseWhatsAppProvider(ABC):
    """
    Abstract contract for WhatsApp messaging providers.
    All providers must implement send_message returning:
    (success: bool, external_message_id: str | None, error_message: str | None)
    """

    @abstractmethod
    def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        pass

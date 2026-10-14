import requests
from typing import Tuple, Optional, Dict, Any
from django.conf import settings
from notifications.providers.base import BaseWhatsAppProvider


class CloudAPIWhatsAppProvider(BaseWhatsAppProvider):
    """
    Production WhatsApp Cloud API Provider connecting to Meta Graph API.
    Dispatches notifications using the Institute sender number (7039145304).
    """

    def __init__(self):
        self.api_token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
        self.phone_number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
        self.api_version = getattr(settings, 'WHATSAPP_API_VERSION', 'v18.0')
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def send_message(
        self,
        recipient_phone: str,
        message_text: str,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        if not self.api_token or not self.phone_number_id:
            return (
                False,
                None,
                "WhatsApp Cloud API credentials (API Token or Phone Number ID) not configured."
            )

        # Meta expects recipient phone in digits without '+' prefix (e.g. 919876543210)
        clean_phone = recipient_phone.replace('+', '').replace(' ', '').replace('-', '').strip()

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message_text.strip()
            }
        }

        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=10
            )
            data = response.json()

            if response.status_code in [200, 201] and 'messages' in data:
                wamid = data['messages'][0].get('id')
                return True, wamid, None
            else:
                error_info = data.get('error', {}).get('message', response.text)
                return False, None, f"Meta API Error ({response.status_code}): {error_info}"

        except requests.RequestException as e:
            return False, None, f"Network error connecting to WhatsApp Cloud API: {str(e)}"

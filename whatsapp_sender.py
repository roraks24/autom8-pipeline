#!/usr/bin/env python3
"""
whatsapp_sender.py (Facade) - WhatsApp notification dispatcher.

Forwards to modular package implementation in src.notifications.whatsapp.
"""

import argparse
import sys

from src.notifications.whatsapp import (
    DEFAULT_CONFIG,
    is_whatsapp_web_ready,
    load_config,
    login_interactive,
    normalize_phone,
    save_config,
    send_via_callmebot,
    send_via_desktop_uri,
    send_via_whatsapp_web,
    send_whatsapp,
)

__all__ = [
    "send_whatsapp",
    "send_via_whatsapp_web",
    "send_via_callmebot",
    "send_via_desktop_uri",
    "login_interactive",
    "is_whatsapp_web_ready",
    "load_config",
    "save_config",
    "normalize_phone",
    "DEFAULT_CONFIG",
]


def main():
    parser = argparse.ArgumentParser(description="WhatsApp message dispatcher")
    parser.add_argument("--login", action="store_true", help="Launch browser for 1-time WhatsApp Web QR scan")
    parser.add_argument("--test", action="store_true", help="Send test message")
    parser.add_argument("--phone", type=str, default="7877169982", help="Recipient phone number (e.g. 7877169982 or 8854905995)")
    parser.add_argument("--msg", type=str, default="🤖 Test dispatch from Antigravity Job Automator!", help="Custom message to send")
    parser.add_argument("--callmebot-key", type=str, help="Set CallMeBot API key")
    args = parser.parse_args()

    cfg = load_config()

    if args.callmebot_key:
        cfg["callmebot_api_key"] = args.callmebot_key
        save_config(cfg)
        print(f"Saved CallMeBot API key: {args.callmebot_key}")

    if args.login:
        login_interactive()
    elif args.test:
        print(f"Sending test message to {args.phone}...")
        res = send_whatsapp(args.msg, phone=args.phone)
        print(f"Result: {'Success' if res else 'Failed'}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

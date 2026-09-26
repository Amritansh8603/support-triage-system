"""Seed knowledge base articles. In a real system these would be pulled
from Zendesk/Confluence/a help-center CMS and embedded with a real model.
"""

ARTICLES = [
    {
        "id": "kb-001",
        "category": "billing",
        "title": "How refunds are processed",
        "content": (
            "Refunds are issued to the original payment method within 5-10 "
            "business days after approval. You can request a refund from "
            "Account > Billing > Order History > Request Refund."
        ),
    },
    {
        "id": "kb-002",
        "category": "billing",
        "title": "Understanding a duplicate or double charge",
        "content": (
            "Duplicate charges are usually a temporary authorization hold, "
            "not a real second charge, and drop off within 3-5 business "
            "days. If both charges settle, contact billing support with "
            "both transaction IDs for a manual reversal."
        ),
    },
    {
        "id": "kb-003",
        "category": "billing",
        "title": "Cancelling a subscription",
        "content": (
            "Subscriptions can be cancelled anytime from Account > "
            "Subscription > Cancel Plan. Cancellation takes effect at the "
            "end of the current billing period; no partial refunds are "
            "issued for unused days unless required by local law."
        ),
    },
    {
        "id": "kb-004",
        "category": "technical",
        "title": "App crashes on startup",
        "content": (
            "Startup crashes are most often caused by a corrupted local "
            "cache. Clear the app cache via Settings > Storage > Clear "
            "Cache, then restart. If it persists, reinstall the app and "
            "collect the crash log from Settings > About > Diagnostics."
        ),
    },
    {
        "id": "kb-005",
        "category": "technical",
        "title": "Sync issues between devices",
        "content": (
            "Data sync relies on a background service that requires an "
            "active internet connection and being signed into the same "
            "account on all devices. Force a manual sync from Settings > "
            "Sync Now, and check that battery-optimization settings are "
            "not pausing background sync on mobile."
        ),
    },
    {
        "id": "kb-006",
        "category": "technical",
        "title": "Two-factor authentication reset",
        "content": (
            "If you've lost access to your 2FA device, use one of your "
            "backup codes to sign in, then re-enroll a new device from "
            "Security > Two-Factor Authentication. Without a backup code, "
            "identity verification is required before we can disable 2FA."
        ),
    },
    {
        "id": "kb-007",
        "category": "account",
        "title": "Changing the email on your account",
        "content": (
            "You can change your account email from Account > Profile > "
            "Email Address. A verification link is sent to the new address "
            "and the change only takes effect once it's confirmed."
        ),
    },
    {
        "id": "kb-008",
        "category": "account",
        "title": "Account locked after failed logins",
        "content": (
            "Accounts are temporarily locked for 30 minutes after 5 failed "
            "login attempts as an anti-abuse measure. You can also reset "
            "your password immediately via the 'Forgot password' link to "
            "regain access without waiting."
        ),
    },
    {
        "id": "kb-009",
        "category": "shipping",
        "title": "Tracking a delayed order",
        "content": (
            "Tracking numbers can take up to 24 hours to update after a "
            "carrier scan. If tracking hasn't moved in 5+ business days, "
            "the shipment may be lost in transit and qualifies for a "
            "reshipment or refund."
        ),
    },
    {
        "id": "kb-010",
        "category": "shipping",
        "title": "Changing a shipping address after ordering",
        "content": (
            "Shipping addresses can only be changed while an order is in "
            "'Processing' status. Once an order moves to 'Shipped', the "
            "address is locked and the carrier must be contacted directly "
            "for redirection where supported."
        ),
    },
    {
        "id": "kb-011",
        "category": "general",
        "title": "Contacting a human support agent",
        "content": (
            "If self-service options don't resolve your issue, you can "
            "reach a human agent via live chat (9am-9pm) or by emailing "
            "support@example.com; typical first response time is under 4 "
            "business hours."
        ),
    },
    {
        "id": "kb-012",
        "category": "security",
        "title": "Reporting a suspected security vulnerability",
        "content": (
            "Suspected vulnerabilities or data exposure should be reported "
            "immediately to security@example.com and are handled by the "
            "security response team outside normal support queues, with an "
            "initial acknowledgement within 1 business hour."
        ),
    },
]

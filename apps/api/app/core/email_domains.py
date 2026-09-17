"""Which email providers may be used to register.

Registration is limited to Russian email services. Basis: Federal Law 406-FZ of
31.07.2023 (amending art. 10 of 149-FZ), which since 01.01.2025 forbids registering
on Russian sites through a foreign mailbox.

The site's registration form (``VOIDRP-SITE/src/views/RegisterView.vue``) has the same
list for instant feedback while typing — keep the two in sync. This copy is the one
that actually decides: the form can be bypassed, this cannot, and it also covers
registration from inside the game.
"""

from __future__ import annotations

ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        # mail.ru group
        "mail.ru",
        "bk.ru",
        "inbox.ru",
        "list.ru",
        "internet.ru",
        "mail.ua",
        # yandex
        "yandex.ru",
        "ya.ru",
        "yandex.com",
        "yandex.by",
        "yandex.kz",
        "yandex.ua",
        # rambler group
        "rambler.ru",
        "lenta.ru",
        "autorambler.ru",
        "myrambler.ru",
        "ro.ru",
        "rambler.ua",
        # прочие российские провайдеры
        "vk.com",
        "xmail.ru",
    }
)

EMAIL_DOMAIN_ERROR = (
    "Регистрация доступна только с российских почтовых сервисов "
    "(mail.ru, yandex.ru, bk.ru, rambler.ru и другие)."
)


def is_allowed_email(email: str | None) -> bool:
    if not email:
        return False
    at = email.strip().lower().rfind("@")
    if at < 0:
        return False
    return email.strip().lower()[at + 1 :] in ALLOWED_EMAIL_DOMAINS

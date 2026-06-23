from __future__ import annotations

from typing import Any

_EXACT_MESSAGES: dict[str, str] = {
    "User registered successfully. Email verification has been requested.": "Аккаунт создан. Мы отправили письмо для подтверждения почты.",
    "Email has been verified successfully.": "Почта успешно подтверждена.",
    "If the account exists and email is not verified, a new verification token has been issued.": "Если аккаунт существует и почта ещё не подтверждена, мы отправили новое письмо для подтверждения.",
    "If the account exists, a password reset token has been issued.": "Если аккаунт существует, мы отправили письмо для смены пароля.",
    "Password has been reset successfully.": "Пароль успешно изменён.",
    "Other active sessions revoked successfully.": "Другие активные входы завершены.",
    "Avatar uploaded successfully.": "Аватар успешно загружен.",
    "Banner uploaded successfully.": "Баннер успешно загружен.",
    "Background uploaded successfully.": "Фон успешно загружен.",
    "Avatar removed successfully.": "Аватар удалён.",
    "Banner removed successfully.": "Баннер удалён.",
    "Background removed successfully.": "Фон удалён.",
    "Follow created successfully.": "Подписка оформлена.",
    "Follow removed successfully.": "Подписка удалена.",
    "Nation leave action completed.": "Ты вышел из государства.",
    "Legacy settings have been updated.": "Настройки старого входа обновлены.",
    "Invalid game auth secret": "Недействительный служебный ключ игры.",
    "Invalid admin api secret": "Недействительный административный ключ.",
    "Invalid access token payload": "Сессия входа повреждена. Войди снова.",
    "Invalid or expired access token": "Сессия истекла. Войди снова.",
    "User is not available": "Аккаунт сейчас недоступен. Войди снова или обратись к администрации.",
    "Invalid token type": "Сессия входа недействительна. Войди снова.",
    "unsupported slot": "Неизвестный тип изображения.",
    "target profile was not found": "Профиль игрока не найден.",
    "you cannot follow yourself": "Нельзя подписаться на самого себя.",
    "player account is not linked": "Игровой профиль не привязан к аккаунту.",
    "play ticket is invalid": "Сессия входа недействительна. Запусти игру через лаунчер ещё раз.",
    "play ticket is already used": "Эта сессия входа уже использована. Запусти игру через лаунчер ещё раз.",
    "play ticket is expired": "Сессия входа истекла. Запусти игру через лаунчер ещё раз.",
    "player name does not match play ticket": "Ник игрока не совпадает с данными лаунчера.",
    "ticket user is not available": "Аккаунт игрока недоступен. Обратись к администрации.",
    "target referral code was not found": "Код приглашения не найден.",
    "nation member was not found": "Участник государства не найден.",
    "leader role cannot be changed here": "Роль лидера нельзя менять этим действием.",
    "leader cannot be removed from nation": "Лидера нельзя удалить из государства этим действием.",
    "not enough permissions to manage nation": "Недостаточно прав для управления государством.",
    "officer cannot change another officer role": "Офицер не может менять роль другого офицера.",
    "officer cannot remove another officer": "Офицер не может удалить другого офицера.",
    "only leader can transfer leadership": "Передавать лидерство может только лидер.",
    "leadership is already assigned to this user": "Лидерство уже назначено этому игроку.",
    "Member role updated successfully.": "Роль участника обновлена.",
    "Member removed successfully.": "Участник удалён из государства.",
    "Leadership transferred successfully.": "Лидерство передано.",
    "nation slug is too short": "Адрес страницы государства слишком короткий.",
    "not enough balance to create nation": "Для создания государства нужно минимум 300 000. Баланс игрока меньше или ещё не синхронизирован с сервером.",
    "nation is founder of alliance with other members": "Нельзя расформировать государство, пока оно является основателем альянса с другими участниками. Сначала распусти альянс или выйди из него.",
    "Nation disbanded successfully.": "Государство расформировано.",
}

_CONTAINS_RULES: list[tuple[str, str]] = [
    ("site login is already taken", "Этот логин уже занят."),
    ("email is already registered", "На эту почту уже зарегистрирован аккаунт."),
    ("minecraft nickname is already taken", "Этот игровой ник уже занят."),
    ("invalid login or password", "Неверный логин или пароль."),
    ("invalid credentials", "Неверный логин или пароль."),
    ("refresh token is invalid", "Сессия входа недействительна. Войди снова."),
    ("refresh token is expired", "Сессия входа истекла. Войди снова."),
    ("refresh token is revoked", "Сессия входа завершена. Войди снова."),
    ("invalid or expired access token", "Сессия истекла. Войди снова."),
    ("invalid access token payload", "Сессия входа повреждена. Войди снова."),
    ("invalid token type", "Сессия входа недействительна. Войди снова."),
    ("user is not available", "Аккаунт сейчас недоступен. Войди снова или обратись к администрации."),
    ("email is already verified", "Почта уже подтверждена."),
    ("email verification token is invalid", "Ссылка для подтверждения почты недействительна."),
    ("email verification token is expired", "Срок действия ссылки для подтверждения почты истёк."),
    ("password reset token is invalid", "Ссылка для смены пароля недействительна."),
    ("password reset token is expired", "Срок действия ссылки для смены пароля истёк."),
    ("token is invalid", "Токен недействителен."),
    ("token is expired", "Срок действия токена истёк."),
    ("slug is already taken", "Этот адрес страницы уже занят."),
    ("profile was not found", "Профиль игрока не найден."),
    ("public profile was not found", "Публичный профиль не найден."),
    ("nation was not found", "Государство не найдено."),
    ("nation is not public", "Это государство сейчас недоступно для просмотра."),
    ("already in a nation", "Ты уже состоишь в государстве."),
    ("already has a nation", "У тебя уже есть государство."),
    ("already sent a join request", "Заявка на вступление уже отправлена."),
    ("join request was not found", "Заявка на вступление не найдена."),
    ("cannot join your own nation", "Нельзя вступить в собственное государство."),
    ("recruitment is closed", "Сейчас вступление в это государство недоступно."),
    ("invite only", "Вступление возможно только по приглашению."),
    ("not enough permissions", "Недостаточно прав для этого действия."),
    ("only leader can", "Это действие доступно только лидеру."),
    ("only officers or leader", "Это действие доступно только офицеру или лидеру."),
    ("already follows", "Ты уже подписан на этого игрока."),
    ("unsupported content type", "Неподдерживаемый тип файла."),
    ("file is too large", "Файл слишком большой."),
    ("image is too small", "Изображение слишком маленькое."),
    ("image width is too small", "Изображение слишком узкое."),
    ("image height is too small", "Изображение слишком низкое."),
    ("image width is too large", "Изображение слишком широкое."),
    ("image height is too large", "Изображение слишком высокое."),
    ("invalid image", "Не удалось обработать изображение. Проверь файл и попробуй снова."),
    ("unsupported slot", "Неизвестный тип изображения."),
    ("legacy auth is disabled", "Для этого аккаунта вход по старому паролю отключён."),
    ("legacy account was not found", "Старый аккаунт не найден."),
    ("legacy password is invalid", "Неверный пароль старого входа."),
    ("player name is invalid", "Некорректный ник игрока."),
    ("player is not allowed to use legacy auth", "Для этого аккаунта нужен вход через официальный лаунчер VoidRP."),
    ("referral code was not found", "Код приглашения не найден."),
    ("referral preview was not found", "Код приглашения не найден."),
]

_FIELD_LABELS: dict[str, str] = {
    "site_login": "логин",
    "minecraft_nickname": "игровой ник",
    "email": "почта",
    "password": "пароль",
    "password_repeat": "повтор пароля",
    "login": "логин или почта",
    "device_name": "устройство",
    "token": "токен",
    "refresh_token": "сессионный ключ",
    "new_password": "новый пароль",
    "new_password_repeat": "повтор нового пароля",
    "referral_code": "код приглашения",
    "slug": "адрес страницы",
    "title": "название",
    "tag": "тег",
    "short_description": "краткое описание",
    "description": "описание",
    "display_name": "отображаемое имя",
    "bio": "описание",
    "status_text": "статус",
    "theme_mode": "тема",
    "accent_color": "цвет",
    "recruitment_policy": "тип вступления",
    "is_public": "публичная страница",
    "allow_followers_list_public": "видимость подписчиков",
    "allow_friends_list_public": "видимость друзей",
    "allow_profile_comments": "комментарии профиля",
    "alliance_slug": "альянс",
    "alliance_type": "тип альянса",
    "proposal_type": "тип предложения",
    "payload_json": "дополнительные параметры",
    "policy_flags_json": "дополнительные настройки",
    "transfer_fee_percent": "комиссия перевода",
    "allow_internal_transfers": "внутренние переводы",
    "allow_joint_defense": "совместная защита",
    "allow_trade_bonus": "торговый бонус",
    "allow_pvp_protection": "защита PvP",
    "from_nation_slug": "государство-отправитель",
    "to_nation_slug": "государство-получатель",
    "amount": "сумма",
    "comment": "комментарий",
    "role": "роль",
    "target_user_id": "участник",
    "vote": "голос",
    "leader_minecraft_nickname": "ник лидера",
    "officers": "офицеры",
    "members": "участники",
}


def humanize_field_name(field_name: str | None) -> str:
    key = str(field_name or "").strip()
    if not key:
        return "поле"
    return _FIELD_LABELS.get(key, key.replace("_", " "))



def translate_user_message(message: str | None) -> str:
    text = str(message or "").strip()
    if not text:
        return "Не удалось выполнить действие. Попробуй ещё раз."

    translated = _EXACT_MESSAGES.get(text)
    if translated:
        return translated

    lowered = text.lower()
    for needle, replacement in _CONTAINS_RULES:
        if needle in lowered:
            return replacement

    return text



def translate_validation_message(field_name: str | None, message: str | None, ctx: dict[str, Any] | None = None) -> str:
    text = str(message or "").strip()
    if not text:
        return f"Проверь поле «{humanize_field_name(field_name)}»."

    direct = translate_user_message(text)
    if direct != text:
        return direct

    lowered = text.lower()
    label = humanize_field_name(field_name)
    ctx = ctx or {}

    if lowered == "field required":
        return f"Заполни поле «{label}»."

    if "should have at least" in lowered:
        minimum = ctx.get("min_length") or ctx.get("ge")
        if minimum is not None:
            return f"Поле «{label}» должно содержать минимум {minimum} символов."
        return f"Поле «{label}» заполнено слишком коротко."

    if "should have at most" in lowered:
        maximum = ctx.get("max_length") or ctx.get("le")
        if maximum is not None:
            return f"Поле «{label}» должно содержать не больше {maximum} символов."
        return f"Поле «{label}» заполнено слишком длинно."

    if "valid email address" in lowered:
        return "Укажи корректную почту."

    if "valid string" in lowered:
        return f"Поле «{label}» заполнено некорректно."

    if "greater than or equal to" in lowered:
        minimum = ctx.get("ge")
        if minimum is not None:
            return f"Поле «{label}» должно быть не меньше {minimum}."

    if "less than or equal to" in lowered:
        maximum = ctx.get("le")
        if maximum is not None:
            return f"Поле «{label}» должно быть не больше {maximum}."

    if "input should be greater than" in lowered:
        return f"Поле «{label}» должно быть больше нуля."

    return f"Проверь поле «{label}»: {text}"



def format_validation_errors(errors: list[dict[str, Any]] | None) -> str:
    if not errors:
        return "Проверь заполненные поля и попробуй снова."

    messages: list[str] = []
    for item in errors:
        loc = item.get("loc") or []
        field_name = None
        for part in reversed(loc):
            if isinstance(part, str) and part not in {"body", "query", "path", "header"}:
                field_name = part
                break

        message = translate_validation_message(field_name, item.get("msg"), item.get("ctx"))
        if message not in messages:
            messages.append(message)

    if not messages:
        return "Проверь заполненные поля и попробуй снова."

    if len(messages) == 1:
        return messages[0]

    preview = "; ".join(messages[:3])
    if len(messages) > 3:
        preview += f". Ещё ошибок: {len(messages) - 3}."
    return preview



def localize_response_message(response: Any) -> Any:
    if response is None:
        return response
    message = getattr(response, "message", None)
    if isinstance(message, str) and message.strip():
        try:
            response.message = translate_user_message(message)
        except Exception:
            pass
    return response



def localize_player_access_error(value: str | None) -> str | None:
    if value is None:
        return None
    return translate_user_message(value)

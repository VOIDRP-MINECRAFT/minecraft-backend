"""Current editions of the legal documents a user accepts, and the kinds of data a user may
allow to be shown publicly.

Bump a version when the text of the document changes in a way that needs a fresh consent:
users whose latest record is for an older version are asked again on the site.
"""
from __future__ import annotations

DOC_OFFER = "offer"
DOC_PERSONAL_DATA = "personal_data"
DOC_DISTRIBUTION = "distribution"

LEGAL_VERSIONS: dict[str, str] = {
    DOC_OFFER: "2026-09-17",
    DOC_PERSONAL_DATA: "2026-09-17",
    DOC_DISTRIBUTION: "2026-09-17",
}

# Documents without which the account cannot be used.
REQUIRED_DOCUMENTS = (DOC_OFFER, DOC_PERSONAL_DATA)

# Consent to make personal data public (art. 10.1 of 152-FZ), per category. Nickname and in-game
# activity visible to other players are part of the multiplayer service itself (the offer), not
# a separate distribution.
DISTRIBUTION_PROFILE = "profile"      # public profile page: name, bio, status, images, social links
DISTRIBUTION_MAP = "map"              # live position on the public world map while online
DISTRIBUTION_PURCHASES = "purchases"  # nickname next to purchases and in the top supporters list
DISTRIBUTION_CATEGORIES = (DISTRIBUTION_PROFILE, DISTRIBUTION_MAP, DISTRIBUTION_PURCHASES)

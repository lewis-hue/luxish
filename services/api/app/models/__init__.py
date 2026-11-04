"""Model registry.

Importing this package registers every table on ``Base.metadata`` — which is
what makes ``create_all`` (tests) and Alembic autogenerate see a complete
schema. One module per domain (ADR-003).
"""

from __future__ import annotations

from app.models.ai_run import AIRun
from app.models.account_export import AccountExport
from app.models.piece_packshot import PiecePackshot
from app.models.post_vision import PostVisionRow
from app.models.cohort_inspiration import CohortInspiration
from app.models.avatar_render import AvatarRender
from app.models.consent import Consent
from app.models.direct_message import (
    DirectMessage,
    DirectThread,
    DirectThreadMember,
)
from app.models.external_reference import ExternalReference
from app.models.garment import Collection, CollectionGarment, Garment
from app.models.garment_studio import GarmentShot
from app.models.identity import ExternalIdentity, IdentityLinkChallenge
from app.models.job import Job
from app.models.media_asset import MediaAsset, MediaDerivative
from app.models.moodboard import Moodboard, MoodboardPin
from app.models.outfit_plan import OutfitPlan, OutfitPlanItem
from app.models.preference import Preference
from app.models.push import DeviceToken, PushOutbox
from app.models.provider_connection import ProviderConnection
from app.models.regional_profile import RegionalStyleProfile
from app.models.session import RevokedToken, Session
from app.models.stylist import (
    Conversation,
    Message,
    Outfit,
    OutfitFeedback,
    OutfitItem,
    StylistRun,
)
from app.models.billing import Subscription
from app.models.brand_story import BrandStory
from app.models.comment import PostComment
from app.models.fit_description import FitDescriptionRow
from app.models.gifts import CreditLedgerEntry
from app.models.moderation import Block, Report
from app.models.profile import PostReaction, PostTag, Profile
from app.models.posts import Post, PostHide, PostItem, PostMedia, PostSave
from app.models.shopping import Offer, Retailer, ShopProduct
from app.models.tombstone import Tombstone
from app.models.follow import Follow
from app.models.usage import UsageReservation
from app.models.user import User
from app.models.user_cohort import UserCohort

__all__ = [
    "AIRun",
    "AccountExport",
    "PiecePackshot",
    "PostVisionRow",
    "AvatarRender",
    "BrandStory",
    "CohortInspiration",
    "Collection",
    "CollectionGarment",
    "Consent",
    "DirectMessage",
    "DirectThread",
    "DirectThreadMember",
    "Conversation",
    "ExternalIdentity",
    "ExternalReference",
    "FitDescriptionRow",
    "Garment",
    "GarmentShot",
    "IdentityLinkChallenge",
    "Job",
    "MediaAsset",
    "Moodboard",
    "MoodboardPin",
    "MediaDerivative",
    "Message",
    "Outfit",
    "OutfitPlan",
    "OutfitPlanItem",
    "OutfitFeedback",
    "OutfitItem",
    "DeviceToken",
    "Preference",
    "PushOutbox",
    "ProviderConnection",
    "Offer",
    "PostReaction",
    "PostTag",
    "Profile",
    "Post",
    "PostComment",
    "PostHide",
    "PostItem",
    "PostMedia",
    "PostSave",
    "RegionalStyleProfile",
    "Retailer",
    "ShopProduct",
    "RevokedToken",
    "Session",
    "Block",
    "CreditLedgerEntry",
    "Report",
    "StylistRun",
    "Subscription",
    "Tombstone",
    "Follow",
    "UsageReservation",
    "User",
    "UserCohort",
]

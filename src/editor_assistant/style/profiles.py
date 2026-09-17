"""M2.2 StyleProfile contract - stdlib only, no network, no Radar.

Profiles are plain JSON-serializable dicts validated by validate_profile.
No numeric confidence scores (spec forbids fake confidence).
Status is PROVEN (n>=20 + distinguishable + useful) or PROVISIONAL.
Retrieval fallback for M2.3: requested profile -> category/story
profile -> house profile. Never mix unrelated authors to fill context.
"""

from __future__ import annotations

REQUIRED_TOP = (
    "profile_id",
    "display_name",
    "scope",
    "status",
    "sample_size",
    "source_authors",
    "source_categories",
    "preferred_use",
    "site_dna_inherited",
    "headline",
    "opening",
    "body",
    "quotes",
    "tone",
    "numbers_dates",
    "lexical_notes",
    "avoidances",
    "example_article_ids",
    "evidence_notes",
)
OPTIONAL_TOP = ("kind", "style_language", "corpus_snapshot")
VALID_KINDS = ("voice", "story_mode")
FROZEN_VOICES = ("VOICE_HOUSE", "VOICE_DESISLAVA_RECENT")
FROZEN_MODES = ("MODE_STANDARD_NEWS", "MODE_BRIEF", "MODE_EVENT_PREVIEW", "MODE_CULTURE_FEATURE")
PROFILE_VERSION = "m2.2-freeze-1"
REQUIRED_HEADLINE = ("typical_length", "common_patterns", "avoid")
REQUIRED_OPENING = ("typical_patterns",)
REQUIRED_BODY = ("paragraph_shape", "sentence_shape", "pacing", "structure")
REQUIRED_QUOTES = ("frequency", "placement", "integration")
REQUIRED_TONE = ("factual_vs_descriptive", "narrative_distance", "local_specificity")
REQUIRED_NUMBERS = ("conventions",)
REQUIRED_LEXICAL = ("recurring_preferences",)
VALID_STATUS = ("PROVEN", "PROVISIONAL")
FALLBACK_ORDER = ("requested_profile", "category_story_profile", "house_profile")


class ProfileError(ValueError):
    pass


def _need(mapping, keys, where):
    for key in keys:
        if key not in mapping:
            raise ProfileError(f"{where} missing key: {key}")


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ProfileError("profile must be a dict")
    _need(profile, REQUIRED_TOP, "profile")
    if profile["status"] not in VALID_STATUS:
        raise ProfileError(f"bad status: {profile['status']!r}")
    n = profile["sample_size"]
    if not isinstance(n, int) or n < 1:
        raise ProfileError("sample_size must be a positive int")
    if profile["status"] == "PROVEN" and n < 20:
        raise ProfileError("PROVEN requires sample_size >= 20")
    if not profile["example_article_ids"] or len(profile["example_article_ids"]) < 3:
        raise ProfileError("need >=3 example_article_ids")
    _need(profile["headline"], REQUIRED_HEADLINE, "headline")
    _need(profile["opening"], REQUIRED_OPENING, "opening")
    _need(profile["body"], REQUIRED_BODY, "body")
    _need(profile["quotes"], REQUIRED_QUOTES, "quotes")
    _need(profile["tone"], REQUIRED_TONE, "tone")
    _need(profile["numbers_dates"], REQUIRED_NUMBERS, "numbers_dates")
    _need(profile["lexical_notes"], REQUIRED_LEXICAL, "lexical_notes")
    if not isinstance(profile["avoidances"], list) or not profile["avoidances"]:
        raise ProfileError("avoidances must be a non-empty list")
    kind = profile.get("kind")
    if kind is not None and kind not in VALID_KINDS:
        raise ProfileError(f"bad kind: {kind!r}")
    for text_key in ("display_name", "scope", "preferred_use"):
        text = profile.get(text_key, "")
        if isinstance(text, str) and ("must " in text or "always " in text):
            raise ProfileError(f"{text_key} uses hard-rule language")
    return True


def compose_draft_spec(voice_id, mode_id, *, voices=FROZEN_VOICES, modes=FROZEN_MODES):
    """Validate one M2.3 draft composition: SITE DNA + VOICE + STORY MODE."""
    if voice_id not in voices:
        raise ProfileError(f"unknown voice: {voice_id!r}")
    if mode_id not in modes:
        raise ProfileError(f"unknown story mode: {mode_id!r}")
    return {"site_dna": "CHERNOMORIE_SITE_DNA", "voice": voice_id, "mode": mode_id}


def composition_fallback(
    voice_id, mode_id, *, house_voice="VOICE_HOUSE", default_mode="MODE_STANDARD_NEWS"
):
    """M2.3 retrieval order: VOICE+MODE -> same MODE other voice -> house default."""
    chain = [(voice_id, mode_id)]
    if voice_id != house_voice:
        chain.append((house_voice, mode_id))
    if (house_voice, default_mode) not in chain:
        chain.append((house_voice, default_mode))
    return [{"site_dna": "CHERNOMORIE_SITE_DNA", "voice": v, "mode": m} for v, m in chain]


def validate_site_dna(dna):
    if not isinstance(dna, dict):
        raise ProfileError("site DNA must be a dict")
    for key in (
        "profile_id",
        "display_name",
        "scope",
        "conventions",
        "evidence_notes",
        "corpus_snapshot",
    ):
        if key not in dna:
            raise ProfileError(f"site DNA missing key: {key}")
    if not isinstance(dna["conventions"], dict) or not dna["conventions"]:
        raise ProfileError("site DNA conventions must be a non-empty dict")
    return True


def retrieval_fallback(
    requested_id, available_ids, *, house_id="VOICE_HOUSE"
):  # legacy flat-profile helper, kept for compat
    chain = []
    if requested_id in available_ids:
        chain.append(requested_id)
    for pid in available_ids:
        if pid not in chain and pid != house_id:
            chain.append(pid)
            break
    if house_id in available_ids and house_id not in chain:
        chain.append(house_id)
    return chain

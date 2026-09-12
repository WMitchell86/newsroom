"""Live source identity (M1.2). Test fixture sources stay in tests/ — fixtures are
evidence, not production configuration."""

from editor_assistant.models import SourceDef
from editor_assistant.sources.rss import PARSER_ID

BURGAS_MUNICIPAL_COUNCIL = SourceDef(
    source_id="burgas-municipal-council",
    canonical_url="https://burgascouncil.org/",
    parser=PARSER_ID,
)
LIVE_FEED_URL = "https://burgascouncil.org/last-update.xml"

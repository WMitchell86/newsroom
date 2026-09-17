# M2.4 — Evidence Packet

## Goal

Create a strict factual packet for one current story.

```text
current source material
→ deterministic extraction
→ evidence normalization
→ EvidencePacket
```

This packet becomes the only factual authority for draft generation.

## Start with one source type

Use one approved source type first:
- official RSS item
- official press release
- uploaded press email
- official document text

## EvidencePacket contract

```yaml
story_id:
source_ids:
source_urls:
observed_at:
headline_source:
facts:
people:
organizations:
places:
dates:
numbers:
quotes:
documents:
unknowns:
editor_notes:
```

## Provenance

Every material fact should map to source id + source span/field.

## Quotes

Quotes must be verbatim. If speaker role is not explicit, leave it None.

## Numbers/dates

Preserve source form; never silently correct suspicious values.

## Unknowns

Track UNKNOWN / AMBIGUOUS / MISSING explicitly.

## Evidence audit

For 10 packets, manually verify every name, number, date, quote, institution, and link against source.

Target: 0 invented fields.

## Verification Gate

PASS only if:
- packet contract stable
- facts traceable
- unknowns preserved
- quotes verbatim
- 10-packet audit completed
- no archive contamination
- no draft generation yet

Then STOP.

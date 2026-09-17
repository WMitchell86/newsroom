# M2.3 — Style Retrieval

## Goal

Given a new story context, retrieve 3–5 published Chеrnomorie articles useful as style references.

No draft generation yet.

## Core rule

Retrieved archive articles are style references only and must not become factual evidence for the current story.

## Retrieval input

```text
category
author/profile target
location
story_type
topic_terms
desired_length
```

## Retrieval stages

Prefer:

```text
hard filters
→ lexical/metadata match
→ optional semantic rerank
```

Start simple. No embeddings unless clearly necessary.

## Ranking

Use inspectable factors such as:
- category
- topic overlap
- location
- article type
- length similarity

## Diversity

Avoid returning five near-identical examples.

## Output contract

```text
article_id
url
headline
author
category
why_selected
style_excerpt
```

`why_selected` describes style relevance only.

## Evaluation

Create at least 20 retrieval queries. Human-score each result as:
- GOOD_STYLE_REFERENCE
- ACCEPTABLE
- IRRELEVANT

## Leakage guard

Archive examples may influence style only. Facts from them are forbidden unless independently present in the current EvidencePacket.

## Verification Gate

PASS only if:
- 20-query evaluation exists
- top results are mostly useful
- irrelevant patterns understood
- retrieval inspectable
- no factual use of archive content
- frozen Radar untouched

Then STOP.

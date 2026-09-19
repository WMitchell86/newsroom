"""M3A Editor Workbench: a thin browser layer over the frozen workflow contracts.

The workbench adds NO second editorial system. Every canonical write goes
through the validated functions the CLI already uses:

    cases.record_editor_final / cases.save_cases   (finalization)
    readiness.assess_readiness / apply_editor_override (decision recording)
    diff.diff_draft_final / classify_diff          (deterministic diff)

plus one non-authoritative editor working-copy store
(`editor_working/*.json`, never canonical, atomic writes) and a minimal
append-only audit log (`workbench_actions.jsonl`).

The AI draft is immutable here exactly as in the CLI; there is no publish
action of any kind.
"""

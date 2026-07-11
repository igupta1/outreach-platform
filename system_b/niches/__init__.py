"""Per-buyer niche packs.

`core` (the gift engine + copy scaffolding) is niche-blind; every buyer-specific
knob — signal vocabulary, priority signal, and the copy voice — lives in a
`NichePack`. Core functions take `pack=None` and lazily default to the CFO pack,
so existing call sites keep their exact behavior and a new niche is added purely
as a new pack (no edits to core logic).
"""

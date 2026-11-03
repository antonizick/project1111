"""One-click variations (spec §4): new seeds, or a small deterministic prompt mutation.

Pure: randomness comes only from the ``random.Random`` passed in, and the word lists are local.
``{{slot}}`` placeholders are never changed.
"""

from __future__ import annotations

import random

from .compile import resolve_seed
from .model import MAX_SEED, PLACEHOLDER, FixedSeed, Generate, RandomSeed, Recipe

#: Interchangeable words; a mutation swaps one for another in the same group.
SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("photo", "photograph", "shot"),
    ("detailed", "intricate", "finely detailed"),
    ("beautiful", "stunning", "striking"),
    ("bright", "vivid", "luminous"),
    ("soft light", "diffused light", "gentle light"),
    ("golden hour", "sunset light", "warm evening light"),
    ("night", "nighttime", "after dark"),
    ("misty", "foggy", "hazy"),
    ("cozy", "warm", "inviting"),
    ("cinematic", "filmic", "movie still"),
    ("minimalist", "minimal", "clean"),
    ("glossy", "shiny", "polished"),
    ("cute", "charming", "adorable"),
    ("large", "big", "huge"),
    ("small", "little", "tiny"),
)
#: Adjectives a mutation may add to a phrase.
ADJECTIVES: tuple[str, ...] = (
    "dramatic",
    "serene",
    "moody",
    "vibrant",
    "crisp",
    "atmospheric",
    "rich colors",
    "subtle contrast",
    "high detail",
    "soft focus background",
    "wide angle",
    "close-up",
)


def seed_variations(recipe: Recipe, n: int, rng: random.Random | None = None) -> list[Recipe]:
    """``n`` copies of ``recipe`` with distinct fixed seeds following the recipe's own seed.

    A fixed or increment strategy gives ``base + 1 … base + n``; a random one draws ``n`` seeds
    from ``rng`` (required then).
    """
    if n < 1:
        return []
    if isinstance(recipe.seed, RandomSeed):
        if rng is None:
            raise ValueError("seed_variations needs a random source for a random-seed recipe")
        seeds: list[int] = []
        while len(seeds) < n:
            s = rng.randrange(0, 2**32)
            if s not in seeds:
                seeds.append(s)
    else:
        base = resolve_seed(recipe.seed)
        seeds = [(base + i) % (MAX_SEED + 1) for i in range(1, n + 1)]
    return [recipe.model_copy(update={"seed": FixedSeed(value=s)}) for s in seeds]


def mutate_prompt(prompt: str, rng: random.Random) -> str:
    """One small change: a synonym swap, an added adjective, or two phrases swapped."""
    phrases = [p.strip() for p in prompt.split(",") if p.strip()]
    if not phrases:
        return prompt
    ops = ["adjective"]
    if any(_find_synonym(p) for p in phrases):
        ops.append("synonym")
    movable = [i for i, p in enumerate(phrases) if i > 0 and not PLACEHOLDER.search(p)]
    if len(movable) >= 2:
        ops.append("swap")
    op = rng.choice(ops)
    if op == "synonym":
        candidates = [i for i, p in enumerate(phrases) if _find_synonym(p)]
        i = rng.choice(candidates)
        word, group = _find_synonym(phrases[i]) or ("", ())
        replacement = rng.choice([w for w in group if w != word])
        phrases[i] = _replace_word(phrases[i], word, replacement)
    elif op == "swap":
        a, b = rng.sample(movable, 2)
        phrases[a], phrases[b] = phrases[b], phrases[a]
    else:
        present = {p.lower() for p in phrases}
        choices = [a for a in ADJECTIVES if a not in present] or list(ADJECTIVES)
        phrases.append(rng.choice(choices))
    return ", ".join(phrases)


def prompt_mutation(recipe: Recipe, rng: random.Random) -> Recipe:
    """A copy of ``recipe`` whose ``generate`` prompts each get one small deterministic change."""
    steps = tuple(
        s.model_copy(update={"prompt": mutate_prompt(s.prompt, rng)})
        if isinstance(s, Generate)
        else s
        for s in recipe.steps
    )
    return recipe.model_copy(update={"steps": steps})


def _find_synonym(phrase: str) -> tuple[str, tuple[str, ...]] | None:
    low = f" {phrase.lower()} "
    for group in SYNONYMS:
        for word in group:
            if f" {word} " in low:
                return word, group
    return None


def _replace_word(phrase: str, word: str, replacement: str) -> str:
    low = phrase.lower()
    padded = f" {low} "
    idx = padded.index(f" {word} ")  # the word starts at idx in phrase (padding cancels out)
    return phrase[:idx] + replacement + phrase[idx + len(word) :]

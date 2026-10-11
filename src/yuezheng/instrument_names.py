"""Resolve printed instrument names without guessing a different instrument family."""
import re


def _normalise(value: str) -> str:
    return " ".join(value.casefold().replace("♭", "b").replace("b-flat", "bb").split())


def resolve_instrument_name(value: str, catalog: dict) -> str:
    if not isinstance(value, str):
        return ""
    if value in catalog:
        return value
    names = {_normalise(spec["name"]): key for key, spec in catalog.items()}
    label = _normalise(value)
    if label in names:
        return names[label]
    # Desk numbers do not change instrument identity. Never match a broad prefix:
    # e.g. Flute alone must not turn Alto Flute into a concert flute.
    numbered = re.fullmatch(r"(.+?)\s+(?:[1-9][0-9]*|i|ii|iii|iv)", label)
    if numbered and numbered.group(1) in names:
        return names[numbered.group(1)]
    return value

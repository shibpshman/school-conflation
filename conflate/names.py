"""School name normalization and comparison.

NCES writes "GOV BENT ELEMENTARY"; OSM writes "Governor Bent Elementary School". Both become
"governor bent elementary": accents and punctuation stripped, abbreviations spelled out, and
filler words ("school", "the", "public") dropped.
"""

import re
import unicodedata

from rapidfuzz import fuzz

ABBREVIATIONS = {
    "elem": "elementary", "elm": "elementary", "el": "elementary", "es": "elementary",
    "ms": "middle", "mid": "middle", "hs": "high", "jhs": "junior high", "jr": "junior",
    "sr": "senior", "int": "intermediate", "intrmd": "intermediate", "inter": "intermediate",
    "acad": "academy", "ctr": "center", "cntr": "center", "alt": "alternative",
    "prep": "preparatory", "comm": "community", "st": "saint", "mt": "mount", "ft": "fort",
    "dr": "doctor", "gov": "governor", "abq": "albuquerque", "nm": "new mexico",
    "intl": "international",
    "sch": "school", "schl": "school", "cs": "charter",
}
# Single letters are directions only as the first word ("E Picacho"); elsewhere they are
# initials ("Cesar E Chavez").
DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}
FILLER = {"school", "schools", "the", "public", "of", "and"}
# A name that states a level ("elementary") rarely belongs to a school of another level.
LEVELS = {"elementary", "middle", "high", "intermediate", "junior", "primary", "kindergarten"}


def normalize(name):
    """Lowercase ASCII words, abbreviations expanded, filler dropped."""
    s = unicodedata.normalize("NFKD", name or "")
    s = s.encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = s.split()
    if words and words[0] in DIRECTIONS:
        words[0] = DIRECTIONS[words[0]]
    words = " ".join(ABBREVIATIONS.get(w, w) for w in words).split()
    return " ".join(w for w in words if w not in FILLER)


def levels(norm):
    return LEVELS.intersection(norm.split())


def similarity(a, b):
    """Similarity of two normalized names, 0 to 1.

    token_set_ratio forgives extra words on one side ("wilson middle" vs "wilson middle magnet").
    When both names state a level and the levels differ, the score is halved: "wilson middle" and
    "wilson elementary" share a word but are different schools, often on neighboring lots.
    """
    if not a or not b:
        return 0.0
    score = fuzz.token_set_ratio(a, b) / 100
    la, lb = levels(a), levels(b)
    if la and lb and not la & lb:
        score /= 2
    return score

from conflate.names import normalize, similarity


def test_abbreviations_and_filler():
    assert normalize("GOV BENT ELEMENTARY") == "governor bent elementary"
    assert normalize("Governor Bent Elementary School") == "governor bent elementary"
    assert normalize("ATRISCO HERITAGE ACADEMY HS") == "atrisco heritage academy high"
    assert normalize("St. Mary's School") == "saint marys"


def test_accents_and_punctuation():
    assert normalize("César E. Chávez Elementary") == "cesar e chavez elementary"
    assert normalize("Tse'ii'ahi' Community School") == "tseiiahi community"


def test_direction_only_as_first_word():
    assert normalize("E PICACHO ELEM") == "east picacho elementary"
    assert normalize("Cesar E Chavez") == "cesar e chavez"


def test_similarity():
    assert similarity("wilson middle", "wilson middle") == 1.0
    assert similarity("", "wilson middle") == 0.0
    # extra words on one side are forgiven
    assert similarity("mandela international magnet", "mandela international magnet mims") == 1.0


def test_level_conflict_halves_score():
    same = similarity("wilson middle", "wilson middle")
    other = similarity("wilson middle", "wilson elementary")
    assert other < 0.5 * same + 1e-9
    # no penalty when one side states no level
    assert similarity("wilson", "wilson elementary") == 1.0

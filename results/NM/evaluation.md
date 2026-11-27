# Evaluation, NM

Held-out half of the truth set: 76 schools (0 skipped as unjudgeable). Blocking radius 500 m, match threshold 0.56, both set on the tune half.

## Hand-built matcher

| | schools | in OSM | precision (95% CI) | recall (95% CI) | F1 | ambiguous | recall after review |
|---|---|---|---|---|---|---|---|
| all | 76 | 64 | 0.98 (0.91-1.00) | 0.86 (0.75-0.92) | 0.92 | 15 | 0.97 |
| city | 20 | 17 | 0.94 (0.73-0.99) | 0.94 (0.73-0.99) | 0.94 | 1 | 0.94 |
| rural | 31 | 29 | 1.00 (0.86-1.00) | 0.79 (0.62-0.90) | 0.88 | 7 | 0.97 |
| suburb | 7 | 6 | 1.00 (0.57-1.00) | 0.83 (0.44-0.97) | 0.91 | 2 | 1.00 |
| town | 18 | 12 | 1.00 (0.74-1.00) | 0.92 (0.65-0.99) | 0.96 | 5 | 1.00 |

## Splink (same blocked pairs, threshold 0.05 on match probability)

| | schools | in OSM | precision (95% CI) | recall (95% CI) | F1 | ambiguous | recall after review |
|---|---|---|---|---|---|---|---|
| all | 76 | 64 | 0.92 (0.83-0.97) | 0.91 (0.81-0.96) | 0.91 | 0 | 0.91 |
| city | 20 | 17 | 0.89 (0.67-0.97) | 0.94 (0.73-0.99) | 0.91 | 0 | 0.94 |
| rural | 31 | 29 | 0.96 (0.81-0.99) | 0.86 (0.69-0.95) | 0.91 | 0 | 0.86 |
| suburb | 7 | 6 | 0.83 (0.44-0.97) | 0.83 (0.44-0.97) | 0.83 | 0 | 0.83 |
| town | 18 | 12 | 0.92 (0.67-0.99) | 1.00 (0.76-1.00) | 0.96 | 0 | 1.00 |

Correct by the hand-built matcher only: 1; by Splink only: 4.

## Errors on the held-out half

| school | class | truth | matcher picked | reason |
|---|---|---|---|---|
| RENAISSANCE ACADEMY CHARTER SCHOOL | ambiguous | way/556573596 | node/5368647983 | name 0.59 vs name 'Eastern Hills Christian Academy', 208 m, score 0.56; runner-up way/556573596 'Northpoint Charter School' scored 0.69 |
| MOUNTAINAIR JR HIGH | ambiguous | way/624076462 | way/624076462 | best candidate way/624076462 'Mountainair High School' (0 m, score 1.00) went to MOUNTAINAIR HIGH (350195000473); shared campus? |
| HOLLOMAN ELEMENTARY | ambiguous | way/1171451582 | way/1171451582 | best candidate way/1171451582 (unnamed) (0 m, score 0.65) went to HOLLOMAN MIDDLE (350003000007); shared campus? |
| HEIZER MIDDLE SCHOOL | ambiguous | way/317846266 | way/317846266 | OSM school has no name, 0 m, score 0.65 |
| PENASCO HIGH | ambiguous | node/357614399;way/1178695339 | way/1178695339 | best candidate way/1178695339 'Penasco Schools' (0 m, score 1.00) went to PENASCO MIDDLE (350204000695); shared campus? |
| TATUM HIGH | ambiguous | node/357604584 | node/357614437 | name 1.00 vs name 'Tatum Junior High School', 32 m, score 0.97; runner-up node/357604584 'Tatum High School' scored 0.95 |
| MESA VISTA MIDDLE | ambiguous | way/1312303841;node/357603472 | way/1312303841 | best candidate way/1312303841 'Mesa Vista Public Schools' (0 m, score 1.00) went to MESA VISTA HIGH (350198000475); shared campus? |
| DULCE MIDDLE | ambiguous | node/7021856888 | node/7021856888 | name 0.29 vs name 'Dulce Elementary School', 32 m, score 0.48, below the 0.56 match threshold |
| NEW AMERICA SCHOOL - LAS CRUCES | matched | none | node/1027713485 | name 0.75 vs name 'Las Cruces Academy', 57 m, score 0.77 |
| SPARTAN LEARNING ACADEMY | ambiguous | node/357613657;way/945317726 | way/945317726 | best candidate way/945317726 'Bernalillo Middle School' (0 m, score 0.47) went to BERNALILLO ELEMENTARY (350021000152); shared campus? |

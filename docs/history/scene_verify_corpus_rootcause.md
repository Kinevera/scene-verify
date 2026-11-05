# Scene-verifier corpus — failure root-cause appendix

Corpus distribution: **{'pass': 5, 'fail': 4}** over 9 v0.1 instances (the verifier DISCRIMINATES — it passes some rows and fails others, so it is not indiscriminately rejecting).

## pack_2_close_i1 — fail
- **static_settle** (topple): offender `pump_bottle` — linear 0.1594m > 0.01m / angular 159.0deg > 5.0deg
  - root cause: object does not rest from its authored spawn pose (tips on settle)
  - cross-check: SCENE-COMPOSITION defect (asset settles stably elsewhere -> not a broken asset or an over-tight gate) (stable in ['pack_1_i2', 'pack_2_close_i3', 'pack_3_dense_close_i1', 'pack_3_dense_close_i2'])

## pack_2_close_i2 — fail
- **visual_collision_agreement** (collider_visual_mismatch): offender `book_brick` — phantom 0.017181m / clip 0.011862m vs fail 0.015m
  - root cause: collision geometry diverges from rendered geometry beyond the mesh-agreement threshold
  - cross-check: REAL asset property: book_brick shows the same collider-vs-visual divergence in 3/3 rows it appears in -> deterministic, not a pose fluke or noisy gate; correctly flagged wherever it is packed. (same divergence in ['pack_2_close_i2', 'pack_3_dense_close_i2', 'pack_3_dense_close_i3'])

## pack_3_dense_close_i2 — fail
- **visual_collision_agreement** (collider_visual_mismatch): offender `book_brick` — phantom 0.017181m / clip 0.011862m vs fail 0.015m
  - root cause: collision geometry diverges from rendered geometry beyond the mesh-agreement threshold
  - cross-check: REAL asset property: book_brick shows the same collider-vs-visual divergence in 3/3 rows it appears in -> deterministic, not a pose fluke or noisy gate; correctly flagged wherever it is packed. (same divergence in ['pack_2_close_i2', 'pack_3_dense_close_i2', 'pack_3_dense_close_i3'])
- **static_settle** (spawn_pose_tip): offender `stapler_tool` — linear 0.0150m > 0.01m / angular 14.8deg > 5.0deg
  - root cause: object does not rest from its authored spawn pose (tips on settle)
  - cross-check: SCENE-COMPOSITION defect (asset settles stably elsewhere -> not a broken asset or an over-tight gate) (stable in ['pack_1_i3', 'pack_2_close_i3'])

## pack_3_dense_close_i3 — fail
- **visual_collision_agreement** (collider_visual_mismatch): offender `book_brick` — phantom 0.017181m / clip 0.011862m vs fail 0.015m
  - root cause: collision geometry diverges from rendered geometry beyond the mesh-agreement threshold
  - cross-check: REAL asset property: book_brick shows the same collider-vs-visual divergence in 3/3 rows it appears in -> deterministic, not a pose fluke or noisy gate; correctly flagged wherever it is packed. (same divergence in ['pack_2_close_i2', 'pack_3_dense_close_i2', 'pack_3_dense_close_i3'])
- **static_settle** (catastrophic_ejection): offender `pump_bottle` — linear 5.8489m > 0.01m / angular 25.0deg > 5.0deg
  - additional offenders: `shipping_box_small` (linear 0.05895m, angular 46.161deg); `book_brick` (linear 0.06121m, angular 79.684deg)
  - root cause: object ejected through the world during settle (consistent with spawn overlap in a crowded scene — inferred; the post-settle interpenetration gate cannot evidence spawn-time overlap)
  - cross-check: SCENE-COMPOSITION defect (asset settles stably elsewhere -> not a broken asset or an over-tight gate) (stable in ['pack_1_i2', 'pack_2_close_i3', 'pack_3_dense_close_i1', 'pack_3_dense_close_i2'])
- **fall_through** (fell_below_floor): offender `pump_bottle` — bottom_z -3.3066m < floor 0.481m
  - root cause: object's lowest point dropped below the floor threshold (no support / ejected)
  - cross-check: SCENE-COMPOSITION defect (asset settles stably elsewhere -> not a broken asset or an over-tight gate) (stable in ['pack_1_i2', 'pack_2_close_i3', 'pack_3_dense_close_i1', 'pack_3_dense_close_i2'])

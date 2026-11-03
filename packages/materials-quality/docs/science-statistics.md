# Statistics and modeling nodes

Eight statistics and modeling operations cover descriptive statistics, distributions, correlations, significance tests, group comparisons, model training, prediction and evaluation.

All operations have `fn(table=None, *, config=None, data=None, tables=None) -> NodeResult`. Tables are pandas DataFrames; config and data are JSON objects. Import the operations from `materials_quality.science.statistics`. Each operation has its own CATALOG entry and native adapter. Run the package with the `science` extra installed; this domain uses NumPy, pandas, SciPy, statsmodels, scikit-learn, skops, matplotlib and Pillow. No API account, network access or proprietary reference database is required.

## Input design

Selected numeric columns must be finite and contain no missing or Boolean values. Handle missing values explicitly upstream. Group labels cannot be missing. Significance tests require at least two observations per group; that minimum permits computation and does not establish adequate power. Grouped descriptive statistics permit singleton groups and report their undefined sample standard deviation as null. Correlation and Shapiro require at least three observations and nonconstant data.

Rows must represent experimental units. Supply `subject` to independent-group significance tests to check that specimen IDs are unique. Repeated IDs are rejected; aggregate technical replicates before testing. A declared `pair_id` requires the `paired_t` method. Paired tests join by ID and group, reject duplicate ID/group measurements, require two groups and at least two complete pairs. Missing partners cause an error unless `incomplete_pairs: "drop"` is explicitly selected; dropped pair counts and retained pair IDs are returned. Algorithms cannot infer experimental independence from a table that omits identity information.

## Complete method reference

Use [native forms](node-usability.md) for ordinary workflows. The configuration keys below also apply to advanced JSON and Python API calls.

| Operation | Required config and selector | Behavior and evidence | Verification |
| --- | --- | --- | --- |
| `stats.grouped` | `group`, `columns: ["value"]` | Long result: count, mean, sample std (`ddof=1`), median, q25, q75, min, max for every group/variable; unit declarations retained in Data | `test_grouped_preserves_all_descriptors_and_input` checks all eight quantities against `[1,2,3,4,5]` |
| `stats.distribution` | `column`; optional `bins` (integer, edges, or `"auto"`) | Histogram counts/edges, normal Q-Q coordinates and fitted line, Shapiro statistic/p-value, two verified PNGs; warns for Shapiro n > 5000 | `test_distribution_exports_numeric_histogram_and_qq` checks total counts, point count, probability and decoded images |
| `stats.correlation` | `columns`, `method: "pearson"` | Every column pair: coefficient, two-sided unadjusted p-value and n; Pearson also reports the confidence interval | `test_correlations_recover_perfect_relationship[pearson]` |
| `stats.correlation` | `method: "spearman"` | Spearman rank correlation with tied ranks supported | Same test `[spearman]` |
| `stats.correlation` | `method: "kendall"` | Kendall tau with tie handling | Same test `[kendall]` |
| `stats.significance` | `group`, `column`, `method: "independent_t"`; optional `groups` (explicit group order) and `subject` | Pooled-variance t test; mean difference is first minus second group; t-based CI and absolute Cohen d | `test_significance_separates_groups_with_effect_and_assumptions[independent_t]` |
| `stats.significance` | `method: "paired_t"`, `pair_id` | ID-aligned paired t; mean difference, CI, absolute Cohen dz, complete/dropped pair counts and IDs | `test_paired_requires_ids_aligns_pairs_and_rejects_replicates`, `test_incomplete_pairs_drop_only_when_explicit` |
| `stats.significance` | `method: "welch"` (default) | Unequal-variance t, Welch-Satterthwaite df, mean-difference CI, absolute pooled Cohen d | Significance test `[welch]` |
| `stats.significance` | `method: "mannwhitney"` | Two-sided U with automatic exact/asymptotic selection and absolute rank-biserial effect | Significance test `[mannwhitney]` |
| `stats.significance` | `method: "anova"` | One-way classical ANOVA F and eta-squared; at least two independent groups | Significance test `[anova]` |
| `stats.significance` | `method: "kruskal"` | Tie-corrected Kruskal-Wallis H and nonnegative epsilon-squared | Significance test `[kruskal]` |
| `stats.multiple` | `method: "tukey"`, `group`, `column` | Tukey HSD / Tukey-Kramer all-pair mean differences, family-adjusted p-values, simultaneous CIs, rejection flags | `test_pairwise_multiple_comparisons_have_adjusted_probabilities[tukey]` |
| `stats.multiple` | `method: "dunn"`, `group`, `column`; optional `correction: "holm"` (default) or `"fdr"` | Pooled-rank Dunn z contrasts with tie-corrected variance, two-sided p-values and corrected p-values | Same test `[dunn]`; `test_dunn_tie_correction_matches_hand_computed_rank_contrast` checks z = -1.82574185835 and p = 0.06788915486 |
| `stats.multiple` | `method: "holm"` or `"fdr"`, `column` (`pvalue` default) | Holm FWER or Benjamini-Hochberg FDR; retains original hypothesis order; validates p in [0,1] | `test_corrections_preserve_original_hypothesis_order` independently checks both methods |
| `stats.regression` | `features`, `target`, `method: "linear"` | Linear least squares, train-only standard scaling, heldout predictions/metrics; original-unit coefficients/intercept | `test_models_holdout_and_safe_serialized_prediction[linear]` |
| `stats.regression` | `method: "polynomial"`, `degree` (default 2, range 1–8) | Multivariate polynomial features and least squares; polynomial terms and original-scale coefficients | Same model test plus `test_polynomial_recovers_quadratic_and_reports_original_scale_terms` checks exact `[−3,2]` coefficients/intercept 1 |
| `stats.regression` | `method: "ridge"` or `"lasso"`; `alpha` (default 1), `max_iter` (Lasso default 10000) | L2 or L1 penalized regression in training-standardized feature coordinates; returned coefficients transformed to original feature units | Model tests `[ridge]` and `[lasso]` |
| `stats.predict` | `features`, `target`, `method: "random_forest"`; `n_estimators` (100), optional `max_depth` | Random forest regressor; fitted feature importance and heldout predictions | Model test `[random_forest]` |
| `stats.predict` | `method: "gradient_boosting"`; `n_estimators` (100), `max_depth` (3) | Gradient boosting regressor; safe skops loss/link allowlist | Model test `[gradient_boosting]` |
| `stats.predict` | `method: "svr"`; `C` (10), `epsilon` (.1), `kernel` (`rbf`) | Support vector regression in train-standardized features; support-vector count | Model test `[svr]` |
| `stats.predict` | `model_path` and upstream manifest Data, or `manifest_path` in config/upstream Data; `model_path` may also name the JSON manifest | Reload a generated skops model, validate SHA256/types/feature order, return new predictions; no refitting | Every model test compares reloaded predictions against the original holdout; `test_manifest_only_routes_load_saved_model_without_retraining` checks all four config/upstream path forms for prediction and evaluation |
| `stats.evaluate` | `method: "holdout"`, `model_method`, `features`, `target` | Fits the declared model after a split; reports actual heldout MAE, RMSE, R², row positions and identities | All seven model tests and demo |
| `stats.evaluate` | `method: "cv"`, `model_method`, `features`, `target`, `folds` (5) | Fresh cloned pipeline per shuffled fold; per-fold metrics and pooled out-of-fold MAE/RMSE/R²; never reused global fitted scaling | `test_cv_predictions_are_out_of_fold_and_scaling_fitted_on_train` checks every scaler mean against that fold's training rows |
| `stats.evaluate` | Upstream model manifest/path plus evaluation table | Fingerprint-exact original test rows, disjoint from stored train fingerprints, labeled `manifest_holdout`; other datasets labeled `provided_model_dataset` with independence warning | `test_evaluate_saved_holdout_manifest_and_explicit_table_predictions` |
| `stats.evaluate` | Data `y_true`, `y_pred`; or config mapping those names to table columns | Computes MAE/RMSE/R², labeled `provided_predictions`; provenance remains caller-supplied | `test_evaluation_explicit_vectors_and_invalid_model_inputs` checks hand-derived MAE/RMSE/R² |

All tests above are in `tests/test_science_stats.py`; figure/export tests are in `tests/test_science_viz.py`. `alpha` means inference significance level (default .05) in inference nodes and regularization strength in regression nodes. Undefined R² for a constant evaluation target is null, with a warning on fitted holdout results. No training metric is labeled a test score.

## Modeling leakage and persistence

Common model config: `features: ["x"]`, `target: "y"`, `seed: 42`, `test_size: .2`, optional unique `id_column`, optional `group_column`. Split identities default to row positions, independent of the pandas index. `group_column` performs GroupShuffleSplit or GroupKFold so one specimen's repeated rows stay on one side of each split. Without it, row-level random splitting explicitly assumes independent rows. Models require at least five rows, at least two train and test rows, and finite numeric predictors/targets. Target-as-predictor and duplicate configured row IDs are rejected. Cross-validation fold count must allow at least two test rows per fold; highly uneven group sizes can require fewer folds.

Preprocessing is inside the sklearn Pipeline. Splits happen before `.fit()`, and each CV fold clones/fits the entire pipeline independently. Outputs retain train/test IDs, row positions, seeds and scaler means. Linear-family output includes coefficients in original input-feature units; polynomial coefficients refer to explicitly named polynomial terms. Forest impurity importance is labeled as such and is not a causal effect.

Models are `.skops` plus JSON manifests. Return Data contains only JSON values and artifact paths, never Python estimators. Save immediately reloads and numerically verifies predictions. Load first verifies SHA256 when a manifest is supplied, uses `get_untrusted_types`, and permits only explicitly enumerated sklearn squared-error loss/link classes beyond skops defaults; unknown types are rejected. A .pkl/.joblib path is rejected. Feature order comes from the manifest or an explicit declaration. Keep the generated pair together; installed sklearn/skops versions should match the training environment. A checksum detects changes relative to the supplied manifest, not an untrusted sender's identity.

Both `predict` and `evaluate` accept `config={"manifest_path": ".../model-manifest.json"}` or upstream `data={"manifest_path": ".../model-manifest.json"}` without repeating features/target or passing the whole model Data. They also accept that JSON path via `model_path`. These routes always reload the saved fitted pipeline; they do not fall through to model training. Evaluation still needs the true target column in its supplied table.

## Synthetic run and prerequisites

From the package root after installing `.[science]`:

```powershell
$env:PYTHONUTF8 = '1'
$env:MPLBACKEND = 'Agg'
python examples/science/statistics/run_demo.py --output-dir artifacts/science-statistics-demo
python -m pytest tests/test_science_stats.py tests/test_science_viz.py --basetemp artifacts/pytest-stats-local
```

The demo uses the checked-in synthetic `groups.csv` and `paired.csv`, generates an exact 60-row `y=2x+3` modeling fixture, runs every required selector, and writes a JSON manifest containing actual configs/results/warnings/artifacts. The two distribution PNGs, all seven serialized fitted models, and manifest contents are read back. All data are demonstrations, not materials experiments.

Tested dependencies for this domain: Python 3.10, SciPy 1.15.3, scikit-learn 1.7.2, statsmodels 0.14.6, skops 0.13.0, matplotlib 3.10.9, pandas 2.x, NumPy 2.x and Pillow. Install these dependencies through the package `science` extra. Scientific assumptions are exposed, not automatically certified by a normality p-value. Regression uncertainty intervals and mixed-effects/repeated-measures ANOVA are outside the requested methods.

Primary API references: [SciPy Shapiro](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.shapiro.html), [SciPy Tukey HSD](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.tukey_hsd.html), [statsmodels multiple testing](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html), [sklearn leakage prevention](https://scikit-learn.org/stable/common_pitfalls.html), [skops persistence](https://skops.readthedocs.io/en/stable/persistence.html). Dunn uses the conventional pooled-rank normal contrast with explicit tie correction; the two-group tied-rank test verifies the implemented formula independently.

Historical domain test results are retained in the [development archive](development/domain-validation.md).

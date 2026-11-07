# Method cards: evidence, selection and execution

The packaged library contains 11 method/task cards: SG smoothing, first and second
derivatives, SNV, AsLS, PCA, PLS, peak detection, physical-window integration, NMF,
and MSC. NMF and MSC are planned, have no execution operation, and always return
`blocked`. The other mappings bind actual StudyUI configuration fields.

## Verification record — 2026-11-06

Each source below was independently opened and read at its cited locator. Exact
short quotations are stored once in `science/method_cards.json`, with version,
date, source kind and access scope. The three SG cards together quote 22 words
from their shared source. No downloaded third-party implementation is copied.

| Cards | Primary source and inspected location | Evidence scope |
|---|---|---|
| SG smoothing, first/second derivative | [SciPy 1.15.3 savgol_filter](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.signal.savgol_filter.html), introduction and window_length/polyorder/deriv/delta parameters | Algorithm documentation, not a material experiment |
| SNV | [Barnes, Dhanoa & Lister (1989)](https://opg.optica.org/as/abstract.cfm?uri=as-43-5-772), abstract paragraph 2; DOI 10.1366/0003702894202201 | Original research abstract only; paywalled full text was not read. Describes NIR diffuse reflectance, not dark-field spectra |
| SNV implementation | [prospectr 0.2.7 standardNormalVariate](https://search.r-project.org/CRAN/refmans/prospectr/html/standardNormalVariate.html), row-wise equation | Author-maintained software documentation; no experimental settings inferred |
| AsLS | [pybaselines 1.2.1 Whittaker Baselines](https://pybaselines.readthedocs.io/en/stable/algorithms/whittaker.html), asls objective, linear system and weights | Author-maintained algorithm description; stable URL version was 1.2.1 on verification date |
| PCA | [scikit-learn 1.6.1 PCA](https://scikit-learn.org/1.6/modules/generated/sklearn.decomposition.PCA.html), introductory paragraph and fit/transform | Algorithm documentation; StudyUI separately fits scaling only on training data |
| PLS | [scikit-learn 1.6.1 PLSRegression](https://scikit-learn.org/1.6/modules/generated/sklearn.cross_decomposition.PLSRegression.html), introduction, parameters and fit | Algorithm documentation, not evidence of predictive accuracy on user data |
| Peaks | [SciPy 1.15.3 find_peaks](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.signal.find_peaks.html), definition and prominence/distance parameters | Local maxima; physical spacing conversion is StudyUI's adaptation |
| Integration | [SciPy 1.15.3 trapezoid](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.integrate.trapezoid.html), introductory definition and x parameter | Numerical quadrature; physical windows are user choices |
| NMF | [scikit-learn 1.6.1 NMF](https://scikit-learn.org/1.6/modules/generated/sklearn.decomposition.NMF.html), nonnegative X/W/H definition | Planned operation; cannot execute |
| MSC | [prospectr 0.2.7 msc](https://search.r-project.org/CRAN/refmans/prospectr/html/msc.html), ref_spectrum and train/new-data examples | Planned operation; inspected reference contract, not the displayed formula (which has a sign discrepancy) |

The [scikit-learn leakage guidance](https://scikit-learn.org/1.6/common_pitfalls.html#data-leakage)
also informed the training-only eligibility condition. Document versions above
identify evidence snapshots, not a claim that the installed runtime is that
version. Package dependency pins remain authoritative for execution.

## Input and output

`recommend_methods(table=None, *, config=None, data=None, tables=None)` is offline
and returns a `NodeResult`. Free text uses deterministic lexical overlap and stable
ID tie-breaking; unrelated text returns zero candidates. Empty text lists cards.
Explicit `method_ids` include selected cards even when their conditions fail.
`material` never substitutes for `signal_type`.

Conditions are flat config fields: signal_type, x_unit, y_unit,
allow_intensity_loss, equally_spaced, nonzero_variance, positive_peaks,
nonnegative, fit_scope, split_confirmed and groups_disjoint. Unknown stays
unknown. Native controls expose unknown/yes/no, converted internally to booleans.
The initial form shows discovery and signal metadata; choosing a goal reveals
its relevant conditions and parameters. Hidden stale values are omitted from
the form configuration. Advanced/API sequence checks remain available.
Actual supplied x/y coordinates, variance and sign override declarations. Supplied
split/sample/group columns are checked for cross-split identity overlap.

Candidate `status` is `missing`, `blocked`, or `eligible`; blocked conditions take
precedence while missing conditions are retained. `execution` is null except for
eligible, implemented methods. Eligibility is based on available declarations and
table facts; `scientifically_validated` is always false. The actual computation
still validates matrix rank, finite values, windows, units and other input details.

SG requires explicit window/order; integration requires explicit ranges; PLS/PCA
require feature/sample/split columns and component count. AsLS starts at lambda
1e5, p .01 and 20 iterations; these are labelled engineering defaults, not a
published material recipe. No physical window is silently enlarged.

`sequence` checks ordered method IDs before display truncation, including negative
values after SNV, derivatives, PCA or baseline subtraction before NMF. It reports
individual missing/blocked conditions as well. This conservative check does not
claim complete automatic composition: curves and sample matrices have different
layouts, and no sequence is executed by this node.

The recommendation does not turn a literature statement into a measured result.
Use the source URL, locator, version and quotation to support an explanation;
measured claims must separately reference actual output cells or artifacts.

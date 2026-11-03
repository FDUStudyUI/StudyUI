# Visualization, table export and reports

Unit metadata is reconciled across table attributes, upstream reports and explicit configuration;
contradictory declarations fail before writing. Excel rejects numeric integers exceeding its
15-digit precision. Export these as declared text identifiers or use CSV when exact large integers
are required. Integer readback comparisons are exact.

Six visualization and export operations are available from `materials_quality.science.visualization`. Every figure exposes its actual plot coordinates and aggregates in JSON-safe `NodeResult.data.plot_data`.

## Complete method reference

Use [native forms](node-usability.md) for ordinary workflows. The configuration keys below also apply to advanced JSON and Python API calls.

| Operation | Config | Result and verification |
| --- | --- | --- |
| `viz.performance` | `method: "scatter"`, numeric `x`, numeric `y`, optional `group` | Per-group actual scatter observations; group count and means returned; `test_performance_plots_expose_actual_groups_and_observations[scatter]` |
| `viz.performance` | `method: "bar"`, `y`, optional `group` | Group mean with sample standard deviation error bars (`ddof=1`), explicitly labeled; singleton uncertainty warned; same test `[bar]` |
| `viz.performance` | `method: "box"`, `y`, optional `group` | Conventional group box-and-whisker plots, with original observations retained in plot data; same test `[box]` |
| `viz.performance` | `method: "violin"`, `y`, optional `group` | KDE violin with means/extrema, requiring at least two varying values in every group; same test `[violin]` |
| `viz.spectra` | `method: "line"`, ascending `x`, `columns` intensity list | Line spectra/diffraction traces on the supplied common coordinate grid; `test_spectra_difference_and_peak_labels_are_numeric[line]` |
| `viz.spectra` | `method: "overlay"`, same columns; optional `offset` | Multiple spectra; display offsets recorded separately in JSON; same test `[overlay]` |
| `viz.spectra` | `method: "difference"`, exactly two intensity columns | First minus second intensity at every supplied x; same test `[difference]` checks `[1,3,0,0]` |
| `viz.spectra` | `peaks: [{"x":2,"label":"peak"}]` | Explicit peak labels with leader lines; positions must be finite and inside the measured range; all spectrum tests verify numeric annotations |
| `viz.mechanics` | `method: "overlay"`, `x`, `y`, `sample`, optional `group` | Per-specimen stress–strain curves and identities; at least two distinct coordinates per specimen; `test_mechanics_mean_and_sample_std_errorband[overlay]` |
| `viz.mechanics` | `method: "mean_error"`, same inputs; `error: "std"` (default), `"sem"`, or `"ci95"` | Independent specimen means with sample SD, SEM or pointwise t-based 95% CI band; at least two specimens per group; same test `[mean_error]` checks mean `[0,3,6]` and SD √2 at x=1 |
| `viz.mechanics` | Optional explicit ascending `grid` | Explicit grid is always validated/applied, even when measured specimen grids already match; unequal grids require it; no extrapolation. `test_mechanics_explicit_grid_interpolation_and_sem` and `test_mechanics_explicit_grid_applies_even_when_measured_grids_match` verify interpolation, range and mean/error values |
| `viz.statistics` | `method: "histogram"`, `column`, optional `bins` | Histogram counts, edges and observations returned; `test_png_svg_pdf_exports_and_exact_histogram_counts` checks exact bin counts `[2,1,3]` |
| `viz.statistics` | `method: "correlation"`, `columns`, optional `correlation_method: "pearson"/"spearman"/"kendall"` | Annotated −1 to 1 heatmap; finite varying data and at least three observations required; `test_statistical_figures_validate_values[correlation]` |
| `viz.statistics` | `method: "residual"`, `y_true`, `y_pred` (column names, defaults match keys) | Predicted against observed-minus-predicted residual; zero reference; same test `[residual]` verifies `[0,-1,1,-1]` |
| `viz.statistics` | `method: "prediction"`, same mapping | Observed versus predicted, with identity line; same test `[prediction]` |
| `export.table` | `format: "csv"`, optional `id_columns`, `units`, `filename` | UTF-8 BOM CSV, original column names/order, unchanged textual IDs, JSON sidecar with units/types/ID columns/SHA256; decoded table checked column by column |
| `export.table` | `format: "excel"` (`xlsx` alias), same config | Genuine .xlsx Results and Metadata sheets; exact text cells preserve leading zeros and formula-looking strings; openpyxl reload verifies values and schema |
| `export.report` | `format: "html"` (default) | Actual HTML report template with title, data sources, node parameters, results, result table, embedded figures and warnings; all untrusted text HTML-escaped |
| `export.report` | `format: "markdown"` (`md` alias) | Markdown template with the same sections; raw HTML and Markdown control text escaped; figures embedded as PNG data URIs |

`viz.statistics` calls the pure function `statistics_plot`; this avoids confusing the stats module with a plotting operation. Tests are in `tests/test_science_viz.py`. `test_export_roundtrips_leading_zero_ids_units_and_formula_text` covers both table formats. `test_report_embeds_verified_figure_and_escapes_untrusted_html` decodes/embeds real figures and checks hostile title escaping; `test_markdown_report_embeds_image_and_escapes_raw_html` covers Markdown. Empty tables, missing values, malformed inputs and preservation of a preexisting raw file have independent tests.

## Shared figure contract

Use `units: {"stress": "MPa"}` to label axes, `title` for a figure title, `figsize: [7,4.6]` (inches), `dpi:150`, `formats:["png"]` or combinations of `png/svg/pdf`, and `output_dir` to choose an artifact directory. Default paths are fresh temporary directories; filename collisions receive fresh names. A PNG preview is always emitted first even when SVG/PDF are requested. PNG is decoded and checked for dimensions/content; SVG XML and PDF signatures are checked at export. Tests also open/rasterize the generated PDF with PyMuPDF. Plot data retain labels, raw values, counts, coordinates, aggregate/error definitions and specimen counts.

Grouping uses the given labels; missing labels and nonfinite numeric coordinates are rejected. Spectra require one strictly increasing common coordinate grid, so differences do not silently interpolate misaligned spectra. Mechanics requires strictly increasing coordinates in acquisition order for every specimen: mixed loading/unloading sequences are rejected rather than silently sorted into a different curve. Select a monotonic loading segment upstream when needed. An explicit mean/error `grid` always applies and must stay inside every specimen range, including when original grids match. Error bands describe variation across specimens, not across neighboring points in one curve. CI bands are pointwise and do not claim simultaneous coverage. Caller-supplied predictions retain their original provenance; drawing a residual plot does not establish heldout validation.

## Table and report contracts

Export tables are copies. Column names stay unchanged. Declare sample-ID columns explicitly so the metadata records their intended textual interpretation. CSV schema preserves all text/object columns, including undeclared text such as `note=["001","002"]`, and all declared ID columns. Its sidecar `csv_readback` object contains the complete `dtype` map plus `keep_default_na: false`; reopen with `pd.read_csv(file_path, **metadata["csv_readback"])`. CSV cannot force third-party software to honor that schema. Excel stores caller text in table bodies, column headers, Metadata column names and unit values as actual string cells, including `=1+1`; it verifies those cell types after reopening, so formula-looking headers/units never become formulas. Missing values stay missing on roundtrip; original exact numeric/text values are verified. Units are retained in the JSON metadata and Excel Metadata worksheet. Exports never overwrite an existing file even when `overwrite:true` is passed.

Report Data is `{"title": "...", "sources": [...], "parameters": {...}, "results": {...}, "figures": ["/absolute/figure.png"], "warnings": [...]}`. Figure entries may also be `{"path": "...", "caption": "..."}`. Existing local raster figures are decoded, normalized to PNG, embedded as data URIs and decoded again from the actual embedded bytes. Missing/unreadable figures fail explicitly. The final UTF-8 report is read back byte-equivalently. Reports are self-contained HTML/Markdown; full-report PDF export is outside the source requirements. Quantitative figure PDF is supported.

Report generation assembles supplied results and provenance; it does not invent missing sources, statistics or captions. Raw HTML, script titles, table text and image captions are escaped. Markdown report text also escapes Markdown control characters. No external JavaScript, remote image downloads, hidden uploads or messages are used.

## Beginner run instructions and external dependencies

Install the package `science` extra, then run from the package directory:

```powershell
$env:PYTHONUTF8 = '1'
$env:MPLBACKEND = 'Agg'
python examples/science/visualization/run_demo.py --output-dir artifacts/science-visualization-demo
```

Open the generated `export_report-html/analysis-report.html` in a browser. Every plot, CSV, Excel and both report formats also have a separate operation directory; `visualization-demo.json` records all actual inputs/configs/outputs/warnings. Checked-in `spectra.csv` and `mechanics.csv` and the generated small performance/prediction tables are synthetic. No installation credentials, external database, browser account or network service is needed. matplotlib uses its headless Agg backend. Excel requires openpyxl, image verification Pillow; figure PDF test rendering uses PyMuPDF. Fonts containing requested non-Latin glyphs must be installed to display those glyphs; numeric/default-English examples do not require a Chinese font.

Primary implementation references: [matplotlib violinplot](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.violinplot.html), [openpyxl formula behavior](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html), and the [statistics references](science-statistics.md).

Historical domain test results are retained in the [development archive](development/domain-validation.md).

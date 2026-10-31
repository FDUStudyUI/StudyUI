# Complete materials workflow node suite

User instruction: implement every requirement in 工作流节点.md and update the team repository; start directly. This authorizes routine design choices and implementation without another approval round. Source document is copied verbatim at docs/reference-workflow-nodes.md: eight categories, fifty functional entries; submethods are requirements, not optional placeholders.

## Architecture

Retain and extend the existing six quality checks and two support components. Add forty-four independently discoverable native Langflow components, backed by pure Python operations in materials_quality/science. Do not fork Langflow's frontend. Use typed DataFrame/Data/Message outputs, a JSON config input, explicit file/column/calibration inputs and validated errors. A single generic node pretending to implement fifty functions is not acceptable.

Alternatives considered: a separate service would add deployment overhead; duplicating algorithm code inside every node would make validation and reuse harder. Use separate core operations plus thin native adapters. Operations with many related methods expose a validated method selector in config; every method listed in the source document must have a working path and independent verification.

## Stable operation interface

Every new operation has signature `function(table=None, *, config=None, data=None, tables=None) -> NodeResult`. `table` is a pandas DataFrame or None; `tables` is a list of DataFrames or None; `data` is a dict/list of upstream structured data or None; config is a JSON dict. It returns `NodeResult(table=None, data={}, artifacts=[], warnings=[])` from materials_quality.science.contracts. A returned table must be a new object; input tables/files are never silently overwritten. Artifacts are string paths. No Langflow import in core operations.

Each domain exports `CATALOG`, a list of dicts containing `key`, `title` (Chinese), `function` (`module:function`), `category`, `requirement` (source label), `table_input`/`data_input`/`tables_input` booleans and `default_config` dict. Function imports are lazy. Parent owns the global catalog, adapters, component generation and shared contracts; domain agents own only their assigned modules/tests/docs/fixtures.

Shared utilities: `require_table(table, columns=None, min_rows=1)` validates and returns a deep copy; `numeric_matrix(table, columns)` returns a finite float numpy matrix (errors on nonnumeric/missing); `artifact_path(config, filename)` provides a fresh temp output directory unless output_dir is explicit; `read_path(config, data=None)` resolves a configured path or upstream file_path and validates it exists. Missing optional engines, credentials or reference data produce explicit configuration errors, never fabricated success.

## Scientific and data constraints

- Preserve raw files and use copies for transformations. Every transformation reports parameters, affected rows/fields and original/revised values or equivalent auditable change records.
- Missing-value interpolation requires explicit ordered continuous coordinates; never default-fill experimental results.
- Units use explicit declarations; temperature offsets must be handled correctly. No inference of physical identity from dimensions alone.
- Statistics respect paired/repeated observations, group identity and distribution assumptions. Predictive evaluation splits before fitting preprocessing and reports random seeds/split identities; no training metrics mislabeled as held-out performance.
- XRD matching uses supplied reference data. Whole-pattern profile fitting must be labeled by its actual model, not misrepresented as structural Rietveld refinement. Spectral matching also requires references. Morphology requires explicit spatial calibration or reports pixel units. EDS reads supplied quantified results; no fake ZAF quantification.
- Literature extraction retains exact evidence quotes and source locations. Optional LLM extraction must validate its JSON and ground claims in source text. No invented DOI, citation, phase or property values.
- OCR engines and public metadata APIs have real implementations with local synthetic fixtures; public-network smoke tests are separate from deterministic CI. Proprietary instrument formats use explicit converter/plugin interfaces with tested supported formats.

## Domains and operation keys

1. io.table_import, io.text_import, io.pdf_import, io.image_import, io.instrument_import, io.database_import.
2. extract.pdf_text, extract.pdf_tables, extract.image_ocr, extract.image_tables, extract.chart_digitize, extract.convert_file.
3. Existing schema/missing/types/units/duplicates/outliers checks: add structure templates, semantic type inference, optional explicit unit conversion, similar-record matching without losing existing contracts.
4. preprocess.filter, preprocess.missing, preprocess.units, preprocess.reshape, preprocess.merge, preprocess.normalize.
5. materials.xrd, materials.spectra, materials.thermal, materials.mechanics, materials.sem_eds, materials.microstructure.
6. stats.grouped, stats.distribution, stats.correlation, stats.significance, stats.multiple, stats.regression, stats.predict, stats.evaluate.
7. viz.performance, viz.spectra, viz.mechanics, viz.statistics, export.table, export.report.
8. lit.search, lit.metadata, lit.extract, lit.compare, lit.sources, lit.summary.

## Acceptance

Requirement matrix maps all fifty entries and each listed submethod to operation, configuration, test and example. Run all original tests, new deterministic algorithm tests, native code-loader/discovery checks, portable connected flows covering every category, regular wheel install and real Langflow browser imports/runs. Verify artifacts by reading them back (table exports, images, report contents, serialized model predictions), not just checking a path exists. Complete external-data features with explicit input contracts and demonstration reference fixtures; absence of a production database/key is a deployment prerequisite, not implemented functionality.

Deliver install/run instructions for a computer beginner, a method/parameter reference, synthetic examples clearly labeled, external dependency instructions and a truthful capability matrix. Submit a feature PR to FDUStudyUI/StudyUI; do not claim all requirements fulfilled until implementation, tests and examples support the claim.

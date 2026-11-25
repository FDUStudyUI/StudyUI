# DNA Origami Nanogaps Workflow

This flow reproduces a descriptive analysis from the public source data for:

`Amplified Plasmonic Forces from DNA Origami-Scaffolded Single Dyes in Nanogaps`

- DOI: `10.1021/acs.nanolett.3c01016`
- Public repository handle: `1810/352700`
- License recorded by the source repository: `CC BY 4.0`

The JSON flow is self-contained. It embeds the four Figure 3 time-dependent SERS CSV files and verifies their SHA-256 hashes when the source node materializes them.

## Conditions

The condition code used by the workflow is:

| Code | Condition | Embedded file |
| --- | --- | --- |
| `0` | 0 Cy5 | `fig3_0cy5_time.csv` |
| `1` | 1 Cy3 | `fig3_1cy3_time.csv` |
| `2` | 1 Cy5 | `fig3_1cy5_time.csv` |
| `3` | 2 Cy5 | `fig3_2cy5_time.csv` |

Each source file contains 1,600 wavelength rows. The workflow clips the spectra to 550-850 nm, reshapes the six time columns (`0`, `30`, `60`, `90`, `120`, `150` s) to long form, and aggregates repeated wavelength samples before analysis.

## Node Route

1. Import the four measured CSV files with an explicit comma delimiter. The importer accepts the mixed CRLF/CR line endings present in the public files.
2. Filter the wavelength window and add the condition code.
3. Convert wide time columns to long form, coerce numeric types, and create one curve key per condition-time pair.
4. Append the four conditions and calculate wavelength-level and time-level descriptive summaries.
5. Run `BatchSpectrumAnalyzer` on 24 condition-time curves with linear baseline correction, a 650-850 nm lambda10 search window, and a 550-850 nm area range.
6. Run `SeriesDynamics` on the four condition-level time series.
7. Generate spectral-band, primary-area box, and time-scatter figures, plus feature CSV files and an HTML report.

The workflow deliberately leaves bootstrap and inferential significance testing disabled. The source package provides six analyzed curves per condition, but the package does not establish that these are independent biological replicates for a significance claim.

## Run

From the repository root on Windows:

```powershell
.\start_demo.bat --setup
.\start_demo.bat
```

The launcher preloads this flow together with the existing demo flows. Open the printed local URL, select **DNA origami scaffolded single dyes in nanogaps**, and run the graph from the final report node.

The run produces an HTML report, spectral and temporal feature CSV files, and publication-style PNG/PDF/SVG/TIFF figures in the runtime temporary output directory.

# Working paper

The paper is split by section so both authors can work without repeatedly
editing `main.tex`.

- Taji owns `sections/01_introduction.tex` and `sections/02_related_work.tex`.
- Noah owns the abstract and `sections/03_data_collection.tex` through
  `sections/09_conclusion.tex`.
- Put paper-ready plots in `figures/` and bibliography entries in
  `references.bib`.
- Keep `UF_FRED_paper_style.sty` unchanged.

Copy `UF_FRED_paper_style.sty` from the Overleaf project into this directory.
Then compile from this directory with:

```sh
tectonic main.tex
```

Write the abstract after the results and conclusion are stable. Remove all
remaining `TODO` and `OWNER` comments before submission.

# Working with data

Open the **Data** tab. The **Dataset** menu chooses which dataset node to look
at: *Raw input data* (the file as imported), *Cleaned data* (what the model
used), or any dataset a transform created. Every change you make creates a new
node next to the one you started from; nothing is edited in place.

## Data View

The rows, 100 at a time (**Previous** / **Next**), numbers shown to seven
significant digits. **Show value labels** switches coded columns between codes
(`1`, `2`) and their labels (`male`, `female`). Codes the variable declares as
missing are shown in italics, whether or not labels are on — in the GSS, `-100`
reads as *iap* (inapplicable).

## Variable View

One row per variable, as in SPSS:

| Column | What it holds |
|---|---|
| **Name**, **Type** | the column and its storage type |
| **Label** | the variable label, e.g. *Highest year of school completed* |
| **Values** | value labels, written `1 = Low; 2 = High` |
| **Measure** | *scale*, *ordinal* or *nominal* |
| **Missing** | declared missing codes, written `-99, 900..999` (a range with `..`) |
| **Sharing** | whether an AI provider may see this column's values ([Trust and records](05-trust.md#sharing-data-with-ai-providers)) |
| **Summary** | blanks, coded-missing and distinct values |

Edit any cell; the edits collect in **Review changes (n)**, and applying them
creates a new run with the new metadata — the old run keeps the old labels, so
results stay reproducible. Sharing levels are the exception: they are a
project setting and save at once.

Missing codes matter. A code declared missing is excluded from every
statistic, test and model, and each run reports how many values it excluded
per variable. SPSS files bring their codes with them; for CSV and Excel data,
declare them here (or ask the Agent: *treat 999 in hours as missing*).

## Transforms

**Transform…** in the Data tab covers the everyday operations:

| Operation | What it does |
|---|---|
| **Select rows** | keep rows meeting all conditions (`=`, `≠`, `>`, `≥`, `<`, `≤`, *between*, *is missing*, *is not missing*) |
| **Keep variables** | keep a subset of columns |
| **Recode into new variable** | SPSS `RECODE INTO`: values and ranges to new codes, with *else* and *missing* rules; the original column is kept |
| **Compute new variable** | `+`, `−`, `×`, `÷`, `ln( )` of existing columns |
| **Rename variable** | |
| **Remove duplicate rows** | rows identical on the columns you choose, keeping the first (the Agent can also keep the last) |
| **Fill missing values** | per column: mean, median, mode, a constant, or drop the rows |

Each shows a **Preview**, then creates a new dataset; *this one is not
changed*. The new dataset appears in the **Dataset** menu and in the graph.

More operations live on a dataset node in the **Graph** (click the node):

- **Data operation** — change column types (numeric, string, datetime), with a
  preview of what fails to convert.
- **Derived variable / recode** — add, subtract, multiply, ratio, log,
  interaction, recode.
- **Merge / append / reshape / subset** — with a second dataset, or reshaping
  wide to long and back.
- **Run code** — Python on the dataset in a sandbox with no network; the node's
  data is read-only and your result (`result`, a DataFrame) becomes a new node.
- **Run OLS from this data node** — fit a model on exactly this dataset.

Every transform is previewed, fingerprinted and confirmed before it runs, and
recorded in the analysis ledger. The Agent can do all of them from a sentence
(*keep respondents aged 25–55*); it shows you the change as a proposal first.
The complete list, with every field, is in the
[data operations reference](../reference/data-operations.md).

## Export

**Export…** in the Data tab (and **Export data** at the bottom of the Table
view) writes the current dataset node:

- **Format** — Stata `.dta`, SPSS `.sav` or compressed `.zsav`, CSV, Excel.
- **Stata version** — *14–18 (format 118)*, the default and what Stata 14–18
  save themselves; *13 (format 117, no Unicode)*; or *15–18, over 32,767
  variables (format 119)*.
- **File name** — optional.
- **Value labels** — *keep codes and label sets*, *write label text instead of
  codes*, or *codes only*.
- **Declared missing codes** — *write as missing* or *keep as values*.
- **Variables** and **Rows** — a subset of columns, and filters on rows.

**Preview** lists everything the chosen format cannot hold before you write
it — for example *256 value(s) matching −100 to −10 written as missing: Stata
has no user-missing codes*. SPSS keeps user-missing codes natively (up to three
codes, or one range and one code, per variable). **Export** downloads the file;
the dataset itself is unchanged.

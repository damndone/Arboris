"""Closed survey design values shared by metadata and execution."""

LONELY_PSU_POLICIES = ("fail", "remove", "adjust", "average", "certainty")
REPLICATE_TYPES = ("brr", "jackknife", "bootstrap", "provided")
#: Degrees of freedom for coefficient t tests and intervals. "design" is the
#: design df itself (#PSU - #strata): Korn-Graubard, and what Stata svy, SAS
#: SURVEYREG and SUDAAN use. "design_minus_p" also subtracts the parameters
#: (degf - p + 1), R survey's svyglm convention. The first is the default.
DF_CONVENTIONS = ("design", "design_minus_p")


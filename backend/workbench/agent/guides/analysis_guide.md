# Arboris analysis guide

These principles hold for every analysis in this Workbench: a two-variable
regression, a panel or difference-in-differences design, a survey estimate, a
time-series forecast, a trading-strategy backtest, or a machine-learning
model. Personal and project instructions refine them; where they disagree,
the more specific instruction wins. None of them relaxes the analysis-integrity
rules.

1. **Start from the question.** Name the target before the method: what is
   estimated or predicted (an effect, an association, a level, a forecast, a
   class, a risk), for which population or period, and whether the aim is
   description, prediction or causal explanation. These need different
   evidence; say which one an answer supports.

2. **Know the data before modelling it.** Unit of observation, sample and
   period, how the data were produced (survey design and weights, panel
   structure, time index and frequency, revisions), missingness and its likely
   mechanism, outliers, measurement levels and units. Inspect; never infer a
   variable's meaning from its name.

3. **Let the design choose the method.** Dependence decides inference
   (clusters, panels, serial correlation, heteroskedasticity, survey design);
   time order decides validation; the outcome's type decides the model
   family. State the assumptions a method needs, check the ones that can be
   checked, and report the diagnostics rather than assuming them.

4. **Validate for the goal.**
   - Inference: estimates with uncertainty (standard errors, intervals) under
     a stated covariance assumption; a p-value is not an effect size.
   - Prediction and machine learning: judge out of sample. Split before
     fitting anything that learns from the data (scaling, imputation, feature
     selection, tuning) and compare with a simple baseline.
   - Time series and quantitative research: respect time. Use only what was
     known at each moment (no look-ahead), evaluate walk-forward or on a
     rolling origin, and for strategies account for costs, slippage,
     survivorship and the number of variants tried.

5. **Count the tries.** Every specification, subsample, threshold or test
   tried is part of the result. Report multiplicity and robustness across
   reasonable alternatives, and report what failed as well as what worked.
   Never choose a specification because it is significant.

6. **Say what the numbers mean, and what they do not.** Association is not
   causation without an identification argument the data support. Keep units
   and scales as recorded. Separate statistical from practical significance.
   Name the limits: sample size and power, external validity, dependence on
   the model.

7. **Keep it reproducible.** Every result cites the run, model, step or
   artifact it came from. Changes to data or models go through reviewed
   proposals. Prefer steps the Workbench can re-run to one-off arithmetic.

8. **Be plain with the person.** Lead with the answer, then the evidence,
   then the caveats. When the question, the target or a variable's meaning is
   ambiguous, ask instead of guessing. Use the person's language and terms.

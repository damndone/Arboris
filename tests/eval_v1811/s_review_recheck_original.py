"""Re-execute frozen review tests with evidence redirected to a new directory."""
from pathlib import Path
import s_review_test_adversarial as original
import s_review_test_required_coverage as coverage

original.EVIDENCE = Path(__file__).with_name('s_review_recheck_evidence') / 'original'
for module in (original, coverage):
    for name, value in vars(module).items():
        if name.startswith('test_'):
            globals()[name] = value

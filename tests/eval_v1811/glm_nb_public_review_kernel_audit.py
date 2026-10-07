"""Audit actual retained HTTP kernels against fresh native R, using old tolerances."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np

HERE=Path(__file__).resolve().parent
native=json.loads((HERE/'glm_nb_public_review_native.json').read_text())['full_precision']
output=HERE/'glm_nb_public_review_kernel_metrics.json'
assert not output.exists()
rows=[]
for line in (HERE/'glm_nb_public_review_green.txt').read_text().splitlines():
    match=re.search(r'(\{"http_owner":.*\})',line)
    if not match:continue
    entry=json.loads(match.group(1));root=Path(entry['http_owner'])
    path=root/'model_results/inference_kernels/glm_1.json'
    kernel=json.loads(path.read_text())
    expected=native[str(entry['alpha']).removesuffix('.0')][entry['role']]
    beta=np.array([float(expected['beta']['(Intercept)' if name=='Intercept' else name])
        for name in kernel['param_names']])
    covariance=np.asarray(expected['covariance'],dtype=float)
    actual_covariance=np.asarray(kernel['vcov'],dtype=float)
    # Exact existing owner-reference acceptance: beta absolute 1e-8, SE absolute 1e-6.
    assert np.max(np.abs(np.asarray(kernel['params'])-beta)) <= 1e-8
    assert np.max(np.abs(np.sqrt(np.diag(actual_covariance))-np.sqrt(np.diag(covariance)))) <= 1e-6
    assert kernel['nobs']==int(expected['nobs'])
    assert kernel['covariance_estimator']=='nonrobust' and kernel['reference_distribution']=='z'
    rows.append({**entry,'kernel_sha256_after':hashlib.sha256(path.read_bytes()).hexdigest(),
        'beta_max_abs_difference':float(np.max(np.abs(np.asarray(kernel['params'])-beta))),
        'se_max_abs_difference':float(np.max(np.abs(np.sqrt(np.diag(actual_covariance))-np.sqrt(np.diag(covariance))))),
        'vcov_max_abs_difference_reported_only':float(np.max(np.abs(actual_covariance-covariance))),
        'native_score_over_n':float(expected['score_over_n']),
        'native_min_information_eigenvalue':float(expected['min_information_eigenvalue'])})
    assert rows[-1]['kernel_sha256_after']==entry['kernel_sha256']
assert len(rows)==6
output.write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n')
print(json.dumps({'http_kernel_count':len(rows),'max_beta_abs':max(row['beta_max_abs_difference'] for row in rows),
    'max_se_abs':max(row['se_max_abs_difference'] for row in rows),
    'max_native_score_over_n':max(row['native_score_over_n'] for row in rows)},allow_nan=False))

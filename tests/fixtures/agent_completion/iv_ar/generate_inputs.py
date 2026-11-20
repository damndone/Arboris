"""Deterministic raw rows; no fitted output is used to select inputs."""
from pathlib import Path
import numpy as np
import pandas as pd
root = Path(__file__).parent
rng = np.random.default_rng(20261020)
for q in range(1, 5):
    n = 120
    z = rng.integers(-8, 9, (n, q))
    w = rng.integers(-3, 4, n)
    u = rng.integers(-4, 5, n)
    x = z.sum(axis=1)+w+u
    e = rng.integers(-4, 5, n)*(1+abs(z[:, 0]))
    y = 1.5*x+2*w+e
    frame = pd.DataFrame({'y': y, 'x': x, 'w': w, **{f'z{j+1}': z[:, j] for j in range(q)}})
    frame.to_csv(root/f'q{q}.csv', index=False)
    if q == 2:
        frame['y'] = frame.y+12000*frame.x
        frame.to_csv(root/'distant.csv', index=False)

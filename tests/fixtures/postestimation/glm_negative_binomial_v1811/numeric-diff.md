# Fresh owner / native numeric comparison

| Quantity | Owner | Native | Absolute error | Relative error | Tolerance |
|---|---:|---:|---:|---:|---:|
| R coefficient Intercept | 0.52403339827549933 | 0.52403339827555395 | 5.462e-14 | 1.042e-13 | absolute 1e-08 |
| R SE Intercept | 0.16986251046239531 | 0.16986251046239487 | 4.441e-16 | 2.614e-15 | absolute 1e-06 |
| Stata coefficient Intercept | 0.52403339827549933 | 0.52403339827555417 | 5.485e-14 | 1.047e-13 | absolute 1e-08 |
| Stata SE Intercept | 0.16986251046239531 | 0.1698625104623952 | 1.11e-16 | 6.536e-16 | absolute 1e-06 |
| R coefficient x1 | 0.37889378683705344 | 0.37889378683709035 | 3.691e-14 | 9.743e-14 | absolute 1e-08 |
| R SE x1 | 0.075946638212289863 | 0.07594663821229021 | 3.469e-16 | 4.568e-15 | absolute 1e-06 |
| Stata coefficient x1 | 0.37889378683705344 | 0.37889378683709046 | 3.703e-14 | 9.772e-14 | absolute 1e-08 |
| Stata SE x1 | 0.075946638212289863 | 0.075946638212290196 | 3.331e-16 | 4.386e-15 | absolute 1e-06 |
| R coefficient x2 | -0.2889451515437183 | -0.28894515154376593 | 4.763e-14 | 1.648e-13 | absolute 1e-08 |
| R SE x2 | 0.065780418659816556 | 0.065780418659816847 | 2.914e-16 | 4.43e-15 | absolute 1e-06 |
| Stata coefficient x2 | -0.2889451515437183 | -0.28894515154376604 | 4.774e-14 | 1.652e-13 | absolute 1e-08 |
| Stata SE x2 | 0.065780418659816556 | 0.065780418659816833 | 2.776e-16 | 4.219e-15 | absolute 1e-06 |
| R coefficient x3 | -0.10121807811343853 | -0.10121807811349151 | 5.299e-14 | 5.235e-13 | absolute 1e-08 |
| R SE x3 | 0.14744903698769601 | 0.14744903698769615 | 1.388e-16 | 9.412e-16 | absolute 1e-06 |
| Stata coefficient x3 | -0.10121807811343853 | -0.10121807811349159 | 5.307e-14 | 5.243e-13 | absolute 1e-08 |
| Stata SE x3 | 0.14744903698769601 | 0.1474490369876964 | 3.886e-16 | 2.635e-15 | absolute 1e-06 |
| R wald_joint.statistic | 43.440653744956535 | 43.440653744966909 | 1.037e-11 | 2.388e-13 | relative 1e-06 |
| R wald_joint.p_value | 3.6896221611677756e-10 | 3.6896221611486429e-10 | 1.913e-21 | 5.186e-12 | relative 1e-05 |
| R wald_shifted.statistic | 10.745724600516064 | 10.745724600510435 | 5.629e-12 | 5.239e-13 | relative 1e-06 |
| R wald_shifted.p_value | 0.0010452050791135592 | 0.0010452050791167394 | 3.18e-15 | 3.043e-12 | relative 1e-05 |
| R lincom.estimate | -0.69899651625038317 | -0.69899651625044146 | 5.829e-14 | 8.339e-14 | relative 1e-06 |
| R lincom.std_error | 0.15076868785670133 | 0.15076868785670161 | 2.776e-16 | 1.841e-15 | relative 1e-06 |
| R nlcom.estimate | -1.3113000332858176 | -1.3113000332857292 | 8.837e-14 | 6.739e-14 | relative 1e-06 |
| R nlcom.std_error | 0.39432819176154726 | 0.39432819166511462 | 9.643e-11 | 2.445e-10 | relative 1e-06 |
| R lr_drop_x2_x3.statistic | 20.922503611121101 | 20.922503611121101 | 0 | 0 | relative 1e-06 |
| R lr_drop_x2_x3.loglik_full | -513.25643356734668 | -513.25643356734679 | 1.137e-13 | 2.215e-16 | relative 1e-06 |
| R lr_drop_x2_x3.loglik_restricted | -523.71768537290723 | -523.71768537290734 | 1.137e-13 | 2.171e-16 | relative 1e-06 |
| R lr_drop_x2_x3.p_value | 2.8624378573147222e-05 | 2.8624378573147229e-05 | 6.776e-21 | 2.367e-16 | relative 1e-05 |
| R margins.average.x1.estimate | 0.65174411263856158 | 0.65174411412307309 | 1.485e-09 | 2.278e-09 | relative 1e-06 |
| R margins.average.x1.std_error | 0.15148571731568122 | 0.15148571822274959 | 9.071e-10 | 5.988e-09 | relative 1e-05 |
| R margins.average.x2.estimate | -0.49702134987783086 | -0.49702135014477106 | 2.669e-10 | 5.371e-10 | relative 1e-06 |
| R margins.average.x2.std_error | 0.12705412459058169 | 0.12705412477458178 | 1.84e-10 | 1.448e-09 | relative 1e-05 |
| R margins.at_means.x1.estimate | 0.57304123609496838 | 0.57304123740021573 | 1.305e-09 | 2.278e-09 | relative 1e-06 |
| R margins.at_means.x1.std_error | 0.11678574791502931 | 0.1167857486671616 | 7.521e-10 | 6.44e-09 | relative 1e-05 |
| R margins.at_means.x2.estimate | -0.4370023804994943 | -0.43700238073434738 | 2.349e-10 | 5.374e-10 | relative 1e-06 |
| R margins.at_means.x2.std_error | 0.10080764078252001 | 0.1008076409375375 | 1.55e-10 | 1.538e-09 | relative 1e-05 |
| Stata wald_joint.statistic | 43.440653744956535 | 43.440653744966951 | 1.042e-11 | 2.398e-13 | relative 1e-06 |
| Stata wald_joint.p_value | 3.6896221611677756e-10 | 3.6896221611485643e-10 | 1.921e-21 | 5.207e-12 | relative 1e-05 |
| Stata wald_shifted.statistic | 10.745724600516064 | 10.745724600510423 | 5.642e-12 | 5.25e-13 | relative 1e-06 |
| Stata wald_shifted.p_value | 0.0010452050791135592 | 0.0010452050791167455 | 3.186e-15 | 3.048e-12 | relative 1e-05 |
| Stata lr_drop_x2_x3.statistic | 20.922503611121101 | 20.922503611121101 | 0 | 0 | relative 1e-06 |
| Stata lr_drop_x2_x3.p_value | 2.8624378573147222e-05 | 2.8624378573147212e-05 | 1.016e-20 | 3.551e-16 | relative 1e-05 |
| Stata lincom.estimate | -0.69899651625038317 | -0.69899651625044168 | 5.851e-14 | 8.37e-14 | relative 1e-06 |
| Stata lincom.std_error | 0.15076868785670133 | 0.15076868785670161 | 2.776e-16 | 1.841e-15 | relative 1e-06 |
| Stata nlcom.estimate | -1.3113000332858176 | -1.3113000332857292 | 8.837e-14 | 6.739e-14 | relative 1e-06 |
| Stata nlcom.std_error | 0.39432819176154726 | 0.39432819168420352 | 7.734e-11 | 1.961e-10 | relative 1e-06 |
| Stata margins.average.x1.estimate | 0.65174411263856158 | 0.65174411293709811 | 2.985e-10 | 4.581e-10 | relative 1e-06 |
| Stata margins.average.x1.std_error | 0.15148571731568122 | 0.15148571734241936 | 2.674e-11 | 1.765e-10 | relative 1e-05 |
| Stata margins.average.x2.estimate | -0.49702134987783086 | -0.49702135010552895 | 2.277e-10 | 4.581e-10 | relative 1e-06 |
| Stata margins.average.x2.std_error | 0.12705412459058169 | 0.12705412465561694 | 6.504e-11 | 5.119e-10 | relative 1e-05 |
| Stata margins.at_means.x1.estimate | 0.57304123609496838 | 0.57304123325593781 | 2.839e-09 | 4.954e-09 | relative 1e-06 |
| Stata margins.at_means.x1.std_error | 0.11678574791502931 | 0.11678574671662101 | 1.198e-09 | 1.026e-08 | relative 1e-05 |
| Stata margins.at_means.x2.estimate | -0.4370023804994943 | -0.43700237833447347 | 2.165e-09 | 4.954e-09 | relative 1e-06 |
| Stata margins.at_means.x2.std_error | 0.10080764078252001 | 0.10080763984550581 | 9.37e-10 | 9.295e-09 | relative 1e-05 |

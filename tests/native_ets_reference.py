def trend_fixture():
    seed = 570
    level, slope = 9.0, 0.8
    observed = []
    for _ in range(180):
        innovation = 0.0
        for _ in range(12):
            seed = seed * 16807 % 2147483647
            innovation += seed / 2147483647
        innovation -= 6.0
        mean = level + slope
        observed.append(mean + innovation)
        level = mean + 0.68 * innovation
        slope += 0.16 * innovation
    return observed

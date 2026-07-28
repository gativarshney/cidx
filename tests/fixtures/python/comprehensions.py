def collect(rows):
    cleaned = [normalize(r) for r in rows if valid(r)]
    totals = {k: compute(v) for k, v in pairs()}
    return chain(cleaned, totals)

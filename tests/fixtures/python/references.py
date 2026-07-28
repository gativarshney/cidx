def process(items):
    results = transform(items)
    return normalize(clean(results))


def transform(items):
    return [str(item) for item in items]

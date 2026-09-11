class SupportResistance:
    def __init__(self, tolerance=0.35):
        self.tolerance = tolerance

    def levels(self, highs, lows):
        prices = [p for _, p in highs] + [p for _, p in lows]

        prices.sort()

        clusters = []

        for p in prices:

            if not clusters:
                clusters.append([p])
                continue

            avg = sum(clusters[-1]) / len(clusters[-1])

            if abs(p - avg) <= self.tolerance:
                clusters[-1].append(p)
            else:
                clusters.append([p])

        levels = []

        for c in clusters:
            if len(c) >= 2:
                levels.append(sum(c) / len(c))

        return levels
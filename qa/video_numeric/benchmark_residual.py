"""Reproducible kernel benchmark against the previous np.median implementation."""
import argparse
import json
import platform
import statistics
import time

import numpy as np

if __package__:
    from .test_regressions import reference
    from .video_qa import neighborhood_residual
else:
    from test_regressions import reference
    from video_qa import neighborhood_residual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if min(args.width, args.height) < 3 or args.repeats < 1:
        parser.error('dimensions must be >= 3 and repeats >= 1')
    rgb = np.random.default_rng(42).integers(0, 65536, (args.height, args.width, 3), dtype=np.uint16)
    for old, new in zip(reference(rgb), neighborhood_residual(rgb)):
        np.testing.assert_array_equal(old, new)
    results = {'shape': list(rgb.shape), 'repeats': args.repeats, 'numpy': np.__version__,
               'platform': platform.platform(), 'exact_array_parity': True}
    for name, function in (('original', reference), ('optimized', neighborhood_residual)):
        times = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            function(rgb)
            times.append(time.perf_counter() - start)
        results[name] = {'seconds': times, 'median_seconds': statistics.median(times)}
    results['speedup'] = results['original']['median_seconds'] / results['optimized']['median_seconds']
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()

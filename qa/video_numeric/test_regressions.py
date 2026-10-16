"""Synthetic CLI regressions; no real-media accuracy claims."""
import csv
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

if __package__:
    from .video_qa import MEDIAN_NETWORK, evidence_quotas, neighborhood_residual
else:
    from video_qa import MEDIAN_NETWORK, evidence_quotas, neighborhood_residual

HERE = Path(__file__).parent


def encode(path, frames):
    height, width = frames.shape[1:3]
    result = subprocess.run([
        'ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb48le',
        '-video_size', f'{width}x{height}', '-framerate', '10', '-i', 'pipe:0',
        '-c:v', 'ffv1', '-pix_fmt', 'gbrp16le', str(path),
    ], input=frames.astype('<u2').tobytes(), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())


def reference(rgb):
    bright = np.zeros(rgb.shape[:2], np.float32)
    dark = bright.copy()
    for y in range(1, rgb.shape[0] - 1, 128):
        stop = min(y + 128, rgb.shape[0] - 1)
        neighbors = np.stack([
            rgb[y + dy:stop + dy, 1 + dx:rgb.shape[1] - 1 + dx]
            for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)
        ])
        residual = (rgb[y:stop, 1:-1].astype(np.float32) - np.median(neighbors, axis=0)) / 65535.0
        bright[y:stop, 1:-1] = np.max(residual, axis=2)
        dark[y:stop, 1:-1] = np.max(-residual, axis=2)
    return bright, dark


class Regressions(unittest.TestCase):
    def run_cli(self, source, out, *args):
        result = subprocess.run([
            sys.executable, str(HERE / 'video_qa.py'), str(source), '--out', str(out), *args,
        ], capture_output=True, text=True, timeout=60)
        return result, json.loads((out / 'report.json').read_text()) if (out / 'report.json').exists() else None

    def test_network_all_orderings_and_binary_ties(self):
        for values in (list(itertools.permutations(range(8))), list(itertools.product((0, 65535), repeat=8))):
            data = np.array(values, dtype=np.uint16).T.copy()
            expected = np.sort(data, axis=0)
            for left, right in MEDIAN_NETWORK:
                low = np.minimum(data[left], data[right])
                data[right] = np.maximum(data[left], data[right])
                data[left] = low
            np.testing.assert_array_equal(data, expected)

    def test_residual_exact_parity_and_no_mutation(self):
        rng = np.random.default_rng(42)
        for shape in ((3, 3, 3), (21, 33, 3), (131, 41, 3), (259, 37, 3)):
            rgb = rng.integers(0, 65536, shape, dtype=np.uint16)
            before = rgb.copy()
            for old, new in zip(reference(rgb), neighborhood_residual(rgb)):
                np.testing.assert_array_equal(new, old)
            np.testing.assert_array_equal(rgb, before)

    def test_quota_totals_for_all_modules_and_small_limits(self):
        for modules, count in (('all', 4), ('pixels', 2), ('clipping', 2)):
            for limit in range(10):
                quotas = evidence_quotas(limit, modules)
                self.assertEqual(sum(quotas.values()), limit)
                self.assertEqual(len(quotas), count)
                self.assertLessEqual(max(quotas.values()) - min(quotas.values()), 1)

    def test_late_kinds_keep_reserved_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            frames = np.full((8, 24, 32, 3), 32768, dtype='<u2')
            for i in range(8):
                frames[i, 4, 3 + i * 3] = 60000
            frames[4:, 14, 8] = 5000
            frames[5:, 18, 20] = 0
            frames[6:, 18, 26] = 65535
            source = root / 'source.mkv'
            encode(source, frames)
            result, report = self.run_cli(source, root / 'out', '--min-frames', '1', '--min-seconds', '0', '--max-crops', '4')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({e['kind'] for e in report['evidence']}, {'bright', 'dark', 'shadow', 'highlight'})
            self.assertEqual(len(report['evidence']), 4)

    def test_module_branches_and_interval_bounds(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            frames = np.full((6, 21, 33, 3), 32768, dtype='<u2')
            frames[1:4, 5, 5] = 65535
            source = root / 'source.mkv'
            encode(source, frames)
            for module in ('pixels', 'clipping', 'all'):
                out = root / module
                result, report = self.run_cli(source, out, '--modules', module, '--max-crops', '0')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(report['frames_processed'], 6)
                self.assertEqual(report['evidence'], [])
                self.assertEqual(bool(report['pixel_summary']), module != 'clipping')
                self.assertEqual(bool(report['clipping_summary']), module != 'pixels')
                with (out / 'clipping_intervals.csv').open() as f:
                    rows = list(csv.DictReader(f))
                if module == 'pixels':
                    self.assertEqual(rows, [])
                else:
                    self.assertEqual(len(rows), 4)
                    for row in rows:
                        self.assertEqual((row['start_frame_0based'], row['end_frame_exclusive']), ('1', '4'))
                        self.assertAlmostEqual(float(row['start_pts_seconds']), .1)
                        self.assertAlmostEqual(float(row['end_pts_seconds_exclusive']), .4)

    def test_vfr_actual_timestamps(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'vfr.mkv'
            cmd = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=32x24:rate=25',
                   '-frames:v', '5', '-vf', "setpts='if(eq(N,0),0,if(eq(N,1),3,if(eq(N,2),11,if(eq(N,3),28,34))))'",
                   '-fps_mode', 'passthrough', '-c:v', 'ffv1', str(source)]
            subprocess.run(cmd, check=True, capture_output=True)
            result, report = self.run_cli(source, root / 'out', '--modules', 'clipping')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report['timestamp_fallbacks'], 0)
            with (root / 'out/clipping_frames.csv').open() as f:
                rows = [r for r in csv.DictReader(f) if r['kind'] == 'shadow' and r['channel'] == 'R']
            np.testing.assert_allclose([float(r['pts_seconds']) for r in rows], [0, .12, .44, 1.12, 1.36])

    def test_truncated_input_is_not_complete(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'source.mkv'
            frames = np.random.default_rng(3).integers(0, 65536, (20, 24, 32, 3), dtype=np.uint16)
            encode(source, frames)
            broken = root / 'broken.mkv'
            raw = source.read_bytes()
            broken.write_bytes(raw[:len(raw) // 2])
            result, report = self.run_cli(broken, root / 'out')
            self.assertNotEqual(result.returncode, 0)
            if report is not None:
                self.assertIn(report['status'], ('partial_failure', 'failed'))
                self.assertTrue(report['errors'])

    def test_resolution_change_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            parts = []
            for index, size in enumerate(('32x24', '48x32')):
                part = root / f'{index}.ts'
                subprocess.run([
                    'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=10',
                    '-frames:v', '4', '-c:v', 'mpeg2video', '-f', 'mpegts', str(part),
                ], check=True, capture_output=True)
                parts.append(part.read_bytes())
            source = root / 'changing.ts'
            source.write_bytes(b''.join(parts))
            result, report = self.run_cli(source, root / 'out')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(report['status'], 'partial_failure')
            self.assertTrue(any('resolution change' in error for error in report['errors']))

    def test_limited_yuv_near_white_is_not_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'limited.mkv'
            y = np.full((16, 16), 940, dtype='<u2')
            uv = np.full((8, 8), 512, dtype='<u2')
            cmd = ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'yuv420p10le',
                   '-video_size', '16x16', '-framerate', '10', '-i', 'pipe:0', '-color_range', 'tv',
                   '-colorspace', 'bt709', '-c:v', 'ffv1', str(source)]
            subprocess.run(cmd, input=(y.tobytes() + uv.tobytes() * 2) * 2, check=True, capture_output=True)
            reports = []
            for preset in ('endpoints', 'near-endpoints'):
                result, report = self.run_cli(source, root / preset, '--modules', 'clipping', '--threshold-preset', preset)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(report['source_metadata']['streams'][0]['color_range'], 'tv')
                reports.append(report)
            self.assertEqual(reports[1]['clipping_summary']['highlight_ANY']['pixel_frame_count'], 512)
            # Conversion rounding varies across FFmpeg builds; no fixed 940->RGB assumption.
            self.assertLessEqual(reports[0]['clipping_summary']['highlight_ANY']['pixel_frame_count'], 512)


if __name__ == '__main__':
    unittest.main()

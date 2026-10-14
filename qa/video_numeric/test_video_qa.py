import csv, json, subprocess, sys, tempfile, unittest
from pathlib import Path
import numpy as np
from video_qa import neighborhood_residual
HERE=Path(__file__).parent

def fixture(path):
    frames=np.full((12,24,32,3),32768,dtype='<u2')
    frames[:,6,7]=65535; frames[:,12,13]=0
    frames[:2,8,9]=65535  # transient, must not qualify
    frames[:,4:8,20:24]=65535 # stationary object, corners are ambiguous candidates
    frames[:,16,17]=[65535,32768,32768] # channel-specific saturation
    p=subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','rgb48le','-video_size','32x24','-framerate','10','-i','pipe:0','-c:v','ffv1','-pix_fmt','gbrp16le',str(path)],input=frames.tobytes(),capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.decode())
    return frames

class Tests(unittest.TestCase):
    def test_streaming_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'source.mkv';fixture(src); before=src.read_bytes();out=d/'output'
            p=subprocess.run([sys.executable,str(HERE/'video_qa.py'),str(src),'--out',str(out),'--min-frames','5','--min-seconds','0.4'],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr+p.stdout)
            report=json.loads((out/'report.json').read_text());self.assertEqual(report['frames_processed'],12);self.assertEqual(report['status'],'complete')
            events=list(csv.DictReader((out/'pixel_intervals.csv').read_text().splitlines()))
            coords={(r['kind'],int(r['x']),int(r['y'])) for r in events}
            self.assertIn(('bright',7,6),coords);self.assertIn(('dark',13,12),coords);self.assertNotIn(('bright',9,8),coords)
            hot=next(r for r in events if r['kind']=='bright' and r['x']=='7' and r['y']=='6');self.assertAlmostEqual(float(hot['duration_seconds']),1.2)
            rows=list(csv.DictReader((out/'clipping_frames.csv').read_text().splitlines()));red=next(r for r in rows if r['kind']=='highlight' and r['channel']=='R');green=next(r for r in rows if r['kind']=='highlight' and r['channel']=='G')
            self.assertEqual(int(red['pixel_count']),int(green['pixel_count'])+1)
            self.assertAlmostEqual(float(red['coverage_fraction']),int(red['pixel_count'])/(24*32))
            self.assertTrue(report['evidence']);self.assertEqual(src.read_bytes(),before)
            retry=subprocess.run([sys.executable,str(HERE/'video_qa.py'),str(src),'--out',str(out)],capture_output=True);self.assertNotEqual(retry.returncode,0)
    def test_static_object_ambiguity(self):
        rgb=np.full((10,10,3),32768,dtype=np.uint16);rgb[3:6,3:6]=65535
        bright,_=neighborhood_residual(rgb)
        self.assertGreater(bright[3,3],0.25) # proves stationary sharp details can trigger
    def test_zero_pixel_delta_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);src=d/'source.mkv';fixture(src)
            p=subprocess.run([sys.executable,str(HERE/'video_qa.py'),str(src),'--out',str(d/'out'),'--pixel-delta','0'],capture_output=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse((d/'out').exists())
    def test_missing_input_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=subprocess.run([sys.executable,str(HERE/'video_qa.py'),str(Path(d)/'missing.mov'),'--out',str(Path(d)/'out')],capture_output=True)
            self.assertNotEqual(p.returncode,0)

if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Read-only, frame-streaming decoded-video QA. See README.md before interpreting results."""
import argparse, csv, json, math, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image


def probe(path):
    p = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-show_format','-of','json',str(path)], capture_output=True, text=True)
    if p.returncode: raise RuntimeError('ffprobe failed: '+p.stderr[-4000:])
    data = json.loads(p.stdout)
    if not data.get('streams'): raise ValueError('No first video stream found')
    return data


def fraction(value):
    x=float(value)
    if not 0 <= x <= 1: raise argparse.ArgumentTypeError('must be between 0 and 1')
    return x


def fps_of(stream):
    for key in ('avg_frame_rate','r_frame_rate'):
        try:
            a,b=stream[key].split('/'); value=float(a)/float(b)
            if math.isfinite(value) and value>0: return value
        except (KeyError, ValueError, ZeroDivisionError): pass
    return None


MEDIAN_NETWORK = (
    (0, 1), (2, 3), (4, 5), (6, 7),
    (0, 2), (1, 3), (4, 6), (5, 7), (1, 2), (5, 6),
    (0, 4), (3, 7), (1, 5), (2, 6),
    (1, 4), (3, 6), (2, 4), (3, 5), (3, 4),
)


def evidence_quotas(limit, modules):
    """Reserve each enabled kind a share; the total never exceeds limit."""
    kinds = []
    if modules != 'clipping':
        kinds.extend(('bright', 'dark'))
    if modules != 'pixels':
        kinds.extend(('shadow', 'highlight'))
    share, remainder = divmod(limit, len(kinds))
    return {kind: share + (index < remainder) for index, kind in enumerate(kinds)}


def neighborhood_residual(rgb):
    """Per-channel center minus median of eight neighbors; outer border is excluded."""
    bright=np.zeros(rgb.shape[:2],np.float32); dark=bright.copy()
    for y in range(1,rgb.shape[0]-1,128):
        stop=min(y+128,rgb.shape[0]-1)
        neighbors=np.stack([rgb[y+dy:stop+dy,1+dx:rgb.shape[1]-1+dx] for dy in (-1,0,1) for dx in (-1,0,1) if (dy,dx)!=(0,0)])
        # Exact eight-input sorting network. Keep the even median in float64,
        # matching np.median(uint16) without overflow or threshold drift.
        scratch = np.empty_like(neighbors[0])
        for left, right in MEDIAN_NETWORK:
            np.minimum(neighbors[left], neighbors[right], out=scratch)
            np.maximum(neighbors[left], neighbors[right], out=neighbors[right])
            neighbors[left] = scratch
        median = (neighbors[3].astype(np.float64) + neighbors[4]) * 0.5
        residual=(rgb[y:stop,1:-1].astype(np.float32)-median)/65535.0
        bright[y:stop,1:-1]=np.max(residual,axis=2)
        dark[y:stop,1:-1]=np.max(-residual,axis=2)
    return bright,dark


class PixelTrack:
    def __init__(self,shape,kind,writer,min_frames,min_seconds):
        self.kind,self.writer,self.min_frames,self.min_seconds=kind,writer,min_frames,min_seconds
        self.count=np.zeros(shape,np.uint32); self.run=np.zeros(shape,np.uint32)
        self.start=np.zeros(shape,np.float64); self.start_frame=np.zeros(shape,np.int64)
        self.longest=np.zeros(shape,np.float32); self.eligible=np.zeros(shape,bool)
        self.events=0
        self.cropped=set()
    def finish(self,mask,end):
        qualified=mask & (self.run>=self.min_frames) & ((end-self.start+1e-9)>=self.min_seconds)
        ys,xs=np.nonzero(qualified)
        for y,x in zip(ys,xs):
            self.writer.writerow([self.kind,int(x),int(y),int(self.start_frame[y,x]),int(self.run[y,x]),float(self.start[y,x]),float(end),float(end-self.start[y,x])])
        self.events+=len(xs)
        self.run[mask]=0
    def update(self,mask,frame,t,end):
        self.finish((~mask)&(self.run>0),t)
        new=mask&(self.run==0); self.start[new]=t; self.start_frame[new]=frame
        self.run[mask]+=1; self.count[mask]+=1
        duration=np.where(mask,end-self.start,0)
        self.longest=np.maximum(self.longest,duration).astype(np.float32)
        qualified=mask&(self.run>=self.min_frames)&(duration+1e-9>=self.min_seconds)
        self.eligible|=qualified
        return qualified


def heatmap(values,path):
    v=np.clip(values,0,1)
    # Red/yellow scale: zero black, one yellow-white. PNG is visual; NPY holds numeric map.
    rgb=np.stack([np.minimum(1,v*2),v,np.maximum(0,v*2-1)],axis=-1)
    Image.fromarray((rgb*255).astype('uint8')).save(path)


def read_exact(pipe,size):
    chunks=[]; left=size
    while left:
        chunk=pipe.read(left)
        if not chunk: break
        chunks.append(chunk); left-=len(chunk)
    return b''.join(chunks)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path); ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--modules',choices=['all','pixels','clipping'],default='all')
    ap.add_argument('--pixel-delta',type=fraction,default=0.25,help='UNCalibrated local residual threshold, fraction of full decoded RGB range; any channel')
    ap.add_argument('--min-frames',type=int,default=8,help='minimum consecutive candidate frames (default 8, uncalibrated)')
    ap.add_argument('--min-seconds',type=float,default=0.2,help='minimum consecutive duration; BOTH frame and duration minima required')
    ap.add_argument('--threshold-preset',choices=['endpoints','near-endpoints'],default='endpoints',help='on full-range decoded RGB: endpoints 0/1; near-endpoints 0.01/0.99; neither measures source YUV legal-range compliance')
    ap.add_argument('--shadow-threshold',type=fraction,help='inclusive <= threshold; overrides range preset')
    ap.add_argument('--highlight-threshold',type=fraction,help='inclusive >= threshold; overrides range preset')
    ap.add_argument('--clip-min-pixels',type=int,default=1,help='per-channel minimum clipped pixels to enter an interval')
    ap.add_argument('--max-crops',type=int,default=24); ap.add_argument('--crop-radius',type=int,default=16)
    args=ap.parse_args(argv)
    if args.min_frames<1 or args.min_seconds<0 or not math.isfinite(args.min_seconds) or args.clip_min_pixels<1 or args.max_crops<0 or args.crop_radius<0: ap.error('invalid nonpositive count or duration')
    if args.pixel_delta<=0: ap.error('--pixel-delta must be greater than zero')
    source=args.input.expanduser().resolve(strict=True); out=args.out.expanduser().resolve()
    if not source.is_file(): ap.error('input must be a regular file')
    if out.exists(): ap.error('--out must be a new directory; existing outputs are never overwritten')
    meta=probe(source); stream=meta['streams'][0]; w,h=stream['width'],stream['height']; fps=fps_of(stream)
    if w<3 or h<3: ap.error('minimum frame size is 3x3')
    shadow=args.shadow_threshold if args.shadow_threshold is not None else (0 if args.threshold_preset=='endpoints' else 0.01)
    highlight=args.highlight_threshold if args.highlight_threshold is not None else (1 if args.threshold_preset=='endpoints' else 0.99)
    if shadow>=highlight: ap.error('shadow threshold must be below highlight threshold')
    out.mkdir(parents=True); (out/'evidence').mkdir()
    report={'status':'running','input':str(source),'width':w,'height':h,'frames_processed':0,'source_metadata':meta,
        'configuration':{**vars(args),'input':str(source),'out':str(out),'effective_shadow_threshold':shadow,'effective_highlight_threshold':highlight},
        'pipeline':{'analysis':'first video stream, original dimensions, no autorotation, every decoded frame, RGB48LE, full-range RGB','decode_precision':'16-bit container; does not imply 16-bit source precision','transfer':'encoded/nonlinear RGB; no linearization or tone mapping','color_conversion':'FFmpeg swscale to full-range RGB; tagged/default matrix interpretation, no ICC management'},
        'warnings':['Thresholds are uncalibrated screening defaults.','Persistent local outliers are candidates, not diagnosed defective sensor pixels. Fixed scene details and registration/stabilization can be indistinguishable. Prefer unstabilized footage with scene motion.','Clipping means decoded RGB threshold occupancy, NOT proof of sensor clipping.','Endpoint occupancy can undercount YUV white after RGB conversion/rounding. Optional near-white thresholds (e.g. 0.99) measure near-white occupancy, not source-code clipping.', 'VFR heatmap fractions and mean coverage are frame-weighted, not duration-weighted.', 'Outer one-pixel border excluded from pixel candidate detection.','Evidence PNGs are 8-bit display previews; numeric analysis is RGB48.'], 'timestamp_fallbacks':0,'evidence':[]}
    for key in ('color_range','color_space','color_transfer','color_primaries'):
        if stream.get(key) in (None,'unknown','unspecified'): report['warnings'].append('Source '+key+' missing/unknown; decoded color interpretation is not calibrated.')
    if stream.get('color_transfer') in ('smpte2084','arib-std-b67'): report['warnings'].append('HDR transfer is retained; thresholds do not measure scene luminance or display clipping.')
    files=[]; processes=[]; tracks=[]; clipping_states={}; previous_t=None; n=0; end=0.; crop_count=0
    def csvfile(name,header):
        f=(out/name).open('w',newline=''); files.append(f); writer=csv.writer(f);writer.writerow(header);return writer
    pixelwriter=csvfile('pixel_intervals.csv',['kind','x','y','start_frame_0based','consecutive_frames','start_pts_seconds','end_pts_seconds_exclusive','duration_seconds'])
    clipwriter=csvfile('clipping_frames.csv',['frame_0based','pts_seconds','end_pts_seconds_exclusive','kind','channel','pixel_count','coverage_fraction','bbox_x0','bbox_y0','bbox_x1_exclusive','bbox_y1_exclusive'])
    clipintervals=csvfile('clipping_intervals.csv',['kind','channel','start_frame_0based','end_frame_exclusive','start_pts_seconds','end_pts_seconds_exclusive','peak_coverage_fraction'])
    clipcounts={k:np.zeros((h,w),np.uint32) for k in ('shadow','highlight')} if args.modules!='pixels' else {}
    if args.modules!='clipping': tracks=[PixelTrack((h,w),k,pixelwriter,args.min_frames,args.min_seconds) for k in ('bright','dark')]
    errors=[]; clip_evidence=set(); clip_summary={}
    crop_quotas=evidence_quotas(args.max_crops,args.modules)
    crop_used={kind:0 for kind in crop_quotas}
    report['evidence_quotas']=crop_quotas
    with tempfile.TemporaryFile() as decode_errors, tempfile.TemporaryFile() as timestamp_errors:
        try:
            decoder=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-noautorotate','-i',str(source),'-map','0:v:0','-an','-sn','-dn','-vf','scale=in_range=auto:out_range=full','-fps_mode','passthrough','-pix_fmt','rgb48le','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=decode_errors);processes.append(decoder)
            timestamps=subprocess.Popen(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=media_type,width,height,best_effort_timestamp_time,pkt_duration_time','-of','compact=p=0:nk=0',str(source)],stdout=subprocess.PIPE,stderr=timestamp_errors,text=True);processes.append(timestamps)
            def next_frame():
                nonlocal previous_t
                raw=read_exact(decoder.stdout,w*h*6)
                if not raw:return None
                if len(raw)!=w*h*6: raise RuntimeError('Truncated decoded frame')
                fields={}
                for line in timestamps.stdout:
                    candidate=dict(part.split('=',1) for part in line.strip().split('|') if '=' in part)
                    if candidate.get('media_type')=='video':fields=candidate;break
                if fields and (int(fields.get('width',w))!=w or int(fields.get('height',h))!=h):
                    raise RuntimeError('Mid-stream resolution change is unsupported; split into constant-resolution clips first')
                try:
                    t=float(fields['best_effort_timestamp_time'])
                    if not math.isfinite(t) or (previous_t is not None and t<=previous_t):raise ValueError()
                except (KeyError,ValueError):
                    if not fps:raise RuntimeError('Missing/nonmonotonic timestamp and no usable nominal frame rate')
                    t=0. if previous_t is None else previous_t+1/fps;report['timestamp_fallbacks']+=1
                previous_t=t
                try:
                    dt=float(fields['pkt_duration_time']);dt=dt if math.isfinite(dt) and dt>0 else None
                except (KeyError,ValueError):dt=None
                return np.frombuffer(raw,dtype='<u2').reshape(h,w,3),t,dt
            current=next_frame()
            while current is not None:
                following=next_frame();rgb,t,dt=current
                if following is not None:end=following[1]
                elif dt:end=t+dt
                elif fps:end=t+1/fps;report['warnings'].append('Final frame duration estimated from nominal frame rate.')
                else:raise RuntimeError('Final frame duration unavailable')
                if n==0:report['first_pts_seconds']=t
                if tracks:
                    residuals=neighborhood_residual(rgb)
                    for tracker,residual in zip(tracks,residuals):
                        candidate=residual>=args.pixel_delta
                        candidate[0,:]=False;candidate[-1,:]=False;candidate[:,0]=False;candidate[:,-1]=False
                        qualified=tracker.update(candidate,n,t,end)
                        if crop_used[tracker.kind]<crop_quotas[tracker.kind]:
                            # One crop per kind/frame; suppress repeated coordinates across frames.
                            ys,xs=np.nonzero(qualified)
                            for y,x in zip(ys,xs):
                                if (int(y),int(x)) in tracker.cropped:continue
                                tracker.cropped.add((int(y),int(x)));r=args.crop_radius
                                box=[max(0,int(x)-r),max(0,int(y)-r),min(w,int(x)+r+1),min(h,int(y)+r+1)]
                                name=f'evidence/{crop_count:03d}_{tracker.kind}_f{n}_x{x}_y{y}.png'
                                Image.fromarray((rgb[box[1]:box[3],box[0]:box[2]]>>8).astype('uint8')).save(out/name)
                                report['evidence'].append({'file':name,'kind':tracker.kind,'frame':n,'pts_seconds':t,'x':int(x),'y':int(y),'crop_xyxy':box});crop_count+=1;crop_used[tracker.kind]+=1;break
                for kind,threshold in (('shadow',shadow),('highlight',highlight)) if clipcounts else []:
                    mask=(rgb.astype(np.float32)/65535<=threshold) if kind=='shadow' else (rgb.astype(np.float32)/65535>=threshold)
                    anymask=np.any(mask,axis=2);clipcounts[kind]+=anymask
                    for channel,m in list(zip('RGB',np.moveaxis(mask,2,0)))+[('ANY',anymask)]:
                        count=int(np.count_nonzero(m));coverage=count/(w*h)
                        xs=np.flatnonzero(np.any(m,axis=0));ys=np.flatnonzero(np.any(m,axis=1))
                        bbox=[int(xs[0]),int(ys[0]),int(xs[-1])+1,int(ys[-1])+1] if count else ['','','','']
                        clipwriter.writerow([n,t,end,kind,channel,count,coverage]+bbox);key=(kind,channel)
                        summary=clip_summary.setdefault(kind+'_'+channel,{'pixel_frame_count':0,'peak_coverage_fraction':0})
                        summary['pixel_frame_count']+=count;summary['peak_coverage_fraction']=max(summary['peak_coverage_fraction'],coverage)
                        if channel=='ANY' and count and kind not in clip_evidence and crop_used[kind]<crop_quotas[kind]:
                            clip_evidence.add(kind);y=int(ys[0]);x=int(np.flatnonzero(m[y])[0]);r=args.crop_radius
                            box=[max(0,x-r),max(0,y-r),min(w,x+r+1),min(h,y+r+1)]
                            name=f'evidence/{crop_count:03d}_{kind}_f{n}_x{x}_y{y}.png'
                            Image.fromarray((rgb[box[1]:box[3],box[0]:box[2]]>>8).astype('uint8')).save(out/name)
                            report['evidence'].append({'file':name,'kind':kind,'frame':n,'pts_seconds':t,'x':x,'y':y,'crop_xyxy':box});crop_count+=1;crop_used[kind]+=1
                        if count>=args.clip_min_pixels:
                            if key not in clipping_states:clipping_states[key]=[n,t,coverage]
                            clipping_states[key][2]=max(clipping_states[key][2],coverage)
                        elif key in clipping_states:
                            start,ts,peak=clipping_states.pop(key);clipintervals.writerow([kind,channel,start,n,ts,t,peak])
                n+=1;report['frames_processed']=n;report['end_pts_seconds_exclusive']=end
                current=following
            if decoder.wait()!=0:errors.append('ffmpeg decoding failed')
            extra_timestamps=sum(1 for line in timestamps.stdout if 'media_type=video' in line)
            if extra_timestamps:errors.append(f'{extra_timestamps} timestamp records had no decoded frame')
            if timestamps.wait()!=0:errors.append('ffprobe frame timestamp extraction failed')
            if n==0:errors.append('No frames decoded')
            expected=stream.get('nb_frames')
            if expected and expected.isdigit() and n!=int(expected):errors.append(f'Decoded frame count {n} differs from declared nb_frames {expected}')
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
        finally:
            for proc in processes:
                if proc.poll() is None:proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                if proc.stdout:proc.stdout.close()
            for log,name in ((decode_errors,'ffmpeg'),(timestamp_errors,'ffprobe')):
                log.seek(0,2);size=log.tell();log.seek(max(0,size-8000));tail=log.read().decode(errors='replace')
                if tail:report[name+'_stderr_tail']=tail;errors.append(name+' reported decoding errors; inspect stderr tail')
    for tracker in tracks:
        tracker.finish(tracker.run>0,end)
        np.save(out/(tracker.kind+'_candidate_frame_fraction.npy'),tracker.count/max(n,1));np.save(out/(tracker.kind+'_longest_run_seconds.npy'),tracker.longest)
        heatmap(tracker.count/max(n,1),out/(tracker.kind+'_persistence.png'))
    for kind,counts in clipcounts.items():
        np.save(out/(kind+'_frame_fraction.npy'),counts/max(n,1));heatmap(counts/max(n,1),out/(kind+'_occupancy.png'))
    for (kind,channel),(start,ts,peak) in clipping_states.items():clipintervals.writerow([kind,channel,start,n,ts,end,peak])
    for f in files:f.close()
    for summary in clip_summary.values():summary['mean_coverage_fraction']=summary['pixel_frame_count']/max(n*w*h,1)
    report['clipping_summary']=clip_summary
    report['pixel_summary']={tr.kind:{'qualifying_coordinates':int(tr.eligible.sum()),'intervals':tr.events} for tr in tracks}
    report['status']='partial_failure' if errors and n else 'failed' if errors else 'complete';report['errors']=errors
    if report['timestamp_fallbacks']:report['warnings'].append('Some timestamps synthesized from nominal frame rate; do not treat those timings as exact.')
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':report['status'],'frames_processed':n,'report':str(out/'report.json')}))
    return 2 if errors else 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError) as exc:print(str(exc),file=sys.stderr);sys.exit(2)

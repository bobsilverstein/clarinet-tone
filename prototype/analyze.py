import numpy as np, librosa, soundfile as sf, json, sys
f,out,mindur=sys.argv[1],sys.argv[2],float(sys.argv[3])
y,sr=sf.read(f,dtype='float32'); print(sf.info(f).subtype, len(y)/sr/60,'min')
yr=librosa.resample(y,orig_sr=sr,target_sr=22050); s2=22050; hop=256
F=[];V=[];C=s2*30//hop*hop
for s in range(0,len(yr),C):
    seg=yr[s:s+C+2048]
    f0,vf,_=librosa.pyin(seg,fmin=120,fmax=1800,sr=s2,frame_length=2048,hop_length=hop,center=False)
    k=C//hop if s+C<len(yr) else len(f0); F.append(f0[:k]);V.append(vf[:k])
f0=np.concatenate(F);vf=np.concatenate(V)
db=20*np.log10(librosa.feature.rms(y=yr,frame_length=2048,hop_length=hop,center=False)[0]+1e-9)
n=min(len(f0),len(db));f0=f0[:n];vf=vf[:n];db=db[:n]; ht=hop/s2
np.savez(out+'.npz',f0=f0,vf=vf,db=db,hop=ht)
semi=np.round(librosa.hz_to_midi(np.where(vf&(db>-40),f0,np.nan)))
notes=[];i=0
while i<n:
    if np.isnan(semi[i]): i+=1; continue
    j=i;gap=0
    while j+1<n:
        if semi[j+1]==semi[i]: j+=1;gap=0
        elif np.isnan(semi[j+1]) and gap<4: j+=1;gap+=1
        else: break
    t0=i*ht;t1=(j+1)*ht
    if t1-t0>=mindur:
        m=int(semi[i]); a=t0+0.2*(t1-t0); b=t0+0.8*(t1-t0)
        x=y[int(a*sr):int(b*sr)]
        p=librosa.yin(x,fmin=librosa.midi_to_hz(m-0.7),fmax=librosa.midi_to_hz(m+0.7),sr=sr,frame_length=4096,hop_length=480)
        c=(librosa.hz_to_midi(p)-m)*100
        # pitch trend over whole held note (for sag): thirds
        xx=y[int((t0+0.1)*sr):int((t1-0.05)*sr)]
        pp=librosa.yin(xx,fmin=librosa.midi_to_hz(m-0.7),fmax=librosa.midi_to_hz(m+0.7),sr=sr,frame_length=4096,hop_length=480)
        cc=(librosa.hz_to_midi(pp)-m)*100; th=np.array_split(cc,3)
        L=20*np.log10(librosa.feature.rms(y=x,frame_length=2048,hop_length=480)[0]+1e-9)
        notes.append(dict(t=t0,end=t1,dur=t1-t0,m=m,w=librosa.midi_to_note(m+2,unicode=False),cents=float(np.median(c)),wob=float(np.std(c)),
          db=float(np.median(L)),dbsd=float(np.std(L)),thirds=[float(np.median(q)) for q in th]))
    i=j+1
json.dump(notes,open(out+'.json','w'))
for x in notes: print(f"{x['t']:6.1f}s {x['dur']:4.1f}s {x['w']:4s} {x['cents']:+4.0f}c wob{x['wob']:5.1f} {x['db']:6.1f}dB thirds {' '.join(f'{q:+.0f}' for q in x['thirds'])}")

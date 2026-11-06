import numpy as np, librosa, soundfile as sf, json
d=np.load('track.npz'); f0=d['f0']; vf=d['vf']; hop=float(d['hop'])
y,sr=sf.read("/mnt/user-data/uploads/Clarinet tone/Recordings/2026-11-05_1731_reed-0804_1_long-tone.wav",dtype='float32')
yr=librosa.resample(y,orig_sr=sr,target_sr=22050); sr2=22050
rms=librosa.feature.rms(y=yr,frame_length=2048,hop_length=256)[0]; db=20*np.log10(rms+1e-9)
n=min(len(f0),len(db)); f0=f0[:n];vf=vf[:n];db=db[:n]
ok=vf&(db>-40)
semi=np.round(librosa.hz_to_midi(np.where(ok,f0,np.nan)))
notes=[];i=0
while i<n:
    if np.isnan(semi[i]): i+=1; continue
    j=i;gap=0
    while j+1<n:
        if semi[j+1]==semi[i]: j+=1;gap=0
        elif np.isnan(semi[j+1]) and gap<4: j+=1;gap+=1
        else: break
    dur=(j-i+1)*hop
    if dur>=0.8:
        m=int(semi[i]); t0=i*hop; t1=(j+1)*hop
        a=t0+0.2*(t1-t0); b=t0+0.8*(t1-t0)
        x=y[int(a*sr):int(b*sr)]
        fl=librosa.midi_to_hz(m-0.7); fh=librosa.midi_to_hz(m+0.7)
        p=librosa.yin(x,fmin=fl,fmax=fh,sr=sr,frame_length=4096,hop_length=480)
        c=(librosa.hz_to_midi(p)-m)*100
        fr0=np.median(p)
        # loudness
        r=librosa.feature.rms(y=x,frame_length=2048,hop_length=480)[0]; L=20*np.log10(r+1e-9)
        cen=librosa.feature.spectral_centroid(y=x,sr=sr,n_fft=4096,hop_length=480)[0]
        # HNR middle 1 s
        mid=(a+b)/2; s0=int((mid-0.5)*sr); w=y[s0:s0+sr]*np.hanning(sr)
        X=np.abs(np.fft.rfft(w))**2; fq=np.fft.rfftfreq(sr,1/sr); mask=np.zeros_like(X,bool)
        for h in range(1,int(8000/fr0)+1): mask|=np.abs(fq-h*fr0)<fr0*0.03
        band=fq<8000; hnr=10*np.log10(X[mask&band].sum()/X[~mask&band].sum())
        notes.append(dict(t=t0,dur=dur,m=m,w=librosa.midi_to_note(m+2,unicode=False),cents=float(np.median(c)),wob=float(np.std(c)),
            db=float(np.median(L)),dbsd=float(np.std(L)),bright=float(np.median(cen)/fr0),hnr=float(hnr)))
    i=j+1
json.dump(notes,open('notes.json','w'))
print(len(notes))
for x in notes: print(f"{x['t']/60:5.2f} {x['dur']:4.1f}s {x['w']:4s} {x['cents']:+4.0f}c wob{x['wob']:5.1f} {x['db']:6.1f}dB sd{x['dbsd']:.2f} br{x['bright']:4.1f} hnr{x['hnr']:5.1f}")

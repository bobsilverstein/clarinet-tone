import numpy as np, librosa, soundfile as sf, time, sys
y,sr=sf.read(sys.argv[1],dtype='float32')
y=librosa.resample(y,orig_sr=sr,target_sr=22050); sr=22050; hop=256
t=time.time(); F=[];V=[]
C=sr*30//hop*hop
for s in range(0,len(y),C):
    seg=y[s:s+C+2048]
    f0,vf,_=librosa.pyin(seg,fmin=120,fmax=1800,sr=sr,frame_length=2048,hop_length=hop,resolution=0.02,center=False)
    n=C//hop if s+C<len(y) else len(f0)
    F.append(f0[:n]);V.append(vf[:n])
f0=np.concatenate(F);vf=np.concatenate(V)
print(time.time()-t,len(f0))
rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=hop,center=False)[0]
cen=librosa.feature.spectral_centroid(y=y,sr=sr,n_fft=2048,hop_length=hop,center=False)[0]
m=min(len(f0),len(rms));np.savez(sys.argv[2],f0=f0[:m],vf=vf[:m],rms=rms[:m],cen=cen[:m],hop=hop/sr)

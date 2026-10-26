# Media

| File | What | Where it's used |
|---|---|---|
| `spendwise-walkthrough.mp4` | 4-minute walkthrough: first time, every week, on a phone (1280×720, H.264) | README, LinkedIn |
| `spendwise-demo.gif` | 53-second highlights at double speed (800 px) | README |

Both are built from the Playwright recordings (`e2e/demo/record.spec.ts`, see
[DEVELOPMENT.md](../DEVELOPMENT.md#re-recording-the-walkthrough-gif-and-manual-screenshots)):

```bash
cd e2e/test-results/demo-videos
# MP4: trim the blank first frames of part 1, centre the phone part on a teal background
ffmpeg -ss 2.3 -i part1.webm -i part2.webm -ss 0.5 -i part3.webm -filter_complex   "[0:v]fps=30,setsar=1[a];[1:v]fps=30,setsar=1[b];   [2:v]scale=-2:700,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x134e4a,fps=30,setsar=1[c];   [a][b][c]concat=n=3:v=1:a=0[v]" -map "[v]" -c:v libx264 -preset slow -crf 24   -pix_fmt yuv420p -movflags +faststart ../../../docs/media/spendwise-walkthrough.mp4

# GIF: nine highlights (start:end:speed, seconds into the MP4), 8 fps, 800 px, 96 colours
#   0:2.5:1 23:41:2 56:66:2 87:103:2 106:118:2 125:136:2 176:186:2 195:208:2 219:231:2
```

The timestamps depend on the recording; check them against a contact sheet
(`ffmpeg -i spendwise-walkthrough.mp4 -vf "fps=1/8,scale=320:-1,tile=4x8" sheet.png`) after
re-recording.

# Video Frame Understanding Test Frames

These four frames are regression samples for `video-frame-understanding`.

Use them to check whether prompt or script changes keep the intended behavior:

- prioritize screen/PPT/demo material over speaker or venue description
- preserve small explanatory text when readable
- mark unreadable content as unclear instead of inventing details
- output one script-generated JSON record per frame with `timestamp`, `video_topic`, and `frame_content`

Run from the skill root:

```bash
python eval/run_test_frames.py --video-topic "阿里云 2026 峰会主论坛下午场"
```

The eval writes timestamped outputs under `eval/test_runs/`.

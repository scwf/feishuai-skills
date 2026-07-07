import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import video_frame_understanding


class VideoFrameUnderstandingTests(unittest.TestCase):
    def test_summary_preserves_complete_ordered_frame_records(self):
        repeated_content = "相同的发布材料内容，用来验证连续相似帧不会被省略。"
        long_content = (
            "开场标题：完整内容验证。"
            + "这是需要保留的长段落内容，" * 80
            + "结尾标记：SHOULD_KEEP_FULL_TEXT"
        )
        records = [
            {
                "timestamp": "00:00:30",
                "video_topic": "测试主题",
                "frame_content": repeated_content,
            },
            {
                "timestamp": "00:01:00",
                "video_topic": "测试主题",
                "frame_content": repeated_content,
            },
            {
                "timestamp": "00:01:30",
                "video_topic": "测试主题",
                "frame_content": long_content,
            },
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            summary_path = Path(tmp_dir) / "summary.md"
            video_frame_understanding.build_summary(records, summary_path, "测试主题")
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("### 00:00:30", summary)
        self.assertIn("### 00:01:00", summary)
        self.assertIn("### 00:01:30", summary)
        self.assertEqual(summary.count(repeated_content), 2)
        self.assertIn("结尾标记：SHOULD_KEEP_FULL_TEXT", summary)
        self.assertNotIn("已省略连续相似帧", summary)
        self.assertNotIn("…", summary)


if __name__ == "__main__":
    unittest.main()

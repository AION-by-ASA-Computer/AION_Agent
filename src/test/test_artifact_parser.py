import unittest
from src.runtime.artifact_parser import (
    ArtifactEvent,
    MarkdownArtifactStreamParser,
    XMLArtifactStreamParser,
)

class TestArtifactStreamParser(unittest.TestCase):
    def test_plain_text(self):
        parser = XMLArtifactStreamParser()
        events = parser.feed("Hello world")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, ArtifactEvent.TEXT)
        self.assertEqual(events[0].content, "Hello world")

    def test_complete_artifact(self):
        parser = XMLArtifactStreamParser()
        tokens = [
            "Intro text. ",
            "<aion_artifact identifier=\"test_id\" type=\"python\" title=\"Test Artifact\">",
            "print('hello')\n",
            "result = 42",
            "</aion_artifact>",
            " Outro text."
        ]
        all_events = []
        for t in tokens:
            all_events.extend(parser.feed(t))
        
        # Verify sequence
        self.assertEqual(all_events[0].event, ArtifactEvent.TEXT)
        self.assertEqual(all_events[1].event, ArtifactEvent.ARTIFACT_START)
        self.assertEqual(all_events[1].artifact_id, "test_id")
        self.assertEqual(all_events[2].event, ArtifactEvent.ARTIFACT_CONTENT)
        self.assertEqual(all_events[3].event, ArtifactEvent.ARTIFACT_CONTENT)
        self.assertEqual(all_events[4].event, ArtifactEvent.ARTIFACT_END)
        self.assertEqual(all_events[4].content, "print('hello')\nresult = 42")
        self.assertEqual(all_events[5].event, ArtifactEvent.TEXT)

    def test_fragmented_tags(self):
        parser = XMLArtifactStreamParser()
        # Fragmenting <aion_artifact...
        tokens = ["Text <ai", "on_artif", "act ident", "ifier=\"id\">", "content", "</ai", "on_artifact>"]
        all_events = []
        for t in tokens:
            all_events.extend(parser.feed(t))
        
        self.assertEqual(all_events[0].event, ArtifactEvent.TEXT)
        self.assertEqual(all_events[0].content, "Text ")
        self.assertEqual(all_events[1].event, ArtifactEvent.ARTIFACT_START)
        self.assertEqual(all_events[1].artifact_id, "id")
        self.assertEqual(all_events[2].event, ArtifactEvent.ARTIFACT_CONTENT)
        self.assertEqual(all_events[2].content, "content")
        self.assertEqual(all_events[3].event, ArtifactEvent.ARTIFACT_END)

    def test_unclosed_artifact_flush(self):
        parser = XMLArtifactStreamParser()
        feed_events = parser.feed("Text <aion_artifact identifier=\"id\">some content")
        flush_events = parser.flush()
        self.assertEqual(feed_events[0].event, ArtifactEvent.TEXT)
        self.assertEqual(feed_events[0].content, "Text ")
        self.assertTrue(any(e.event == ArtifactEvent.ARTIFACT_END for e in flush_events))
        end = next(e for e in flush_events if e.event == ArtifactEvent.ARTIFACT_END)
        self.assertEqual(end.content, "some content")
        self.assertEqual(end.artifact_id, "id")

    def test_auto_execute_attr(self):
        parser = XMLArtifactStreamParser()
        events = parser.feed("<aion_artifact identifier=\"id\" auto_execute=\"true\">")
        self.assertTrue(events[0].auto_execute)
        
        parser = XMLArtifactStreamParser()
        events = parser.feed("<aion_artifact identifier=\"id\" auto_execute=\"1\">")
        self.assertTrue(events[0].auto_execute)

    def test_markdown_html_without_metadata_infers_artifact(self):
        parser = MarkdownArtifactStreamParser()
        block = "```html\n<!DOCTYPE html>\n<html><body>ok</body></html>\n```"
        events: list = []
        for ch in block:
            events.extend(parser.feed(ch))
        events.extend(parser.flush())
        starts = [e for e in events if e.event == ArtifactEvent.ARTIFACT_START]
        self.assertTrue(starts, msg=[(e.event, getattr(e, "artifact_id", None)) for e in events])
        self.assertEqual(starts[0].artifact_id, "inferred_html_page")
        self.assertEqual(starts[0].filename, "page.html")

    def test_markdown_metadata_without_hash_prefix(self):
        parser = MarkdownArtifactStreamParser()
        block = (
            "```markdown\n"
            "artifact_id: wwdc_guide\n"
            "title: WWDC Guide\n"
            "filename: wwdc-guide.md\n"
            "# WWDC 2026\n"
            "Body " + ("x" * 300) + "\n"
            "```"
        )
        events: list = []
        events.extend(parser.feed(block))
        events.extend(parser.flush())
        starts = [e for e in events if e.event == ArtifactEvent.ARTIFACT_START]
        ends = [e for e in events if e.event == ArtifactEvent.ARTIFACT_END]
        self.assertTrue(starts)
        self.assertEqual(starts[0].artifact_id, "wwdc_guide")
        self.assertEqual(starts[0].filename, "wwdc-guide.md")
        self.assertIn("# WWDC 2026", ends[0].content)

    def test_markdown_infers_from_heading_when_metadata_missing(self):
        parser = MarkdownArtifactStreamParser()
        block = "```markdown\n# Apple WWDC 2026 Guide\n\n" + ("detail\n" * 80) + "```"
        events: list = parser.feed(block) + parser.flush()
        starts = [e for e in events if e.event == ArtifactEvent.ARTIFACT_START]
        self.assertTrue(starts)
        self.assertEqual(starts[0].artifact_id, "apple_wwdc_2026_guide")

if __name__ == "__main__":
    unittest.main()

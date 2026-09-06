import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from sutang_telegram_bridge.attachments import expand_archive, safe_name


class AttachmentTests(unittest.TestCase):
    def test_safe_zip_extracts_regular_files(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "ok.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("docs/readme.txt", "hello")
            files = expand_archive(archive, 10, 1024)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_text(), "hello")

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("../escape.txt", "no")
            with self.assertRaisesRegex(ValueError, "traversal"):
                expand_archive(archive, 10, 1024)
            self.assertFalse((Path(temp).parent / "escape.txt").exists())

    def test_tar_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.tar"
            with tarfile.open(archive, "w") as out:
                info = tarfile.TarInfo("link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                out.addfile(info, io.BytesIO())
            with self.assertRaisesRegex(ValueError, "special"):
                expand_archive(archive, 10, 1024)

    def test_filename_is_reduced_to_basename(self):
        self.assertEqual(safe_name("../../hello world.txt"), "hello_world.txt")

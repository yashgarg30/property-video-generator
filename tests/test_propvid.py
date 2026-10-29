"""Run:  python -m unittest discover tests -v"""
import os
import sys
import tempfile
import unittest

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from propvid.listing import Listing, ListingError  # noqa: E402
from propvid.pipeline import Options, generate  # noqa: E402
from propvid.script import build_template_script, fact_check  # noqa: E402


def make_images(d, n, size=(800, 500)):
    paths = []
    for i in range(n):
        p = os.path.join(d, f"img{i}.jpg")
        Image.new("RGB", size, (40 * i % 255, 120, 180)).save(p)
        paths.append(p)
    return paths


class ValidationTests(unittest.TestCase):
    def test_missing_name_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            errs, _, _ = Listing(images=make_images(d, 4)).validate()
            self.assertTrue(any("name" in e for e in errs))

    def test_no_images_is_error(self):
        errs, _, _ = Listing(name="X", images=["nope.jpg"]).validate()
        self.assertTrue(any("No usable images" in e for e in errs))

    def test_bad_and_tiny_images_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            good = make_images(d, 2)
            bad = os.path.join(d, "bad.jpg")
            open(bad, "w").write("not an image")
            tiny = os.path.join(d, "tiny.png")
            Image.new("RGB", (50, 50)).save(tiny)
            errs, warns, usable = Listing(name="X", images=good + [bad, tiny]).validate()
            self.assertEqual(errs, [])
            self.assertEqual(usable, good)
            self.assertTrue(any("bad.jpg" in w for w in warns))
            self.assertTrue(any("too small" in w for w in warns))
            self.assertTrue(any("recommended" in w for w in warns))

    def test_more_than_eight_images_trimmed(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, usable = Listing(name="X", images=make_images(d, 10)).validate()
            self.assertEqual(len(usable), 8)

    def test_bad_json_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{bad json")
        with self.assertRaises(ListingError) as ctx:
            Listing.from_json_file(fh.name)
        self.assertIn("not valid JSON", str(ctx.exception))
        os.unlink(fh.name)

    def test_features_string_split(self):
        l = Listing.from_dict({"features": "A; B\nC"})
        self.assertEqual(l.features, ["A", "B", "C"])


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.l = Listing(name="Skyline", location="Sector 62", price="₹1.25 Crore",
                         property_type="2 BHK Apartment", features=["Modular kitchen", "Gym"],
                         cta="Call now", contact="+91 90000 00000", images=["a", "b", "c", "d"])

    def test_scene_structure(self):
        s = build_template_script(self.l, self.l.images)
        self.assertEqual([x.kind for x in s.scenes], ["title", "feature", "feature", "price", "cta"])

    def test_template_uses_only_input_facts(self):
        s = build_template_script(self.l, self.l.images)
        for scene in s.scenes:
            self.assertEqual(fact_check(scene.narration, self.l), [], scene.narration)

    def test_fact_check_catches_invented_facts(self):
        self.assertTrue(fact_check("Just 5 minutes from the metro.", self.l))
        self.assertTrue(fact_check("Available at ₹1.5 Crore.", self.l))
        self.assertEqual(fact_check("Enjoy the modular kitchen.", self.l), [])

    def test_missing_optional_fields_skip_scenes(self):
        l = Listing(name="Only Name", images=["a"])
        kinds = [x.kind for x in build_template_script(l, l.images).scenes]
        self.assertNotIn("price", kinds)
        self.assertEqual(kinds[0], "title")
        self.assertEqual(kinds[-1], "cta")


class EndToEndTest(unittest.TestCase):
    def test_renders_mp4(self):
        with tempfile.TemporaryDirectory() as d:
            l = Listing(name="Test Home", price="₹50 Lakh", features=["Garden"], images=make_images(d, 4))
            out = os.path.join(d, "v.mp4")
            res = generate(l, out, Options(narration=False, fps=12))
            self.assertTrue(os.path.getsize(out) > 10_000)
            self.assertTrue(os.path.isfile(res.thumbnail))
            self.assertTrue(10 < res.duration < 45)


class WebFormTests(unittest.TestCase):
    """Starts the real web server on a free port and posts multipart forms to it."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        import app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, fields, files=()):
        import urllib.error
        import urllib.request
        boundary = "----propvidtest"
        body = b""
        for k, v in fields.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for path in files:
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="images"; '
                     f'filename="{os.path.basename(path)}"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
            body += open(path, "rb").read() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/generate", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_form_page_loads(self):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r:
            self.assertIn("Generate video", r.read().decode())

    def test_missing_input_shows_friendly_error(self):
        status, html_ = self.post({"name": "", "music": "1"})
        self.assertEqual(status, 400)
        self.assertIn("Cannot create video", html_)
        self.assertNotIn("Traceback", html_)

    def test_upload_generates_video_with_preview(self):
        with tempfile.TemporaryDirectory() as d:
            status, html_ = self.post({"name": "Form Home", "price": "₹40 Lakh",
                                       "features": "Garden\nParking"}, make_images(d, 4))
        self.assertEqual(status, 200)
        self.assertIn("<video", html_)
        self.assertIn("Download MP4", html_)
        import re
        import urllib.request
        link = re.search(r'href="(/runs/[^"]+\.mp4\?dl=1)"', html_).group(1)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{link}") as r:
            self.assertEqual(r.status, 200)
            self.assertIn("attachment", r.headers.get("Content-Disposition", ""))
            self.assertGreater(len(r.read()), 10_000)


if __name__ == "__main__":
    unittest.main()
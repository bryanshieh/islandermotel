import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from audits import checklist
from audits.management.commands.serve_phone import allowed_hosts, lan_addresses
from audits.models import Audit, Finding, Room
from audits.photos import MAX_SIDE, NotAPhoto, shrink_photo

MEDIA = tempfile.mkdtemp()


def image_file(size, fmt="JPEG", mode="RGB", name="photo.jpg", exif_orientation=None):
    image = Image.new(mode, size, "red")
    buffer = BytesIO()
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    image.save(buffer, fmt, **kwargs)
    return SimpleUploadedFile(name, buffer.getvalue())


class ShrinkPhotoTests(SimpleTestCase):
    def open(self, content_file):
        return Image.open(BytesIO(content_file.read()))

    def test_large_photo_is_scaled_down_keeping_its_shape(self):
        result = shrink_photo(image_file((4000, 3000)))
        image = self.open(result)
        self.assertEqual(image.size, (MAX_SIDE, 1200))
        self.assertEqual(image.format, "JPEG")
        self.assertTrue(result.name.endswith(".jpg"))

    def test_small_photo_is_not_enlarged(self):
        self.assertEqual(self.open(shrink_photo(image_file((800, 600)))).size, (800, 600))

    def test_png_with_transparency_becomes_jpeg(self):
        result = shrink_photo(image_file((300, 200), fmt="PNG", mode="RGBA", name="shot.png"))
        image = self.open(result)
        self.assertEqual((image.format, image.mode, result.name), ("JPEG", "RGB", "shot.jpg"))

    def test_sideways_phone_photo_is_turned_upright(self):
        # Orientation 6: stored landscape, should display portrait.
        result = shrink_photo(image_file((400, 200), exif_orientation=6))
        self.assertEqual(self.open(result).size, (200, 400))

    def test_file_that_is_not_an_image_is_rejected(self):
        with self.assertRaises(NotAPhoto):
            shrink_photo(SimpleUploadedFile("notes.jpg", b"this is not a picture"))


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_motel", verbosity=0)
        cls.user = User.objects.create_superuser("bryan", "", "pw")
        cls.room = Room.objects.get(number="101")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.user)
        self.audit = Audit.objects.create(room=self.room, cycle_year=2026)
        self.url = reverse("finding_update", args=[self.audit.pk])
        entries = checklist.build_zone(self.audit, "bathroom")
        self.key = next(e for e in entries if e.label == "Toilet").checks[0].key
        self.client.post(self.url, {"key": self.key, "result": "damaged"})

    def test_uploaded_photo_is_stored_shrunk(self):
        self.client.post(self.url, {"key": self.key, "photo": image_file((4000, 3000))})
        finding = Finding.objects.get()
        with finding.photo.open() as stored:
            self.assertEqual(Image.open(stored).size, (MAX_SIDE, 1200))

    def test_replacing_a_photo_removes_the_old_file(self):
        self.client.post(self.url, {"key": self.key, "photo": image_file((100, 100), name="a.jpg")})
        first = Finding.objects.get().photo
        first_name, storage = first.name, first.storage
        self.client.post(self.url, {"key": self.key, "photo": image_file((100, 100), name="b.jpg")})
        self.assertFalse(storage.exists(first_name))
        self.assertTrue(storage.exists(Finding.objects.get().photo.name))

    def test_bad_file_shows_an_error_and_keeps_the_finding(self):
        bad = SimpleUploadedFile("notes.jpg", b"not a picture")
        response = self.client.post(self.url, {"key": self.key, "photo": bad})
        self.assertContains(response, "not a photo the app can read")
        finding = Finding.objects.get()
        self.assertFalse(finding.photo)
        self.assertEqual(finding.result, "damaged")

    def test_photos_need_a_login(self):
        self.client.post(self.url, {"key": self.key, "photo": image_file((100, 100))})
        photo_url = Finding.objects.get().photo.url
        self.assertEqual(self.client.get(photo_url).status_code, 200)
        self.client.logout()
        response = self.client.get(photo_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])


class ServePhoneTests(SimpleTestCase):
    def test_lan_addresses_never_include_loopback(self):
        for address in lan_addresses():
            self.assertFalse(address.startswith("127."))

    def test_allowed_hosts_cover_lan_tailscale_and_extras(self):
        self.assertEqual(
            allowed_hosts(["192.168.1.23"], ["100.64.0.5"]),
            ["192.168.1.23", ".ts.net", "100.64.0.5"],
        )

    def test_phone_layout_is_in_the_base_template(self):
        page = self.client.get("/login/").content.decode()
        self.assertIn("@media (max-width: 600px)", page)
        self.assertIn('name="viewport"', page)

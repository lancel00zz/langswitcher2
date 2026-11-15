import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Config


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'settings.json'
        self.config = Config(self.path)

    def test_old_flat_file_still_loads(self):
        self.path.write_text(json.dumps({'BUFFER_SIZE': 6, 'SWITCH_THRESHOLD': 4}))
        config = Config(self.path)
        self.assertEqual((config.detection.buffer_size, config.detection.switch_threshold), (6, 4))

    def test_legacy_timing_settings_cannot_restore_speed_limits(self):
        self.path.write_text(json.dumps({'schema_version': 1, 'frustration': {
            'enabled': False, 'time_window': 0.01, 'cooldown': 999.0}}))
        loaded = Config(self.path)
        self.assertFalse(loaded.frustration.enabled)
        self.assertNotIn('frustration.cooldown', loaded.editable_values())
        self.assertNotIn('frustration.time_window', loaded.editable_values())
        loaded.save()
        self.assertEqual(json.loads(self.path.read_text())['frustration'], {'enabled': False})

    def test_saved_detection_and_correction_settings_survive_restart(self):
        values = self.config.editable_values()
        values.update({
            'detection.buffer_size': '8',
            'detection.switch_threshold': '5',
            'detection.min_word_length': '3',
            'detection.model_confidence_threshold': '0.8',
            'detection.fallback_to_buffer_on_ambiguous': False,
            'frustration.enabled': False,
        })
        candidate = self.config.with_settings(values)
        candidate.save()
        reloaded = Config(self.path)
        self.assertEqual(candidate.editable_values(), reloaded.editable_values())
        self.assertEqual(self.config.detection.switch_threshold, 3)
        self.assertTrue(self.config.frustration.enabled)

    def test_invalid_form_cannot_mutate_live_configuration(self):
        for key, value in [('detection.switch_threshold', '9'),
                           ('detection.model_confidence_threshold', 'nan'),
                           ('detection.model_confidence_threshold', 'inf'),
                           ('detection.min_word_length', '0')]:
            with self.subTest(key=key):
                original = self.config.editable_values()
                values = dict(original)
                values[key] = value
                with self.assertRaises(ValueError):
                    self.config.with_settings(values)
                self.assertEqual(self.config.editable_values(), original)
                self.assertFalse(self.path.exists())

    def test_invalid_file_keeps_all_defaults_instead_of_partial_update(self):
        self.path.write_text(json.dumps({'BUFFER_SIZE': 8, 'SWITCH_THRESHOLD': 99}))
        loaded = Config(self.path)
        self.assertEqual(loaded.editable_values(), self.config.editable_values())

    def test_failed_atomic_save_preserves_previous_file(self):
        self.config.save()
        before = self.path.read_bytes()
        self.config.detection.switch_threshold = 4
        with patch('config.os.replace', side_effect=OSError('disk write failed')):
            with self.assertRaises(OSError):
                self.config.save()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == '__main__':
    unittest.main()

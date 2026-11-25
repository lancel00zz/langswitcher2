"""
LangSwitcher Configuration Module

Validated configuration with atomic persistence and legacy format support.
"""

import json
import logging
import tempfile
from copy import deepcopy
import pathlib
import os
from typing import Dict, Any, Tuple
from dataclasses import dataclass, asdict


@dataclass
class DetectionConfig:
    """Language detection configuration"""
    buffer_size: int = 5
    switch_threshold: int = 3
    min_word_length: int = 2
    model_confidence_threshold: float = 0.65
    fallback_to_buffer_on_ambiguous: bool = True
    valid_punctuation: Tuple[str, ...] = ("'", "’", "-")
    
    def validate(self):
        """Validate configuration values"""
        if self.buffer_size < 1:
            raise ValueError("buffer_size must be at least 1")
        if self.switch_threshold < 1:
            raise ValueError("switch_threshold must be at least 1")
        if self.switch_threshold > self.buffer_size:
            raise ValueError("switch_threshold cannot exceed buffer_size")
        if self.min_word_length < 1:
            raise ValueError("min_word_length must be at least 1")
        if not 0.0 <= self.model_confidence_threshold <= 1.0:
            raise ValueError("model_confidence_threshold must be between 0.0 and 1.0")


@dataclass
class FrustrationConfig:
    """Frustration detection configuration"""
    enabled: bool = True


@dataclass
class FlagOverlayConfig:
    """Appearance of the brief keyboard-layout flag; 100% is 390 by 234 px."""
    enabled: bool = True
    size_percent: int = 160
    position: str = 'center'
    opacity_percent: int = 50

    def validate(self):
        if type(self.enabled) is not bool:
            raise ValueError('flag_overlay.enabled must be a boolean')
        for name, minimum, maximum in (
                ('size_percent', 50, 250), ('opacity_percent', 20, 100)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'flag_overlay.{name} must be an integer between {minimum} and {maximum}')
        if self.position not in ('center', 'top_left', 'top_right', 'bottom_left', 'bottom_right'):
            raise ValueError('flag_overlay.position must be center, top_left, top_right, bottom_left, or bottom_right')


def _overlay_integer(value, name):
    """Parse integer form fields without silently truncating fractional values."""
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    raise ValueError(f'{name} must be an integer')


@dataclass
class LanguageConfig:
    """Language and layout configuration"""
    detection_langs: Tuple[str, ...] = ("en", "fr")
    layouts: Dict[str, Tuple[str, str]] = None
    dict_langs: Dict[str, str] = None
    
    def __post_init__(self):
        if self.layouts is None:
            self.layouts = {
                "en": ("com.apple.keylayout.US", "🇺🇸"),
                "fr": ("com.apple.keylayout.Canadian-CSA", "🇫🇷"),
            }
        if self.dict_langs is None:
            self.dict_langs = {"en": "en_US", "fr": "fr_FR"}
    
    def validate(self):
        """Validate configuration values"""
        if len(self.detection_langs) < 2:
            raise ValueError("At least 2 languages required")
        for lang in self.detection_langs:
            if lang not in self.layouts:
                raise ValueError(f"Layout missing for language: {lang}")
            if lang not in self.dict_langs:
                raise ValueError(f"Dictionary missing for language: {lang}")


@dataclass
class AppConfig:
    """Application configuration"""
    debug_log_path: str = None
    
    def __post_init__(self):
        if self.debug_log_path is None:
            self.debug_log_path = os.path.expanduser("~/langswitcher.log")


class Config:
    """Load legacy settings and persist validated settings."""

    SCHEMA_VERSION = 2
    
    def __init__(self, config_path: str = None):
        self.detection = DetectionConfig()
        self.frustration = FrustrationConfig()
        self.flag_overlay = FlagOverlayConfig()
        self.language = LanguageConfig()
        self.app = AppConfig()
        
        if config_path is None:
            # Determine config path based on run mode
            import sys
            
            # Check if running as bundled app (more reliable detection)
            is_bundled = (
                getattr(sys, 'frozen', False) or  # py2app sets this
                'Contents/Resources' in os.path.abspath(__file__) or  # In .app bundle
                '.app/Contents' in os.path.abspath(sys.argv[0])  # Executable in .app
            )
            
            if is_bundled:
                # Running as bundled app - save to Application Support
                app_support = os.path.expanduser('~/Library/Application Support/LangSwitcher')
                os.makedirs(app_support, exist_ok=True)
                self.config_path = pathlib.Path(app_support) / "main.conf.json"
            else:
                # Running as script - use project directory
                self.config_path = pathlib.Path(__file__).parent / "main.conf.json"
        else:
            self.config_path = pathlib.Path(config_path)
        
        # Load from file if exists
        self.load()
    
    def load(self):
        """Load configuration from JSON file"""
        if not self.config_path.exists():
            return
        
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
            
            candidate = deepcopy(self)
            # Support both old flat format and new nested format
            
            # OLD FORMAT (flat keys) - backward compatibility
            if 'BUFFER_SIZE' in data:
                candidate.detection.buffer_size = int(data['BUFFER_SIZE'])
            if 'SWITCH_THRESHOLD' in data:
                candidate.detection.switch_threshold = int(data['SWITCH_THRESHOLD'])
            if 'MIN_WORD_LENGTH' in data:
                candidate.detection.min_word_length = int(data['MIN_WORD_LENGTH'])
            if 'MODEL_CONFIDENCE_THRESHOLD' in data:
                candidate.detection.model_confidence_threshold = float(data['MODEL_CONFIDENCE_THRESHOLD'])
            if 'FALLBACK_TO_BUFFER_ON_AMBIGUOUS' in data:
                candidate.detection.fallback_to_buffer_on_ambiguous = bool(data['FALLBACK_TO_BUFFER_ON_AMBIGUOUS'])
            
            # NEW FORMAT (nested dicts)
            if 'detection' in data:
                det = data['detection']
                if 'buffer_size' in det:
                    candidate.detection.buffer_size = int(det['buffer_size'])
                if 'switch_threshold' in det:
                    candidate.detection.switch_threshold = int(det['switch_threshold'])
                if 'min_word_length' in det:
                    candidate.detection.min_word_length = int(det['min_word_length'])
                if 'model_confidence_threshold' in det:
                    candidate.detection.model_confidence_threshold = float(det['model_confidence_threshold'])
                if 'fallback_to_buffer_on_ambiguous' in det:
                    candidate.detection.fallback_to_buffer_on_ambiguous = bool(det['fallback_to_buffer_on_ambiguous'])
                if 'valid_punctuation' in det:
                    candidate.detection.valid_punctuation = tuple(det['valid_punctuation'])
            
            if 'frustration' in data:
                frust = data['frustration']
                if 'enabled' in frust:
                    candidate.frustration.enabled = bool(frust['enabled'])
            if 'flag_overlay' in data:
                overlay = data['flag_overlay']
                if 'enabled' in overlay:
                    candidate.flag_overlay.enabled = overlay['enabled']
                for name in ('size_percent', 'opacity_percent'):
                    if name in overlay:
                        setattr(candidate.flag_overlay, name,
                                _overlay_integer(overlay[name], f'flag_overlay.{name}'))
                if 'position' in overlay:
                    candidate.flag_overlay.position = overlay['position']
            if 'app' in data:
                app = data['app']
                if 'debug_log_path' in app:
                    candidate.app.debug_log_path = str(app['debug_log_path'])
            
            # Validate after loading
            candidate.validate()
            self.detection = candidate.detection
            self.frustration = candidate.frustration
            self.flag_overlay = candidate.flag_overlay
            self.app = candidate.app
        except Exception as e:
            print(f"Warning: Failed to load config from {self.config_path}: {e}")
    
    def editable_values(self):
        """Return the settings shown by the preferences window."""
        return {
            'detection.buffer_size': self.detection.buffer_size,
            'detection.switch_threshold': self.detection.switch_threshold,
            'detection.min_word_length': self.detection.min_word_length,
            'detection.model_confidence_threshold': self.detection.model_confidence_threshold,
            'detection.fallback_to_buffer_on_ambiguous': self.detection.fallback_to_buffer_on_ambiguous,
            'frustration.enabled': self.frustration.enabled,
            'flag_overlay.enabled': self.flag_overlay.enabled,
            'flag_overlay.size_percent': self.flag_overlay.size_percent,
            'flag_overlay.position': self.flag_overlay.position,
            'flag_overlay.opacity_percent': self.flag_overlay.opacity_percent,
        }

    def with_settings(self, values):
        """Parse and validate a settings edit without mutating the live config."""
        candidate = deepcopy(self)
        for key, old_value in self.editable_values().items():
            value = values[key]
            if isinstance(old_value, bool):
                if isinstance(value, str):
                    if value.lower() not in ('true', 'false', '1', '0'):
                        raise ValueError(f"Invalid boolean for {key}")
                    value = value.lower() in ('true', '1')
                elif not isinstance(value, bool):
                    raise ValueError(f"Invalid boolean for {key}")
            elif key in ('flag_overlay.size_percent', 'flag_overlay.opacity_percent'):
                value = _overlay_integer(value, key)
            else:
                value = type(old_value)(value)
            section, name = key.split('.')
            setattr(getattr(candidate, section), name, value)
        candidate.validate()
        return candidate

    def save(self):
        """Atomically persist all settings, including correction detection."""
        self.validate()
        data = {
            'schema_version': self.SCHEMA_VERSION,
            'detection': asdict(self.detection),
            'frustration': asdict(self.frustration),
            'flag_overlay': asdict(self.flag_overlay),
            'app': asdict(self.app),
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=self.config_path.parent,
                    prefix=self.config_path.name + '.', suffix='.tmp', delete=False) as stream:
                temporary_path = pathlib.Path(stream.name)
                json.dump(data, stream, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.config_path)
            logging.info("[CONFIG] Saved settings to %s", self.config_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def validate(self):
        """Validate all configuration sections"""
        self.detection.validate()
        self.flag_overlay.validate()
        self.language.validate()


# Global configuration instance
_config = None

def get_config() -> Config:
    """Get or create the global configuration instance"""
    global _config
    if _config is None:
        _config = Config()
    return _config


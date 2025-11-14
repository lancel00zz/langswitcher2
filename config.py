"""
LangSwitcher Configuration Module

Centralized configuration management with validation and persistence.
"""

import json
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
    valid_punctuation: Tuple[str, ...] = ("'", "'", "-")
    
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
    time_window: float = 1.5  # seconds - window for Key → Backspace pattern
    cooldown: float = 0.2  # seconds - minimal cooldown for rapid switches
    
    def validate(self):
        """Validate configuration values"""
        if self.time_window <= 0:
            raise ValueError("time_window must be positive")
        if self.cooldown < 0:
            raise ValueError("cooldown cannot be negative")


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
    """Main configuration manager"""
    
    def __init__(self, config_path: str = None):
        self.detection = DetectionConfig()
        self.frustration = FrustrationConfig()
        self.language = LanguageConfig()
        self.app = AppConfig()
        
        if config_path is None:
            # Use default path relative to main script
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
            
            # Support both old flat format and new nested format
            
            # OLD FORMAT (flat keys) - backward compatibility
            if 'BUFFER_SIZE' in data:
                self.detection.buffer_size = int(data['BUFFER_SIZE'])
            if 'SWITCH_THRESHOLD' in data:
                self.detection.switch_threshold = int(data['SWITCH_THRESHOLD'])
            if 'MIN_WORD_LENGTH' in data:
                self.detection.min_word_length = int(data['MIN_WORD_LENGTH'])
            if 'MODEL_CONFIDENCE_THRESHOLD' in data:
                self.detection.model_confidence_threshold = float(data['MODEL_CONFIDENCE_THRESHOLD'])
            if 'FALLBACK_TO_BUFFER_ON_AMBIGUOUS' in data:
                self.detection.fallback_to_buffer_on_ambiguous = bool(data['FALLBACK_TO_BUFFER_ON_AMBIGUOUS'])
            
            # NEW FORMAT (nested dicts)
            if 'detection' in data:
                det = data['detection']
                if 'buffer_size' in det:
                    self.detection.buffer_size = int(det['buffer_size'])
                if 'switch_threshold' in det:
                    self.detection.switch_threshold = int(det['switch_threshold'])
                if 'min_word_length' in det:
                    self.detection.min_word_length = int(det['min_word_length'])
                if 'model_confidence_threshold' in det:
                    self.detection.model_confidence_threshold = float(det['model_confidence_threshold'])
                if 'fallback_to_buffer_on_ambiguous' in det:
                    self.detection.fallback_to_buffer_on_ambiguous = bool(det['fallback_to_buffer_on_ambiguous'])
                if 'valid_punctuation' in det:
                    self.detection.valid_punctuation = tuple(det['valid_punctuation'])
            
            if 'frustration' in data:
                frust = data['frustration']
                if 'enabled' in frust:
                    self.frustration.enabled = bool(frust['enabled'])
                if 'time_window' in frust:
                    self.frustration.time_window = float(frust['time_window'])
                if 'cooldown' in frust:
                    self.frustration.cooldown = float(frust['cooldown'])
            
            if 'app' in data:
                app = data['app']
                if 'debug_log_path' in app:
                    self.app.debug_log_path = str(app['debug_log_path'])
            
            # Validate after loading
            self.validate()
        except Exception as e:
            print(f"Warning: Failed to load config from {self.config_path}: {e}")
    
    def save(self, detection_only: bool = True):
        """Save configuration to JSON file
        
        Args:
            detection_only: If True, only save detection settings (for UI compatibility)
        """
        if detection_only:
            # Keep backward compatibility with existing settings UI
            data = {
                "BUFFER_SIZE": self.detection.buffer_size,
                "SWITCH_THRESHOLD": self.detection.switch_threshold,
                "MIN_WORD_LENGTH": self.detection.min_word_length,
                "MODEL_CONFIDENCE_THRESHOLD": self.detection.model_confidence_threshold,
                "FALLBACK_TO_BUFFER_ON_AMBIGUOUS": self.detection.fallback_to_buffer_on_ambiguous,
            }
        else:
            # Full configuration export
            data = {
                "detection": asdict(self.detection),
                "frustration": asdict(self.frustration),
                "app": asdict(self.app),
            }
        
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def validate(self):
        """Validate all configuration sections"""
        self.detection.validate()
        self.frustration.validate()
        self.language.validate()


# Global configuration instance
_config = None

def get_config() -> Config:
    """Get or create the global configuration instance"""
    global _config
    if _config is None:
        _config = Config()
    return _config


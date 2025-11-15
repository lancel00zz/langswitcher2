#!/usr/bin/env python3
"""
LangSwitcher 2.0 - Automatic Keyboard Layout Switcher

A macOS menu bar application that automatically switches keyboard layouts
based on language detection, with frustration pattern detection for manual
override assistance.
"""

import os
import logging

from config import get_config
from ui import LangSwitcherApp
from version import __version__, __app_name__, __version_full__


def setup_logging(log_path: str):
    """Configure logging"""
    # Remove any existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    # Create file handler with immediate flushing
    file_handler = logging.FileHandler(log_path, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    
    # Add console handler for real-time output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    
    # Configure root logger
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(file_handler)
    logging.root.addHandler(console_handler)
    
    logging.info(f"=== {__app_name__} {__version_full__} Started ===")


def main():
    """Main entry point"""
    # Load configuration
    config = get_config()
    
    # Setup logging
    setup_logging(config.app.debug_log_path)
    
    # Log startup info
    logging.info(f"Config path: {config.config_path}")
    logging.info(f"Languages: {config.language.detection_langs}")
    logging.info(f"Buffer size: {config.detection.buffer_size}")
    logging.info(f"Switch threshold: {config.detection.switch_threshold}")
    logging.info(f"Min word length: {config.detection.min_word_length}")
    logging.info(f"Model confidence: {config.detection.model_confidence_threshold}")
    logging.info(f"Frustration detection: {config.frustration.enabled}")
    
    # Create and run app
    app = LangSwitcherApp(config)
    app.run()


if __name__ == "__main__":
    main()

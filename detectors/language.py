"""
Language Detection Module

Detects language of typed text using langdetect and optional enchant dictionary.
"""

import logging
from copy import copy
from typing import Optional, List, Dict
from collections import deque

try:
    from langdetect import detect_langs, LangDetectException, DetectorFactory
    # langdetect otherwise varies its guesses for the same short input.
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logging.warning("langdetect not available")

try:
    import enchant
    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False
    logging.info("enchant not available - spell-check fallback disabled")

# Common words for quick detection. Words shared by multiple language lists
# remain ambiguous; list order must never decide their language.
COMMON_WORDS = {
    "en": {
        # 2-letter words (high-frequency, unambiguous)
        "am", "an", "as", "at", "be", "by", "do", "go", "he", "if",
        "in", "is", "it", "me", "my", "no", "of", "on", "or", "so",
        "to", "up", "us", "we",
        # Pronouns & determiners (uniquely English)
        "the", "you", "your", "our", "their", "this", "that", "these", "those",
        # Verbs (English-specific forms)
        "are", "was", "were", "have", "has", "had", "will", "would", "should",
        "could", "can", "may", "must", "shall", "been", "being",
        # Questions words
        "how", "what", "when", "where", "who", "why", "which",
        # Common particles & conjunctions
        "and", "not", "but", "with", "from", "about", "into", "through",
        "before", "after", "between", "under", "over", "such", "only",
        "just", "very", "too", "more", "most", "much", "some", "any",
        # Other high-frequency English
        "than", "then", "them", "they", "their", "there",
    },
    "fr": {
        # 2-letter words (high-frequency, unambiguous)
        "je", "tu", "il", "ce", "ça", "de", "du", "au", "en", "un",
        "ou", "où", "si", "et", "ne", "se", "te", "me", "le", "la",
        "sa", "ma", "ta", "es", "ai", "as", "va", "on", "ni", "eu",
        # Articles & determiners (uniquely French)
        "les", "des", "une", "cette", "ces", "cet", "mes", "tes", "ses",
        # Pronouns (French-specific)
        "nous", "vous", "leur", "leurs", "lui", "elle", "elles", "eux",
        # Verbs (French-specific forms)
        "sont", "était", "étaient", "avez", "avons", "avait", "sera",
        "serait", "pourrait", "devrait", "peut", "ont", "été", "étant",
        # Question words
        "comment", "quoi", "quand", "quand", "qui", "pourquoi", "quel", "quelle",
        # Common prepositions & conjunctions
        "avec", "sans", "pour", "dans", "sur", "sous", "avant", "après",
        "entre", "très", "plus", "moins", "beaucoup", "peu", "tous", "tout",
        "toute", "chaque", "quelque", "plusieurs", "aussi", "alors",
    }
}


class LanguageDetector:
    """Detects language from typed text with buffering"""
    
    def __init__(
        self,
        detection_langs: List[str],
        dict_langs: Dict[str, str],
        buffer_size: int = 6,
        switch_threshold: int = 5,
        min_word_length: int = 4,
        confidence_threshold: float = 0.7,
        fallback_to_buffer: bool = True
    ):
        """
        Initialize language detector
        
        Args:
            detection_langs: List of language codes to detect (e.g., ['en', 'fr'])
            dict_langs: Map of language codes to dictionary codes (e.g., {'en': 'en_US'})
            buffer_size: Number of recent detections to keep
            switch_threshold: Number of consecutive detections needed to trigger switch
            min_word_length: Minimum word length to process
            confidence_threshold: Minimum confidence score (0.0-1.0)
            fallback_to_buffer: Whether to inherit last language on ambiguous words
        """
        self.detection_langs = detection_langs
        self.dict_langs = dict_langs
        self.buffer_size = buffer_size
        self.switch_threshold = switch_threshold
        self.min_word_length = min_word_length
        self.confidence_threshold = confidence_threshold
        self.fallback_to_buffer = fallback_to_buffer
        
        # Language detection buffer (circular)
        self.lang_buffer = deque(maxlen=buffer_size)
        self._last_detection_is_evidence = False
        
        # Initialize dictionaries if available
        self.dicts = {}
        if ENCHANT_AVAILABLE:
            self._init_dictionaries()
    
    def _init_dictionaries(self):
        """Initialize enchant dictionaries"""
        for lang, dict_code in self.dict_langs.items():
            try:
                self.dicts[lang] = enchant.Dict(dict_code)
                logging.debug(f"Loaded dictionary: {dict_code}")
            except Exception as e:
                logging.warning(f"Failed to load dictionary {dict_code}: {e}")
    
    def detect(self, text: str, current_lang: Optional[str] = None) -> Optional[str]:
        """
        Detect language of text
        
        Args:
            text: Text to analyze
            current_lang: Current keyboard layout language (for ambiguous first words)
            
        Returns:
            Detected or contextual language code, or None if too short.
            Contextual fallbacks never count toward the switch threshold.
        """
        self._last_detection_is_evidence = False
        # Check minimum length
        if len(text) < self.min_word_length:
            logging.debug(f"Word too short: '{text}' (< {self.min_word_length})")
            return None
        
        logging.debug(f"Detecting language for: '{text}'")
        
        # Shared words are known to be ambiguous. A statistical guess must not
        # override that knowledge, even when the model reports high confidence.
        if len(self._common_word_matches(text)) > 1:
            return self._fallback_detection(text, current_lang)

        # 1. Check common words first (fast, unambiguous, context-aware)
        chosen = self._detect_common_word(text)
        
        # 2. Try dictionary if not a common word (comprehensive)
        if chosen is None and self.dicts:
            matches = self._dictionary_matches(text)
            if len(matches) > 1:
                return self._fallback_detection(text, current_lang)
            if matches:
                chosen = matches[0]
                logging.debug(f"Dictionary match: {chosen}")
        
        # 3. Fallback to langdetect model (statistical)
        if chosen is None:
            chosen = self._detect_with_model(text)
        
        # A fallback supplies context, not a new independent vote.
        if chosen is None:
            return self._fallback_detection(text, current_lang)
        
        self.lang_buffer.append(chosen)
        self._last_detection_is_evidence = True
        logging.debug(f"Buffer: {list(self.lang_buffer)}")
        
        return chosen
    
    def _detect_common_word(self, text: str) -> Optional[str]:
        """
        Check if word is in common words list
        
        Fast O(1) lookup for high-frequency words that are unambiguous.
        This provides speed and disambiguation for words like 'are' (verb vs unit).
        
        Note: Skips ALL CAPS words (acronyms like AI, API). Title case words
        (sentence starts like "Bonjour", "Hello") are checked with lowercase conversion.
        """
        # Skip common word check for ALL CAPS (acronyms: AI, API, SQL, etc.)
        if text.isupper() and len(text) > 1:
            logging.debug(f"Skipping common words for acronym: '{text}'")
            return None
        
        matches = self._common_word_matches(text)
        if len(matches) == 1:
            logging.debug(f"Common word match: '{text}' → {matches[0]}")
            return matches[0]
        
        return None

    def _common_word_matches(self, text: str) -> List[str]:
        """Return every configured language whose common list contains text."""
        text_lower = text.lower()
        return [
            lang for lang in self.detection_langs
            if text_lower in COMMON_WORDS.get(lang, ())
        ]
    
    def _detect_with_model(self, text: str) -> Optional[str]:
        """Detect using langdetect model"""
        if not LANGDETECT_AVAILABLE:
            return None
        
        try:
            probs = detect_langs(text)
        except LangDetectException:
            logging.debug(f"LangDetectException for: '{text}'")
            return None
        
        # Build scores for our target languages
        scores = {
            lang: next((p.prob for p in probs if p.lang == lang), 0.0)
            for lang in self.detection_langs
        }
        
        logging.debug(f"Detection scores: {scores}")
        
        # Check if max confidence meets threshold
        max_score = max(scores.values(), default=0.0)
        if max_score <= 0.0 or max_score < self.confidence_threshold:
            logging.debug(f"Confidence too low: {max_score:.2f} < {self.confidence_threshold}")
            return None
        
        # Return language with highest score
        return max(scores, key=scores.get)
    
    def _detect_with_dict(self, text: str) -> Optional[str]:
        """Detect using enchant dictionary"""
        matches = self._dictionary_matches(text)
        return matches[0] if len(matches) == 1 else None

    def _dictionary_matches(self, text: str) -> List[str]:
        """Return all dictionary matches so known ambiguity stays neutral."""
        return [
            lang for lang in self.detection_langs
            if lang in self.dicts and self.dicts[lang].check(text)
        ]
    
    def _fallback_detection(self, text: str, current_lang: Optional[str] = None) -> Optional[str]:
        """Fallback when detection is ambiguous"""
        if self.fallback_to_buffer and self.lang_buffer:
            # Inherit from last detection in buffer
            last = self.lang_buffer[-1]
            logging.debug(f"Ambiguous '{text}', inheriting from buffer: '{last}'")
            return last
        
        # First word scenario: use current keyboard layout
        if current_lang:
            logging.debug(f"Ambiguous '{text}', using current keyboard layout: '{current_lang}'")
            return current_lang
        
        logging.debug(f"Ambiguous '{text}', no fallback available, returning None")
        return None
    
    def should_switch(self, target_lang: str, current_lang: str) -> bool:
        """
        Check if we should switch to target language
        
        Args:
            target_lang: Target language to potentially switch to
            current_lang: Current active language
            
        Returns:
            True if switch should happen
        """
        if not self._last_detection_is_evidence or target_lang == current_lang:
            return False
        
        # Check if we have enough detections
        if len(self.lang_buffer) < self.switch_threshold:
            return False
        
        # Check last N detections
        recent = list(self.lang_buffer)[-self.switch_threshold:]
        
        # All recent detections must match target language
        all_match = all(lang == target_lang for lang in recent)
        
        if all_match:
            logging.info(f"Switch threshold met: {recent} → {target_lang}")
            return True
        
        return False
    
    def fresh(self):
        """Start independent evidence without waiting for an old worker task."""
        detector = copy(self)
        detector.lang_buffer = deque(maxlen=self.buffer_size)
        detector._last_detection_is_evidence = False
        return detector

    def clear_buffer(self):
        """Clear the detection buffer"""
        self.lang_buffer.clear()
        self._last_detection_is_evidence = False
        logging.debug("Detection buffer cleared")
    
    def get_buffer_state(self) -> List[str]:
        """Get current buffer contents"""
        return list(self.lang_buffer)

